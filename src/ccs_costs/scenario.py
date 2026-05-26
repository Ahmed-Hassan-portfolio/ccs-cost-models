"""Scenario orchestrator -- wires all engine modules end-to-end.

Replaces the NETL VBA Eval_Form macro. Takes a formation ID and region,
runs the complete calculation chain (thermo -> geo -> costs -> finance),
and returns the break-even CO2 storage price (FYBE).

The evaluate_scenario() function is the central integration point that
no individual module can replace. It encodes the exact wiring and unit
conversions between all subsystems.

NETL reference (Formation 1241_1, Chandeleur Area, GOA offshore):
    FYBE (2008$): $25.34/t
    FYBE (2024$): $72.20/t
    Injection wells: 5 (4 active + 1 spare)
    Pipeline diameter: 12 inches
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from ccs_costs.config import RegionConfig, load_region
from ccs_costs.costs import (
    InfrastructureModel,
    NETLDrillingRegression,
    IEAGHGDrillingRegression,
    PipelineCostModel,
    assemble_cost_catalog,
    calculate_decommissioning_costs,
    calculate_drilling_costs,
    calculate_infrastructure_costs,
    calculate_monitoring_costs,
    calculate_pipeline_costs,
    calculate_regulatory_costs,
    pipeline_diameter,
)
from ccs_costs.costs.catalog import CostClassification, CostItem, DepreciationCategory
from ccs_costs.finance import (
    EscalationConfig,
    FYBEResult,
    FinancialParams,
    RevenueStreams,
    TaxRegime,
    solve_fybe,
)
# FR instruments are handled in the financial model, not as cost items
# from ccs_costs.finance.fr_instruments import FRConfig, calculate_fr_costs
from ccs_costs.geo import (
    FormationProperties,
    ProjectTimeline,
    WellPlan,
    build_schedule,
    compute_injection_rate,
    estimate_fracture_pressure,
    get_formation,
    max_wells_from_capacity,
    monitoring_well_count,
    plume_area,
    required_injection_wells,
    storage_coefficient,
)
from ccs_costs.thermo import (
    brine_density,
    brine_viscosity,
    co2_density,
    co2_viscosity,
)


# ============================================================================
# Data Models
# ============================================================================


class ScenarioConfig(BaseModel):
    """Master input for a single scenario evaluation.

    All inputs needed to run the full calculation chain.
    Most parameters have sensible defaults.
    """

    formation_id: str
    region: str

    # Injection parameters
    injection_rate_tpa: float = 4_000_000  # NETL default: 4 Mt/yr
    capacity_factor: float = 0.85
    max_rate_per_well_tpd: float = 3660  # NETL default cap

    # Geological overrides
    storage_coefficient_method: str = "lookup"
    storage_coefficient_probability: str = "P50"
    injectivity_method: str = "valluri"

    # Infrastructure
    pipeline_distance_km: float | None = None  # None = use formation value
    infrastructure_model: str | None = None  # None = use region default
    operations_years: int | None = None  # None = use region default

    # Thermo
    co2_property_method: str = "duan"

    # Phase 6: parameter override support for sensitivity analysis and Monte Carlo
    formation_overrides: dict | None = None  # Applied to FormationProperties via model_copy
    economic_overrides: dict | None = None   # Applied to RevenueStreams (ets_price, co2_tax_rate)


class ScenarioResults(BaseModel):
    """Master output from a single scenario evaluation.

    Contains all key results, intermediate values, and the input config
    for full reproducibility.
    """

    # Primary outputs
    fybe: float  # Break-even CO2 price (base year $/t)
    fybe_current_year: float  # Escalated to current year $/t
    npv: float
    irr: float | None = None

    # Formation
    formation_id: str
    formation_name: str
    region: str

    # Geological
    co2_density_kgm3: float
    storage_coefficient: float
    plume_area_km2: float

    # Wells
    n_injection_wells: int
    n_monitoring_wells: int

    # Pipeline
    pipeline_diameter_inches: float
    pipeline_length_km: float

    # Costs (base year)
    total_capex: float
    total_opex: float
    cost_breakdown: dict[str, float] = {}  # by_category: drilling, pipeline, platform, etc.
    total_co2_stored_mt: float
    project_duration_years: int

    # Metadata
    currency: str
    base_year: int
    timestamp: str
    config: ScenarioConfig

    # FYBE interpretation: explains what the FYBE value means in context
    fybe_interpretation: str = ""

    def to_compact_dict(self) -> dict[str, Any]:
        """Return a compact dict with ~15 key fields for comparison."""
        return {
            "formation_id": self.formation_id,
            "formation_name": self.formation_name,
            "region": self.region,
            "fybe": round(self.fybe, 2),
            "fybe_current_year": round(self.fybe_current_year, 2),
            "fybe_interpretation": self.fybe_interpretation,
            "n_injection_wells": self.n_injection_wells,
            "n_monitoring_wells": self.n_monitoring_wells,
            "pipeline_diameter_inches": self.pipeline_diameter_inches,
            "pipeline_length_km": round(self.pipeline_length_km, 1),
            "total_capex": round(self.total_capex),
            "total_opex": round(self.total_opex),
            "total_co2_stored_mt": round(self.total_co2_stored_mt, 1),
            "co2_density_kgm3": round(self.co2_density_kgm3, 1),
            "storage_coefficient": self.storage_coefficient,
            "currency": self.currency,
            "base_year": self.base_year,
        }


# ============================================================================
# Core orchestrator
# ============================================================================


def evaluate_scenario(config: ScenarioConfig) -> ScenarioResults:
    """Full scenario evaluation -- the central wiring function.

    Maps to NETL VBA Eval_Form macro. Follows the exact sequence:
    1. Load region config and formation
    2. Thermo: CO2 + brine properties
    3. Geo: storage coefficient -> plume -> injectivity -> wells -> schedule
    4. Costs: pipeline + drilling + platform + monitoring + regulatory + decom
    5. Finance: cashflow model -> FYBE solver

    Args:
        config: ScenarioConfig with formation_id, region, and overrides.

    Returns:
        ScenarioResults with FYBE and all intermediate values.

    Raises:
        ValueError: If formation not found or injection is infeasible.
    """
    # ---------------------------------------------------------------
    # Step 1: Load region config and formation
    # ---------------------------------------------------------------
    region_config = load_region(config.region)
    formation = get_formation(config.region, config.formation_id)

    # Apply formation_overrides (for sensitivity analysis and Monte Carlo)
    if config.formation_overrides:
        formation = formation.model_copy(update=config.formation_overrides)

    # ---------------------------------------------------------------
    # Step 2: Thermo -- CO2 and brine properties
    # ---------------------------------------------------------------
    # CO2 at reservoir conditions
    rho_co2_res = co2_density(
        formation.pressure_mpa,
        formation.temperature_c,
        method=config.co2_property_method,
    )
    mu_co2_res = co2_viscosity(rho_co2_res, formation.temperature_c)

    # Brine at reservoir conditions
    salinity_frac = formation.salinity_ppm / 1e6
    rho_brine = brine_density(
        formation.temperature_c, formation.pressure_mpa, salinity_frac
    )
    mu_brine = brine_viscosity(
        formation.temperature_c, formation.pressure_mpa, salinity_frac
    )

    # CO2 at pipeline conditions (for pipeline sizing)
    costs_config = region_config.costs_config
    mudline_t_c = costs_config.get("mudline_temperature_c", 12.78)
    # Default mudline temperature: 12.78C (55F) for GOA, 4C for NCS
    if config.region == "us-goa":
        mudline_t_c = 12.78  # 55F
    elif "mudline_temperature_c" in costs_config:
        mudline_t_c = costs_config["mudline_temperature_c"]

    # Average pipeline pressure: use midpoint of typical pipeline pressures
    # NETL uses ~11.72 MPa (1700 psig) as average pipeline pressure
    pipeline_avg_p_mpa = 11.72  # Approximate for sizing
    rho_co2_pipe = co2_density(pipeline_avg_p_mpa, mudline_t_c, method="duan")
    mu_co2_pipe = co2_viscosity(rho_co2_pipe, mudline_t_c)

    # ---------------------------------------------------------------
    # Step 3: Geological calculations
    # ---------------------------------------------------------------
    # Storage coefficient
    sc = storage_coefficient(
        lithology=formation.lithology,
        depositional_environment=formation.depositional_environment,
        structure_type=formation.structure_type,
        probability=config.storage_coefficient_probability,
    )

    # Determine operations years
    ops_years = config.operations_years or region_config.timeline.operations_years or 30
    total_co2_tonnes = config.injection_rate_tpa * ops_years

    # Plume area
    pa_km2 = plume_area(
        total_co2_tonnes=total_co2_tonnes,
        storage_coefficient=sc,
        thickness_m=formation.thickness_m,
        porosity=formation.porosity,
        co2_density_kgm3=rho_co2_res,
    )

    # Fracture pressure
    frac_p = (
        formation.fracture_pressure_mpa
        if formation.fracture_pressure_mpa is not None
        else estimate_fracture_pressure(formation.depth_m)
    )

    # Injection rate (per well)
    max_rate_tpd = compute_injection_rate(
        method=config.injectivity_method,
        permeability_md=formation.permeability_md,
        thickness_m=formation.thickness_m,
        co2_viscosity_pas=mu_co2_res,
        brine_viscosity_pas=mu_brine,
        co2_density_kgm3=rho_co2_res,
        brine_density_kgm3=rho_brine,
        reservoir_pressure_mpa=formation.pressure_mpa,
        fracture_pressure_mpa=frac_p,
        max_rate_per_well_tpd=config.max_rate_per_well_tpd,
    )

    # Well count
    n_active = required_injection_wells(
        config.injection_rate_tpa, max_rate_tpd, config.capacity_factor
    )
    # NETL convention: add 1 spare well
    # NETL reference shows number_injection_wells = 5 with
    # number_active_injection_wells = 4 for the default scenario.
    n_injection = n_active + 1

    # Storage capacity constraint: prevent over-drilling of small formations.
    # Only activates when capacity_mt is available (NCS formations from CO2
    # Storage Atlas). GOA formations without capacity_mt are unaffected.
    cap_limit = max_wells_from_capacity(
        capacity_mt=getattr(formation, 'capacity_mt', None),
        injection_rate_tpa=config.injection_rate_tpa,
        operations_years=ops_years,
        max_rate_per_well_tpd=max_rate_tpd,
        capacity_factor=config.capacity_factor,
    )
    if cap_limit is not None and cap_limit < n_injection:
        n_injection = cap_limit
        n_active = n_injection - 1

    n_mon = monitoring_well_count(n_injection)

    # Well plan
    # NETL default: 2 in-reservoir monitoring wells (from drilling costs)
    # The monitoring_well_count gives 24 for 5 injection wells (for O&M satellite),
    # but only 2 actual physical in-reservoir monitoring wells are drilled.
    # n_monitoring in WellPlan = actual wells drilled for cost purposes.
    # NETL drills: n_injection + 1 strat test + 2 in-reservoir monitoring = total
    n_monitoring_drilled = 2  # NETL default: 2 in-reservoir monitoring wells drilled
    well_plan = WellPlan(
        n_injection=n_injection,
        n_monitoring=n_monitoring_drilled,
        n_stratigraphic_test=2,  # NETL default: 2 strat test wells for all formations
    )

    # ---------------------------------------------------------------
    # Step 4: Build project schedule
    # ---------------------------------------------------------------
    timeline = ProjectTimeline(
        screening_years=region_config.timeline.screening_years,
        characterization_years=region_config.timeline.characterization_years,
        permitting_years=region_config.timeline.permitting_years,
        construction_years=region_config.timeline.construction_years,
        operations_years=ops_years,
        pisc_years=region_config.timeline.pisc_years,
        start_year=region_config.escalation.project_start_year,
    )

    schedule = build_schedule(
        formation=formation,
        co2_density_kgm3=rho_co2_res,
        storage_coefficient=sc,
        well_plan=well_plan,
        injection_rate_tpa=config.injection_rate_tpa,
        timeline=timeline,
        total_co2_tonnes=total_co2_tonnes,
    )

    # Extract timing info from schedule for cost modules
    _char_year = _first_project_year_of_stage(schedule.timeline, "characterization")
    _ops_begin = _first_project_year_of_stage(schedule.timeline, "operations")
    _ops_end = _last_project_year_of_stage(schedule.timeline, "operations")
    _pisc_end = _last_project_year_of_stage(schedule.timeline, "pisc")

    # Construction year: use construction stage if it exists, otherwise fall
    # back to permitting stage (NETL combines "Permitting & Construction"
    # into a single stage with construction_years=0).
    _constr_begin = _first_project_year_of_stage(schedule.timeline, "construction")
    if not any(e.stage == "construction" for e in schedule.timeline):
        _constr_begin = _first_project_year_of_stage(schedule.timeline, "permitting")

    # ---------------------------------------------------------------
    # Step 5: Cost calculations
    # ---------------------------------------------------------------
    # Pipeline
    # NETL applies a routing factor (1.1x default) to the straight-line
    # formation distance to get the actual pipeline length.
    pipeline_config = costs_config.get("pipeline", {})
    routing_factor = pipeline_config.get("routing_factor", 1.0)
    if config.pipeline_distance_km is not None:
        pipeline_length_km = config.pipeline_distance_km
    else:
        pipeline_length_km = formation.distance_from_shore_km * routing_factor

    # Pipeline sizing at pipeline conditions
    dia_result = pipeline_diameter(
        flow_rate_tpa=config.injection_rate_tpa,
        length_km=pipeline_length_km,
        inlet_pressure_mpa=15.0,  # Typical pipeline inlet
        outlet_pressure_mpa=8.5,  # Typical pipeline outlet
        temperature_c=mudline_t_c,
        co2_density_kgm3=rho_co2_pipe,
        co2_viscosity_pas=mu_co2_pipe,
    )

    # Determine pipeline cost model
    if config.region == "us-goa":
        pipe_model = PipelineCostModel.NETL_QUESTOR
    else:
        pipe_model = PipelineCostModel.KNOOPE_2014

    pipeline_costs = calculate_pipeline_costs(
        diameter_result=dia_result,
        length_km=pipeline_length_km,
        model=pipe_model,
        offshore=True,
        water_depth_m=formation.water_depth_m,
        base_year=region_config.base_year,
        currency=region_config.currency,
        construction_year=_constr_begin,
        operations_begin=_ops_begin,
        operations_end=_ops_end,
        pisc_end=_pisc_end,
        decom_year=_pisc_end,
    )

    # Pipeline PISC adjustments:
    # 1. Remove PIPE-DECOM: NETL does not have a separate pipeline decom item.
    #    Pipeline decom is absorbed into the PISC O&M period.
    # 2. Adjust PIPE-OPEX-PISC: NETL uses a lower annual O&M rate during PISC
    #    than during operations (reduced maintenance during monitoring-only phase).
    #    PISC factor is ~0.778 of ops rate (NETL: $1,440K vs $1,849K/yr for 12").
    pisc_om_factor = pipeline_config.get("pisc_om_factor", 0.778)
    adjusted_items = []
    for item in pipeline_costs.items:
        if item.id == "PIPE-DECOM":
            continue  # Skip pipeline decom (absorbed into PISC O&M)
        if item.id == "PIPE-OPEX-PISC":
            # Reduce PISC annual rate
            item = item.model_copy(update={
                "amount_base_year": item.amount_base_year * pisc_om_factor,
            })
        adjusted_items.append(item)
    pipeline_costs.items = adjusted_items

    # Drilling
    if config.region == "us-goa":
        costs_yaml_path = (
            _data_root() / "regions" / config.region / "costs.yaml"
        )
        regression = NETLDrillingRegression(
            costs_yaml_path, formation_id=config.formation_id
        )
    else:
        # IEAGHG regression for non-US regions
        # Apply NCS escalation factor from region costs.yaml to bring
        # year-2000 EUR costs to current cost levels.
        drill_config = costs_config.get("drilling", {})
        escalation = drill_config.get("escalation_factor_2000_to_2024", 1.0)
        regression = IEAGHGDrillingRegression(escalation_factor=escalation)

    drilling_costs = calculate_drilling_costs(
        well_plan=well_plan,
        depth_m=formation.depth_m,
        water_depth_m=formation.water_depth_m,
        regression=regression,
        characterization_year=_char_year,
        construction_begin=_constr_begin,
        operations_begin=_ops_begin,
        operations_end=_ops_end,
        pisc_end=_pisc_end,
        n_monitoring_in_reservoir=n_monitoring_drilled,
        n_monitoring_above_seal=0,
    )

    # Infrastructure
    infra_model_str = config.infrastructure_model or region_config.infrastructure_model.value
    infra_model_map = {
        "platform_jacket": InfrastructureModel.PLATFORM_JACKET,
        "jacket": InfrastructureModel.PLATFORM_JACKET,
        "subsea_tieback": InfrastructureModel.SUBSEA_TIEBACK,
    }
    infra_model = infra_model_map.get(
        infra_model_str, InfrastructureModel.PLATFORM_JACKET
    )

    # Extract platform phase-split O&M from costs.yaml if available.
    # These provide correct ops/PISC cost timing to match NETL cost timing.
    infra_config = costs_config.get("infrastructure", {})
    primary_om_ops = infra_config.get("primary_om_ops")
    primary_om_pisc = infra_config.get("primary_om_pisc")
    satellite_om_ops = infra_config.get("satellite_om_ops")
    satellite_om_pisc = infra_config.get("satellite_om_pisc")

    infra_kwargs: dict = dict(
        model_type=infra_model,
        water_depth_m=formation.water_depth_m,
        n_wells=n_injection,
        base_year=region_config.base_year,
        currency=region_config.currency,
        construction_year=_constr_begin,
        operations_begin=_ops_begin,
        operations_end=_ops_end,
        pisc_end=_pisc_end,
        decom_year=_pisc_end,
        injection_rate_tpa=config.injection_rate_tpa,
    )
    # Phase-split O&M overrides only apply to jacket model
    if infra_model == InfrastructureModel.PLATFORM_JACKET:
        infra_kwargs["om_ops_total"] = primary_om_ops
        infra_kwargs["om_pisc_total"] = primary_om_pisc
    platform_primary = calculate_infrastructure_costs(**infra_kwargs)

    # Satellite platform (NETL has one for GOA)
    satellite_platform = None
    if infra_model == InfrastructureModel.PLATFORM_JACKET:
        from ccs_costs.costs.platform import platform_cost_jacket

        satellite_platform = platform_cost_jacket(
            water_depth_m=formation.water_depth_m,
            n_wells=n_injection,
            is_primary=False,
            base_year=region_config.base_year,
            currency=region_config.currency,
            construction_year=_constr_begin,
            operations_begin=_ops_begin,
            operations_end=_ops_end,
            pisc_end=_pisc_end,
            decom_year=_pisc_end,
            injection_rate_tpa=config.injection_rate_tpa,
            om_ops_total=satellite_om_ops,
            om_pisc_total=satellite_om_pisc,
        )

    # Monitoring
    # Compute seismic area for area-dependent monitoring cost scaling.
    # GOA formations have seismic_3d_mi2 from NETL Res_Bas1 extraction.
    # Convert mi² to km² (1 mi² = 2.58999 km²).
    seismic_area_km2 = None
    if hasattr(formation, 'seismic_3d_mi2') and formation.seismic_3d_mi2 is not None:
        seismic_area_km2 = formation.seismic_3d_mi2 * 2.58999

    monitoring_costs = calculate_monitoring_costs(
        schedule=schedule,
        config=region_config.monitoring_config,
        seismic_area_km2=seismic_area_km2,
    )

    # Regulatory
    # Pass corrective action wells for per-formation cost scaling.
    # GOA formations have corrective_action_wells from NETL Res_Bas1.
    n_corrective = getattr(formation, 'corrective_action_wells', None)
    regulatory_costs = calculate_regulatory_costs(
        schedule=schedule,
        config=region_config.regulatory_config,
        corrective_action_wells=n_corrective,
    )

    # Decommissioning
    # Pipeline decom is already included in the pipeline cost module (PIPE-DECOM),
    # so pass pipeline_length_km=0 to avoid double-counting.
    # Platform removal cost: NETL does not have an explicit platform removal line item
    # in the Cost Breakdown 1 sheet (row93 Well Plugging only has NPV in col13).
    # Set platform_removal_cost=0.0 to match NETL cost structure.
    decom_costs = calculate_decommissioning_costs(
        well_plan=well_plan,
        pipeline_length_km=0.0,  # Pipeline decom handled by pipeline module
        water_depth_m=formation.water_depth_m,
        pisc_start_year=_ops_end + 1,
        pisc_end_year=_pisc_end,
        base_year=region_config.base_year,
        currency=region_config.currency,
        platform_removal_cost=0.0,  # NETL has no explicit platform removal in Cost Breakdown 1
    )

    # FR instruments are handled in the cashflow model's financial calculations,
    # NOT as cost catalog items. The NETL Cost Breakdown 1 does not include FR
    # costs -- they appear in the Back-End Financial sheet separately.

    # Additional cost items not covered by individual cost modules
    # (transport vessels, surface equipment, data acquisition, design)
    additional_items: list[CostItem] = []
    additional_costs = costs_config.get("additional_costs", {})
    additional_items.extend(
        _build_additional_cost_items(
            additional_costs,
            region_config.base_year,
            region_config.currency,
            _char_year,
            _constr_begin,
            _ops_begin,
            _ops_end,
            _pisc_end,
        )
    )

    # Assemble cost catalog
    cost_catalog = assemble_cost_catalog(
        pipeline=pipeline_costs,
        drilling=drilling_costs,
        platform=platform_primary,
        monitoring=monitoring_costs,
        decommissioning=decom_costs,
        regulatory=regulatory_costs,
        base_year=region_config.base_year,
        currency=region_config.currency,
        satellite_platform=satellite_platform,
        additional_items=additional_items if additional_items else None,
    )

    # ---------------------------------------------------------------
    # Step 6: Financial model and FYBE solver
    # ---------------------------------------------------------------
    financial_params = FinancialParams.from_region_config(region_config.finance_config)
    tax_regime = region_config.finance_config["tax_regime"]
    escalation = region_config.escalation

    # Revenue streams (Norwegian only)
    revenue_streams = None
    rs_data = region_config.finance_config.get("revenue_streams")
    if rs_data:
        # Apply economic_overrides to revenue stream parameters if specified.
        # ets_price maps to ets_price_eur_per_tonne; co2_tax_rate maps to co2_tax_per_tonne.
        # Setting either to 0 disables that revenue stream, isolating gross storage cost.
        if config.economic_overrides:
            rs_data = dict(rs_data)  # shallow copy to avoid mutating cached config
            if "ets_price" in config.economic_overrides:
                rs_data["ets_price_eur_per_tonne"] = config.economic_overrides["ets_price"]
            if "co2_tax_rate" in config.economic_overrides:
                rs_data["co2_tax_per_tonne"] = config.economic_overrides["co2_tax_rate"]
        revenue_streams = RevenueStreams(**rs_data)

    fybe_result = solve_fybe(
        cost_catalog=cost_catalog,
        schedule=schedule,
        financial_params=financial_params,
        tax_regime=tax_regime,
        escalation=escalation,
        revenue_streams=revenue_streams,
    )

    # ---------------------------------------------------------------
    # Step 7: Package results
    # ---------------------------------------------------------------
    total_capex = cost_catalog.total_capital()
    total_opex = cost_catalog.total_expense()
    cost_breakdown = cost_catalog.by_category()

    # Determine FYBE interpretation based on revenue stream presence.
    # This helps users understand what the FYBE value means: gross storage
    # cost (no revenue) vs net break-even (with ETS/tax credits).
    has_revenue = False
    if revenue_streams is not None:
        ets_val = getattr(revenue_streams, 'ets_price_eur_per_tonne', 0.0) or 0.0
        tax_val = getattr(revenue_streams, 'co2_tax_per_tonne', 0.0) or 0.0
        has_revenue = (ets_val > 0 or tax_val > 0)

    if has_revenue:
        fybe_interpretation = (
            "Net break-even storage fee for a vertically integrated emitter. "
            "Includes EU ETS credits and/or CO2 tax offsets as revenue. "
            "Negative values mean the project is profitable without charging for storage "
            "(emitter's cost savings from ETS/tax credits exceed storage costs). "
            "To see gross storage cost, set economic_overrides={ets_price: 0, co2_tax_rate: 0}."
        )
    else:
        fybe_interpretation = (
            "Gross break-even storage fee (no revenue credits). "
            "This is the minimum fee a storage operator must charge to break even. "
            "Comparable to published storage cost estimates (e.g., Northern Lights EUR 30-60/t)."
        )

    return ScenarioResults(
        fybe=fybe_result.fybe_base_year,
        fybe_current_year=fybe_result.fybe_current_year,
        npv=fybe_result.npv,
        formation_id=formation.id,
        formation_name=formation.name,
        region=config.region,
        co2_density_kgm3=rho_co2_res,
        storage_coefficient=sc,
        plume_area_km2=pa_km2,
        n_injection_wells=n_injection,
        n_monitoring_wells=n_mon,
        pipeline_diameter_inches=dia_result["nominal_diameter_inches"],
        pipeline_length_km=pipeline_length_km,
        total_capex=total_capex,
        total_opex=total_opex,
        cost_breakdown=cost_breakdown,
        total_co2_stored_mt=total_co2_tonnes / 1e6,
        project_duration_years=schedule.total_years,
        currency=region_config.currency,
        base_year=region_config.base_year,
        timestamp=datetime.now(timezone.utc).isoformat(),
        config=config,
        fybe_interpretation=fybe_interpretation,
    )


def evaluate_batch(
    configs: list[ScenarioConfig],
) -> list[ScenarioResults]:
    """Evaluate multiple scenarios.

    Simple loop calling evaluate_scenario for each config.
    Maps to NETL Evaluate_Formations macro.

    Args:
        configs: List of ScenarioConfig objects.

    Returns:
        List of ScenarioResults, one per config.
    """
    return [evaluate_scenario(c) for c in configs]


# ============================================================================
# Internal helpers
# ============================================================================


def _data_root():
    """Get the data directory root."""
    from pathlib import Path

    return Path(__file__).resolve().parent.parent.parent / "data"


def _first_project_year_of_stage(timeline, stage: str) -> int:
    """Get the first project year of a given stage."""
    for entry in timeline:
        if entry.stage == stage:
            return entry.project_year
    return 1


def _last_project_year_of_stage(timeline, stage: str) -> int:
    """Get the last project year of a given stage."""
    last = 1
    for entry in timeline:
        if entry.stage == stage:
            last = entry.project_year
    return last


def _build_additional_cost_items(
    additional_costs: dict,
    base_year: int,
    currency: str,
    char_year: int,
    constr_year: int,
    ops_begin: int,
    ops_end: int,
    pisc_end: int,
) -> list[CostItem]:
    """Build CostItems from the additional_costs section of costs.yaml.

    These cover cost categories that are not modeled by the individual
    cost modules (transport vessels, surface equipment, data acquisition,
    design) but are present in the NETL cost breakdown.

    Args:
        additional_costs: Dict from costs.yaml additional_costs section.
        base_year: Cost base year.
        currency: Currency code.
        char_year: First characterization project year.
        constr_year: First construction project year.
        ops_begin: First operations project year.
        ops_end: Last operations project year.
        pisc_end: Last PISC project year.

    Returns:
        List of CostItems for the additional cost categories.
    """
    items: list[CostItem] = []

    # Map stage names to project years
    stage_year_map = {
        "site_characterization": char_year,
        "permitting_construction": constr_year,
        "operations": ops_begin,
        "pisc": ops_end + 1,
    }

    for name, data in additional_costs.items():
        name_id = name.upper().replace("_", "-")

        # Capital cost
        capex = data.get("capex", 0)
        if capex > 0:
            stage = data.get("stage_capex", "permitting_construction")
            begin = stage_year_map.get(stage, constr_year)
            items.append(CostItem(
                id=f"ADD-{name_id}-CAPEX",
                name=f"{name.replace('_', ' ').title()} (capital)",
                category="additional",
                subcategory=name,
                stage=stage,
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.SITE_CHARACTERIZATION,
                amount_base_year=capex,
                base_year=base_year,
                currency=currency,
                begin_year=begin,
                end_year=begin,
                recurrence="one-time",
            ))

        # O&M during operations
        opex_ops = data.get("opex_annual_ops", 0)
        if opex_ops > 0:
            items.append(CostItem(
                id=f"ADD-{name_id}-OPEX-OPS",
                name=f"{name.replace('_', ' ').title()} O&M (operations)",
                category="additional",
                subcategory=name,
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=opex_ops,
                base_year=base_year,
                currency=currency,
                begin_year=ops_begin,
                end_year=ops_end,
                recurrence="annual",
            ))

        # O&M during PISC
        opex_pisc = data.get("opex_annual_pisc", 0)
        if opex_pisc > 0:
            items.append(CostItem(
                id=f"ADD-{name_id}-OPEX-PISC",
                name=f"{name.replace('_', ' ').title()} O&M (PISC)",
                category="additional",
                subcategory=name,
                stage="pisc",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=opex_pisc,
                base_year=base_year,
                currency=currency,
                begin_year=ops_end + 1,
                end_year=pisc_end,
                recurrence="annual",
            ))

    return items

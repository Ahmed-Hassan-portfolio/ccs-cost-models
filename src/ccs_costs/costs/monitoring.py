"""Monitoring, Verification, and Accounting (MVA) cost framework.

Calculates monitoring costs over the full project lifecycle using
technology-based unit costs loaded from region-specific YAML configs.

Monitoring is the largest single O&M category in the NETL offshore model
($556M / ~46% of total O&M). It spans operations (30 yr) and PISC (50 yr)
with different intensities and technologies.

The monitoring cost module is schedule-driven: it uses ProjectSchedule
to determine when each technology is deployed and for how long. This is
where Norwegian CCS Directive (20yr PISC) vs US EPA (50yr PISC) creates
the largest cost difference.

References:
    NETL CO2_S_COM_Offshore v1.1: Back-End_Cost Items sheet
    EU CCS Directive Art. 17-18: 20-year PISC minimum
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)
from ccs_costs.geo.schedule import ProjectSchedule


# ============================================================================
# Data models
# ============================================================================


class MonitoringUnitCosts(BaseModel):
    """Unit costs for monitoring technologies loaded from YAML config."""

    base_year: int
    currency: str
    technologies: dict  # Raw technology config from YAML


class MonitoringPlan(BaseModel):
    """Which monitoring technologies to deploy and at what frequency."""

    technologies: list[str]
    ops_years: int
    pisc_years: int
    n_injection_wells: int
    n_in_reservoir_wells: int = 12
    n_above_seal_wells: int = 12


class MonitoringCosts(BaseModel):
    """Complete monitoring cost output."""

    total: float
    by_technology: dict[str, float]
    items: list[CostItem]


# ============================================================================
# Configuration loading
# ============================================================================


def _find_regions_dir() -> Path:
    """Find the data/regions directory."""
    # Navigate from this file to project root
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "regions"


def load_monitoring_config(region: str) -> MonitoringUnitCosts:
    """Load monitoring configuration from region-specific YAML.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").

    Returns:
        MonitoringUnitCosts with technology definitions.

    Raises:
        FileNotFoundError: If monitoring.yaml doesn't exist for the region.
    """
    yaml_path = _find_regions_dir() / region / "monitoring.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Monitoring config not found: {yaml_path}"
        )

    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    return MonitoringUnitCosts(
        base_year=config.get("base_year", 2008),
        currency=config.get("currency", "USD"),
        technologies=config.get("monitoring_technologies", {}),
    )


# ============================================================================
# Cost calculation
# ============================================================================


def _classification(value: str) -> CostClassification:
    """Convert string to CostClassification."""
    return CostClassification(value)


def _depreciation(value: str) -> DepreciationCategory:
    """Convert string to DepreciationCategory."""
    return DepreciationCategory(value)


def _count_stage_years(schedule: ProjectSchedule, stage: str) -> int:
    """Count number of years with a given stage in the schedule."""
    return len([y for y in schedule.timeline if y.stage == stage])


def _first_year_of_stage(schedule: ProjectSchedule, stage: str) -> int:
    """Get the first project year of a given stage."""
    for y in schedule.timeline:
        if y.stage == stage:
            return y.project_year
    return 1


def _last_year_of_stage(schedule: ProjectSchedule, stage: str) -> int:
    """Get the last project year of a given stage."""
    last = 1
    for y in schedule.timeline:
        if y.stage == stage:
            last = y.project_year
    return last


def calculate_monitoring_costs(
    schedule: ProjectSchedule,
    config: MonitoringUnitCosts,
    seismic_area_km2: float | None = None,
) -> MonitoringCosts:
    """Calculate monitoring costs over full project lifecycle.

    Walks the ProjectSchedule timeline and applies monitoring technology
    costs based on stage (operations vs PISC) and frequency.

    Area-dependent technologies (3-D seismic, 2-D seismic, microseismic,
    subsea monitoring) are scaled by the ratio of the formation's seismic
    area to the reference area used to calibrate the YAML unit costs.
    When seismic_area_km2 is None, no scaling is applied (costs match the
    reference formation).

    Args:
        schedule: ProjectSchedule with year-by-year timeline.
        config: MonitoringUnitCosts loaded from region YAML.
        seismic_area_km2: Formation-specific 3-D seismic survey area in km².
            Used to scale area-dependent monitoring costs. None = use YAML
            costs as-is (reference formation).

    Returns:
        MonitoringCosts with total, by_technology breakdown, and CostItem list.
    """
    items: list[CostItem] = []
    by_technology: dict[str, float] = {}
    base_year = config.base_year
    currency = config.currency
    techs = config.technologies

    # Area scaling: YAML costs are calibrated to NETL reference formation
    # 1241_1 with seismic_3d_mi2 = 254.67 mi² = 659.67 km².
    # Area-dependent technologies scale linearly with seismic area.
    REFERENCE_SEISMIC_AREA_KM2 = 659.67
    if seismic_area_km2 is not None and seismic_area_km2 > 0:
        area_ratio = seismic_area_km2 / REFERENCE_SEISMIC_AREA_KM2
    else:
        area_ratio = 1.0

    ops_years = _count_stage_years(schedule, "operations")
    pisc_years = _count_stage_years(schedule, "pisc")
    ops_start = _first_year_of_stage(schedule, "operations")
    ops_end = _last_year_of_stage(schedule, "operations")
    pisc_start = _first_year_of_stage(schedule, "pisc")
    pisc_end = _last_year_of_stage(schedule, "pisc")
    char_start = _first_year_of_stage(schedule, "characterization")
    char_end = _last_year_of_stage(schedule, "characterization")

    # Determine well counts from schedule
    n_injection = schedule.well_plan.n_injection
    # In-reservoir and above-seal are split from total monitoring wells
    # NETL default: half in-reservoir, half above-seal
    n_monitoring = schedule.well_plan.n_monitoring
    n_in_res = n_monitoring // 2
    n_above_seal = n_monitoring - n_in_res

    # ---------------------------------------------------------------
    # Subsea monitoring (area-dependent: scales with seismic area)
    # ---------------------------------------------------------------
    if "subsea_monitoring" in techs:
        sm = techs["subsea_monitoring"]
        tech_total = 0.0

        # Characterization baseline surveys
        char_cost = sm.get("characterization_cost", 0.0) * area_ratio
        if char_cost > 0:
            items.append(CostItem(
                id="MON-SUBSEA-CHAR",
                name="Subsea monitoring - characterization baseline",
                category="monitoring",
                subcategory="subsea_monitoring",
                stage="characterization",
                classification=_classification(sm.get("classification_capital", "capital")),
                depreciation_category=_depreciation(sm.get("depreciation", "site_characterization")),
                amount_base_year=char_cost,
                base_year=base_year,
                currency=currency,
                begin_year=char_start,
                end_year=char_start,
                recurrence="one-time",
            ))
            tech_total += char_cost

        # Construction capital (classified per YAML config; NETL: expense)
        constr_cost = sm.get("construction_capital", 0.0) * area_ratio
        if constr_cost > 0:
            # Place construction cost just before ops start
            constr_year = ops_start - 1 if ops_start > 1 else ops_start
            items.append(CostItem(
                id="MON-SUBSEA-CONSTR",
                name="Subsea monitoring - construction equipment",
                category="monitoring",
                subcategory="subsea_monitoring",
                stage="permitting_construction",
                classification=_classification(sm.get("classification_capital", "expense")),
                depreciation_category=_depreciation(sm.get("depreciation", "none")),
                amount_base_year=constr_cost,
                base_year=base_year,
                currency=currency,
                begin_year=constr_year,
                end_year=constr_year,
                recurrence="one-time",
            ))
            tech_total += constr_cost

        # Annual operations O&M
        annual_ops = sm.get("annual_ops_cost", 0.0) * area_ratio
        if annual_ops > 0 and ops_years > 0:
            items.append(CostItem(
                id="MON-SUBSEA-OPS",
                name="Subsea monitoring - operations campaigns",
                category="monitoring",
                subcategory="subsea_monitoring",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual_ops,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            tech_total += annual_ops * ops_years

        # Annual PISC O&M
        annual_pisc = sm.get("annual_pisc_cost", 0.0) * area_ratio
        if annual_pisc > 0 and pisc_years > 0:
            items.append(CostItem(
                id="MON-SUBSEA-PISC",
                name="Subsea monitoring - PISC campaigns",
                category="monitoring",
                subcategory="subsea_monitoring",
                stage="pisc",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual_pisc,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="annual",
            ))
            tech_total += annual_pisc * pisc_years

        by_technology["subsea_monitoring"] = tech_total

    # ---------------------------------------------------------------
    # 3-D Seismic (area-dependent: scales with seismic area)
    # ---------------------------------------------------------------
    if "seismic_3d" in techs:
        s3d = techs["seismic_3d"]
        tech_total = 0.0
        freq = s3d.get("frequency_years", 5)

        # Operations surveys
        ops_cost_per_event = s3d.get("ops_cost_per_event", 0.0) * area_ratio
        if ops_cost_per_event > 0 and ops_years > 0:
            n_ops_events = ops_years // freq
            items.append(CostItem(
                id="MON-SEIS3D-OPS",
                name="3-D Seismic surveys - operations",
                category="monitoring",
                subcategory="seismic_3d",
                stage="operations",
                classification=_classification(s3d.get("classification", "capital")),
                depreciation_category=_depreciation(s3d.get("depreciation", "seismic")),
                amount_base_year=ops_cost_per_event,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="periodic",
                recurrence_years=freq,
            ))
            tech_total += ops_cost_per_event * n_ops_events

        # PISC surveys
        pisc_cost_per_event = s3d.get("pisc_cost_per_event", 0.0) * area_ratio
        if pisc_cost_per_event > 0 and pisc_years > 0:
            n_pisc_events = pisc_years // freq
            items.append(CostItem(
                id="MON-SEIS3D-PISC",
                name="3-D Seismic surveys - PISC",
                category="monitoring",
                subcategory="seismic_3d",
                stage="pisc",
                classification=_classification(s3d.get("classification", "capital")),
                depreciation_category=_depreciation(s3d.get("depreciation", "seismic")),
                amount_base_year=pisc_cost_per_event,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="periodic",
                recurrence_years=freq,
            ))
            tech_total += pisc_cost_per_event * n_pisc_events

        by_technology["seismic_3d"] = tech_total

    # ---------------------------------------------------------------
    # 2-D Seismic (area-dependent: scales with seismic area)
    # ---------------------------------------------------------------
    if "seismic_2d" in techs:
        s2d = techs["seismic_2d"]
        tech_total = 0.0
        freq = s2d.get("frequency_years", 5)

        ops_cost = s2d.get("ops_cost_per_event", 0.0) * area_ratio
        if ops_cost > 0 and ops_years > 0:
            n_ops = ops_years // freq
            items.append(CostItem(
                id="MON-SEIS2D-OPS",
                name="2-D Seismic surveys - operations",
                category="monitoring",
                subcategory="seismic_2d",
                stage="operations",
                classification=_classification(s2d.get("classification", "capital")),
                depreciation_category=_depreciation(s2d.get("depreciation", "seismic")),
                amount_base_year=ops_cost,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="periodic",
                recurrence_years=freq,
            ))
            tech_total += ops_cost * n_ops

        pisc_cost = s2d.get("pisc_cost_per_event", 0.0) * area_ratio
        if pisc_cost > 0 and pisc_years > 0:
            n_pisc = pisc_years // freq
            items.append(CostItem(
                id="MON-SEIS2D-PISC",
                name="2-D Seismic surveys - PISC",
                category="monitoring",
                subcategory="seismic_2d",
                stage="pisc",
                classification=_classification(s2d.get("classification", "capital")),
                depreciation_category=_depreciation(s2d.get("depreciation", "seismic")),
                amount_base_year=pisc_cost,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="periodic",
                recurrence_years=freq,
            ))
            tech_total += pisc_cost * n_pisc

        by_technology["seismic_2d"] = tech_total

    # ---------------------------------------------------------------
    # Microseismic (area-dependent: scales with seismic area)
    # ---------------------------------------------------------------
    if "microseismic" in techs:
        ms = techs["microseismic"]
        tech_total = 0.0

        # Equipment capital (one-time during construction)
        equip_cost = ms.get("equipment_capital", 0.0) * area_ratio
        if equip_cost > 0:
            constr_year = ops_start - 1 if ops_start > 1 else ops_start
            items.append(CostItem(
                id="MON-MICRO-EQUIP",
                name="Microseismic monitoring equipment",
                category="monitoring",
                subcategory="microseismic",
                stage="permitting_construction",
                classification=_classification(ms.get("classification_equipment", "capital")),
                depreciation_category=_depreciation(ms.get("depreciation", "site_characterization")),
                amount_base_year=equip_cost,
                base_year=base_year,
                currency=currency,
                begin_year=constr_year,
                end_year=constr_year,
                recurrence="one-time",
            ))
            tech_total += equip_cost

        # Annual operations cost
        annual_ops = ms.get("annual_ops_cost", 0.0) * area_ratio
        if annual_ops > 0 and ops_years > 0:
            items.append(CostItem(
                id="MON-MICRO-OPS",
                name="Microseismic monitoring - operations",
                category="monitoring",
                subcategory="microseismic",
                stage="operations",
                classification=_classification(ms.get("classification_operations", "expense")),
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual_ops,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            tech_total += annual_ops * ops_years

        # Annual PISC cost
        annual_pisc = ms.get("annual_pisc_cost", 0.0) * area_ratio
        if annual_pisc > 0 and pisc_years > 0:
            items.append(CostItem(
                id="MON-MICRO-PISC",
                name="Microseismic monitoring - PISC",
                category="monitoring",
                subcategory="microseismic",
                stage="pisc",
                classification=_classification(ms.get("classification_operations", "expense")),
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual_pisc,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="annual",
            ))
            tech_total += annual_pisc * pisc_years

        by_technology["microseismic"] = tech_total

    # ---------------------------------------------------------------
    # Well integrity testing (injection wells, operations only)
    # ---------------------------------------------------------------
    if "well_integrity_test" in techs:
        wit = techs["well_integrity_test"]
        cost_per_well = wit.get("cost_per_well_per_year", 0.0)
        if cost_per_well > 0 and ops_years > 0:
            total_annual = cost_per_well * n_injection
            items.append(CostItem(
                id="MON-WIT-INJECT",
                name="Well integrity testing - injection wells",
                category="monitoring",
                subcategory="well_integrity_test",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=total_annual,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            by_technology["well_integrity_test"] = total_annual * ops_years

    # ---------------------------------------------------------------
    # Well MIT (injection wells, operations only)
    # ---------------------------------------------------------------
    if "well_mit_inject" in techs:
        wmi = techs["well_mit_inject"]
        cost_per_well = wmi.get("cost_per_well_per_year", 0.0)
        if cost_per_well > 0 and ops_years > 0:
            total_annual = cost_per_well * n_injection
            items.append(CostItem(
                id="MON-MIT-INJECT",
                name="Well MIT - injection wells",
                category="monitoring",
                subcategory="well_mit_inject",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=total_annual,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            by_technology["well_mit_inject"] = total_annual * ops_years

    # ---------------------------------------------------------------
    # Well O&M (injection wells, operations only)
    # ---------------------------------------------------------------
    if "well_om_inject" in techs:
        woi = techs["well_om_inject"]
        cost_per_well = woi.get("cost_per_well_per_year", 0.0)
        if cost_per_well > 0 and ops_years > 0:
            total_annual = cost_per_well * n_injection
            items.append(CostItem(
                id="MON-OM-INJECT",
                name="Well O&M - injection wells",
                category="monitoring",
                subcategory="well_om_inject",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=total_annual,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            by_technology["well_om_inject"] = total_annual * ops_years

    # ---------------------------------------------------------------
    # Well O&M (in-reservoir monitoring wells, ops + PISC)
    # ---------------------------------------------------------------
    if "well_om_in_res" in techs:
        woir = techs["well_om_in_res"]
        tech_total = 0.0
        n_wells = woir.get("n_wells_default", n_in_res)

        # Operations
        ops_cost = woir.get("ops_cost_per_well_per_year", 0.0)
        if ops_cost > 0 and ops_years > 0:
            total_annual_ops = ops_cost * n_wells
            items.append(CostItem(
                id="MON-OM-INRES-OPS",
                name="Well O&M - in-reservoir monitoring (ops)",
                category="monitoring",
                subcategory="well_om_in_res",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=total_annual_ops,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            tech_total += total_annual_ops * ops_years

        # PISC
        pisc_cost = woir.get("pisc_cost_per_well_per_year", 0.0)
        if pisc_cost > 0 and pisc_years > 0:
            total_annual_pisc = pisc_cost * n_wells
            items.append(CostItem(
                id="MON-OM-INRES-PISC",
                name="Well O&M - in-reservoir monitoring (PISC)",
                category="monitoring",
                subcategory="well_om_in_res",
                stage="pisc",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=total_annual_pisc,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="annual",
            ))
            tech_total += total_annual_pisc * pisc_years

        by_technology["well_om_in_res"] = tech_total

    # ---------------------------------------------------------------
    # Sampling & Analysis - In Reservoir
    # ---------------------------------------------------------------
    if "sampling_analysis_in_res" in techs:
        sair = techs["sampling_analysis_in_res"]
        tech_total = 0.0

        ops_annual = sair.get("ops_annual", 0.0)
        if ops_annual > 0 and ops_years > 0:
            items.append(CostItem(
                id="MON-SAMP-INRES-OPS",
                name="Sampling & analysis - in-reservoir (ops)",
                category="monitoring",
                subcategory="sampling_in_res",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=ops_annual,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            tech_total += ops_annual * ops_years

        pisc_annual = sair.get("pisc_annual", 0.0)
        if pisc_annual > 0 and pisc_years > 0:
            items.append(CostItem(
                id="MON-SAMP-INRES-PISC",
                name="Sampling & analysis - in-reservoir (PISC)",
                category="monitoring",
                subcategory="sampling_in_res",
                stage="pisc",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=pisc_annual,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="annual",
            ))
            tech_total += pisc_annual * pisc_years

        by_technology["sampling_in_res"] = tech_total

    # ---------------------------------------------------------------
    # Sampling & Analysis - Above Seal
    # ---------------------------------------------------------------
    if "sampling_analysis_ab_seal" in techs:
        saas = techs["sampling_analysis_ab_seal"]
        tech_total = 0.0

        ops_annual = saas.get("ops_annual", 0.0)
        if ops_annual > 0 and ops_years > 0:
            items.append(CostItem(
                id="MON-SAMP-ABSEAL-OPS",
                name="Sampling & analysis - above seal (ops)",
                category="monitoring",
                subcategory="sampling_ab_seal",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=ops_annual,
                base_year=base_year,
                currency=currency,
                begin_year=ops_start,
                end_year=ops_end,
                recurrence="annual",
            ))
            tech_total += ops_annual * ops_years

        pisc_annual = saas.get("pisc_annual", 0.0)
        if pisc_annual > 0 and pisc_years > 0:
            items.append(CostItem(
                id="MON-SAMP-ABSEAL-PISC",
                name="Sampling & analysis - above seal (PISC)",
                category="monitoring",
                subcategory="sampling_ab_seal",
                stage="pisc",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=pisc_annual,
                base_year=base_year,
                currency=currency,
                begin_year=pisc_start,
                end_year=pisc_end,
                recurrence="annual",
            ))
            tech_total += pisc_annual * pisc_years

        by_technology["sampling_ab_seal"] = tech_total

    # ---------------------------------------------------------------
    # Gravity survey (one-time capital)
    # ---------------------------------------------------------------
    if "gravity_survey" in techs:
        gs = techs["gravity_survey"]
        cost = gs.get("cost", 0.0)
        if cost > 0:
            timing = gs.get("timing", "characterization")
            if timing == "characterization":
                grav_year = char_start
                grav_stage = "characterization"
            else:
                grav_year = ops_start - 1 if ops_start > 1 else ops_start
                grav_stage = "permitting_construction"

            items.append(CostItem(
                id="MON-GRAVITY",
                name="Gravity survey",
                category="monitoring",
                subcategory="gravity_survey",
                stage=grav_stage,
                classification=_classification(gs.get("classification", "capital")),
                depreciation_category=_depreciation(gs.get("depreciation", "site_characterization")),
                amount_base_year=cost,
                base_year=base_year,
                currency=currency,
                begin_year=grav_year,
                end_year=grav_year,
                recurrence="one-time",
            ))
            by_technology["gravity_survey"] = cost

    # ---------------------------------------------------------------
    # Compute total
    # ---------------------------------------------------------------
    total = sum(by_technology.values())

    return MonitoringCosts(
        total=total,
        by_technology=by_technology,
        items=items,
    )

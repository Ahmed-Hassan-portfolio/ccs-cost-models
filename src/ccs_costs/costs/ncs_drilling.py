"""NCS Activity-Based Drilling Cost Model (v2).

Bottom-up well construction time and cost estimation calibrated to the
Norwegian Continental Shelf. Computes time from activity-level data, then
converts to cost via day rates.

v2: Split section overhead into FLAT (depth-independent) and DEPTH-DEPENDENT
components. Flat time covers procedures that take the same time regardless
of well depth (BHA makeup, testing, cementing pump time). Depth-dependent
time covers activities that scale with casing shoe depth (casing running,
tripping). Derived empirically from SBBU Base Case vs Case-1 comparison
at two different section depths.

Sources:
    SBBU NTNU-IPT 2013/01 (Sangesland et al.) — activity hours, flat/depth split
    Khosravanian & Aadnoy 2021 — PERT distributions, completion time share
    Sodir FactPages 2025 — 920 NCS injection wells, percentile calibration
    IEAGHG 2018-08 — CRA material multipliers, CO2 cement premium

Algorithm:
    section_time = flat_hrs × co2_factor + depth_rate × shoe_depth_km
                   + section_length / ROP(hole_size)
    total_time = Σ(section_time) + BOP_time + completion + NPT
    total_cost = total_time × (rig_rate + service_rate) + material_adders
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


# ============================================================================
# Data models
# ============================================================================


class WellSection(BaseModel):
    """A single hole/casing section of a well."""

    name: str
    hole_size_in: float
    casing_size_in: float
    top_md_m: float
    shoe_md_m: float

    @property
    def length_m(self) -> float:
        return self.shoe_md_m - self.top_md_m


class NCSWellDesign(BaseModel):
    """Well design input for the NCS activity model."""

    sections: list[WellSection]
    water_depth_m: float
    air_gap_m: float = 25.0
    target_tvd_m: float
    cra_grade: str = "25Cr_super_duplex"
    cra_coverage: str = "conservative"  # "conservative" | "moderate" | "full"

    @property
    def rkb_offset_m(self) -> float:
        return self.water_depth_m + self.air_gap_m


class SectionTimeBreakdown(BaseModel):
    """Time breakdown for a single well section."""

    name: str
    hole_size_in: float
    length_m: float
    shoe_depth_m: float
    drilling_hours: float
    flat_overhead_hours: float
    depth_overhead_hours: float
    total_overhead_hours: float
    total_hours: float
    rop_mhr: float


class WellTimeResult(BaseModel):
    """Complete well construction time breakdown."""

    sections: list[SectionTimeBreakdown]
    drilling_hours: float
    overhead_hours: float
    bop_hours: float
    completion_hours: float
    planned_hours: float
    npt_hours: float
    total_hours: float
    total_days: float
    npt_scenario: str

    by_category: dict[str, float] = Field(default_factory=dict)


class MaterialCostBreakdown(BaseModel):
    """Bottom-up material cost from well design."""

    casing_cost: float = 0.0
    casing_cost_by_section: dict[str, float] = Field(default_factory=dict)
    cement_cost: float = 0.0
    total_material: float = 0.0


class WellCostResult(BaseModel):
    """Complete well cost breakdown."""

    time: WellTimeResult
    # Time-dependent costs
    rig_cost: float
    service_cost: float
    spread_cost: float
    # Material costs (bottom-up)
    materials: MaterialCostBreakdown = Field(
        default_factory=MaterialCostBreakdown
    )
    # Fixed costs
    subsea_system: float = 0.0
    completion_equipment: float = 0.0
    mob_demob_per_well: float = 0.0
    total_fixed: float = 0.0
    # Contingency
    contingency: float = 0.0
    contingency_rate: float = 0.15
    # Totals
    subtotal: float = 0.0
    total_cost: float = 0.0
    currency: str
    cost_per_day: float
    batch_discount: float = 0.0


class SodirCalibration(BaseModel):
    """Sodir percentile band for a TVD range."""

    tvd_range: str
    n_wells: int
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float


# ============================================================================
# Model configuration loader
# ============================================================================


def _default_config_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data"
        / "reference"
        / "ncs_drilling_model.yaml"
    )


def load_model_config(path: Path | None = None) -> dict:
    """Load the NCS drilling model calibration YAML."""
    if path is None:
        path = _default_config_path()
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================================
# Core time calculation
# ============================================================================


def _rop_for_hole_size(
    hole_size_in: float,
    reference_rop_mhr: float,
    rop_ratios: dict[float, float],
) -> float:
    """Compute ROP for a given hole size using ratio factors.

    If exact hole size not in table, interpolate between nearest sizes.
    """
    sizes = sorted(rop_ratios.keys())

    # Exact match
    if hole_size_in in rop_ratios:
        return reference_rop_mhr * rop_ratios[hole_size_in]

    # Clamp to range
    if hole_size_in >= sizes[-1]:
        return reference_rop_mhr * rop_ratios[sizes[-1]]
    if hole_size_in <= sizes[0]:
        return reference_rop_mhr * rop_ratios[sizes[0]]

    # Linear interpolation
    for i in range(len(sizes) - 1):
        if sizes[i] <= hole_size_in <= sizes[i + 1]:
            lo, hi = sizes[i], sizes[i + 1]
            frac = (hole_size_in - lo) / (hi - lo)
            ratio = rop_ratios[lo] + frac * (rop_ratios[hi] - rop_ratios[lo])
            return reference_rop_mhr * ratio

    return reference_rop_mhr  # fallback


def _section_overhead(
    hole_size_in: float,
    shoe_depth_m: float,
    activities: dict,
    co2_flat_factor: float,
) -> tuple[float, float]:
    """Compute section overhead split into flat + depth-dependent hours.

    Args:
        hole_size_in: Hole size to look up.
        shoe_depth_m: Casing shoe depth from RKB (m).
        activities: section_activities config dict keyed by hole size.
        co2_flat_factor: Reduction factor for flat time (CO2 well simplification).

    Returns:
        Tuple of (flat_hours, depth_hours).
    """
    # YAML may parse keys as float or str — normalize to float lookup
    act_by_float = {float(k): v for k, v in activities.items()}

    if hole_size_in in act_by_float:
        entry = act_by_float[hole_size_in]
    else:
        nearest = min(act_by_float.keys(), key=lambda s: abs(s - hole_size_in))
        entry = act_by_float[nearest]
    flat = float(entry["flat_hrs"]) * co2_flat_factor
    rate = float(entry["depth_rate_hr_per_km"])
    depth = rate * (shoe_depth_m / 1000.0)
    return flat, depth


def _bop_time(
    water_depth_m: float,
    config: dict,
) -> float:
    """Calculate BOP run + pull time (hours) for given water depth."""
    bop = config["bop"]
    ref_wd = bop["reference_water_depth_m"]
    base_total = bop["run_hours"] + bop["pull_hours"]
    scaling = bop["scaling_hrs_per_100m"]

    delta_wd = water_depth_m - ref_wd
    return base_total + (delta_wd / 100.0) * scaling


def calculate_well_time(
    design: NCSWellDesign,
    config: dict | None = None,
    reference_rop_mhr: float | None = None,
    npt_scenario: Literal["optimistic", "base", "conservative"] = "base",
    include_completion: bool = True,
) -> WellTimeResult:
    """Calculate total well construction time from activity-level model.

    Args:
        design: Well design with sections, water depth, TVD.
        config: Model config dict. Loaded from YAML if None.
        reference_rop_mhr: Override default 8.5" ROP (m/hr).
        npt_scenario: NPT factor scenario.
        include_completion: Whether to include completion time.

    Returns:
        WellTimeResult with full time breakdown.
    """
    if config is None:
        config = load_model_config()

    rop_ratios = {float(k): float(v) for k, v in config["rop_ratio_factors"].items()}
    activities = config["section_activities"]
    ref_rop = reference_rop_mhr or config["reference_rop_mhr"]
    npt_factor = config["npt_factors"][npt_scenario]
    co2_flat_factor = config.get("co2_flat_factor", 1.0)

    # Per-section time
    section_results: list[SectionTimeBreakdown] = []
    total_drilling = 0.0
    total_flat_oh = 0.0
    total_depth_oh = 0.0

    for section in design.sections:
        rop = _rop_for_hole_size(section.hole_size_in, ref_rop, rop_ratios)
        drill_hrs = section.length_m / rop if rop > 0 else 0.0

        flat_oh, depth_oh = _section_overhead(
            section.hole_size_in,
            section.shoe_md_m,
            activities,
            co2_flat_factor,
        )
        oh_total = flat_oh + depth_oh

        section_results.append(
            SectionTimeBreakdown(
                name=section.name,
                hole_size_in=section.hole_size_in,
                length_m=section.length_m,
                shoe_depth_m=section.shoe_md_m,
                drilling_hours=drill_hrs,
                flat_overhead_hours=flat_oh,
                depth_overhead_hours=depth_oh,
                total_overhead_hours=oh_total,
                total_hours=drill_hrs + oh_total,
                rop_mhr=rop,
            )
        )
        total_drilling += drill_hrs
        total_flat_oh += flat_oh
        total_depth_oh += depth_oh

    total_overhead = total_flat_oh + total_depth_oh

    # BOP time
    bop_hrs = _bop_time(design.water_depth_m, config)

    # Completion time: flat + depth-dependent (tubing RIH scales with depth)
    comp_cfg = config["completion"]
    if include_completion:
        completion_hrs = comp_cfg["flat_hours"] + comp_cfg["depth_rate_hr_per_km"] * (design.target_tvd_m / 1000.0)
    else:
        completion_hrs = 0.0

    # Planned (technical) time
    planned = total_drilling + total_overhead + bop_hrs + completion_hrs

    # NPT
    npt_hrs = planned * npt_factor

    # Total
    total_hrs = planned + npt_hrs
    total_days = total_hrs / 24.0

    # Category breakdown
    by_category = {
        "drilling": total_drilling,
        "flat_overhead": total_flat_oh,
        "depth_overhead": total_depth_oh,
        "bop": bop_hrs,
        "completion": completion_hrs,
        "npt": npt_hrs,
    }

    return WellTimeResult(
        sections=section_results,
        drilling_hours=total_drilling,
        overhead_hours=total_overhead,
        bop_hours=bop_hrs,
        completion_hours=completion_hrs,
        planned_hours=planned,
        npt_hours=npt_hrs,
        total_hours=total_hrs,
        total_days=total_days,
        npt_scenario=npt_scenario,
        by_category=by_category,
    )


# ============================================================================
# Material cost calculation (bottom-up from well design)
# ============================================================================

_PPF_TO_KGM = 1.4882  # lb/ft to kg/m conversion


def _calculate_material_costs(
    design: NCSWellDesign,
    config: dict,
    currency: Literal["nok", "usd"] = "nok",
) -> MaterialCostBreakdown:
    """Calculate bottom-up material costs from well design.

    Computes casing steel cost per section using actual weights, grades,
    and CRA multipliers. Cement cost from annular volumes.
    """
    mat = config["materials"]
    base_price = mat["octg_base_usd_per_tonne"]
    norway_prem = mat["norway_premium"]
    grade_factors = {str(k): float(v) for k, v in mat["grade_factors"].items()}
    cra_mults = {str(k): float(v) for k, v in mat["cra_multipliers"].items()}
    weights = {float(k): float(v) for k, v in mat["casing_weights_ppf"].items()}

    # NOK conversion (approximate)
    usd_to_nok = 10.5 if currency == "nok" else 1.0

    casing_by_section: dict[str, float] = {}
    total_casing = 0.0

    for section in design.sections:
        # Look up weight per foot
        nearest_size = min(weights.keys(), key=lambda s: abs(s - section.casing_size_in))
        weight_ppf = weights[nearest_size]
        weight_kgm = weight_ppf * _PPF_TO_KGM

        # Determine grade factor based on CRA coverage design choice
        # CRA coverage options (from YAML):
        #   conservative: production + liner only (NL practice)
        #   moderate/full: intermediate + production + liner (Endurance practice)
        cra_cfg = mat.get("cra_coverage", {})
        coverage_key = design.cra_coverage or cra_cfg.get("default", "conservative")
        cra_sections = cra_cfg.get(coverage_key, ["production", "liner"])

        if section.name in cra_sections:
            mult = cra_mults.get(design.cra_grade, 5.5)
        else:
            if section.name == "conductor":
                mult = grade_factors.get("X56", 0.90)
            elif section.name == "surface":
                mult = grade_factors.get("K55", 0.90)
            elif section.name == "intermediate":
                mult = grade_factors.get("P110", 1.15)
            else:
                mult = 1.0

        # Cost = length × weight_kg/m × price_per_tonne × multiplier × norway_premium
        price_per_tonne = base_price * mult * norway_prem
        weight_tonnes = weight_kgm * section.length_m / 1000.0
        section_cost = weight_tonnes * price_per_tonne * usd_to_nok

        casing_by_section[section.name] = section_cost
        total_casing += section_cost

    # Cement cost
    cement_base = mat["cement_usd_per_m3"]
    co2_prem = mat["co2_cement_premium"]
    excess = mat["cement_excess_factor"]
    total_cement = 0.0
    for section in design.sections:
        hole_d = section.hole_size_in * 0.0254
        casing_d = section.casing_size_in * 0.0254
        annular_vol = math.pi / 4 * (hole_d**2 - casing_d**2) * section.length_m * excess
        # CO2-resistant cement for production section, standard for others
        is_production = section.name in ("production", "liner")
        price = cement_base * (1 + co2_prem) if is_production else cement_base
        total_cement += annular_vol * price * usd_to_nok

    total_material = total_casing + total_cement

    return MaterialCostBreakdown(
        casing_cost=total_casing,
        casing_cost_by_section=casing_by_section,
        cement_cost=total_cement,
        total_material=total_material,
    )


# ============================================================================
# Cost calculation
# ============================================================================


def calculate_well_cost(
    design: NCSWellDesign,
    config: dict | None = None,
    reference_rop_mhr: float | None = None,
    npt_scenario: Literal["optimistic", "base", "conservative"] = "base",
    currency: Literal["nok", "usd"] = "nok",
    rig_rate: float | None = None,
    service_rate: float | None = None,
    campaign_wells: int = 1,
    well_index: int = 1,
    include_subsea_system: bool = False,
) -> WellCostResult:
    """Calculate total well cost: spread + materials + fixed + contingency.

    Args:
        design: Well design specification.
        config: Model config. Loaded from YAML if None.
        reference_rop_mhr: Override default ROP.
        npt_scenario: NPT scenario.
        currency: "nok" or "usd".
        rig_rate: Override rig day rate.
        service_rate: Override service day rate.
        campaign_wells: Total wells in drilling campaign.
        well_index: Which well in the campaign (1-based).
        include_subsea_system: Whether to include subsea tree/wellhead/controls.

    Returns:
        WellCostResult with full cost breakdown.
    """
    if config is None:
        config = load_model_config()

    time_result = calculate_well_time(
        design, config, reference_rop_mhr, npt_scenario
    )

    # --- Time-dependent costs (spread) ---
    rates = config["day_rates"][currency]
    r_rig = rig_rate if rig_rate is not None else rates["rig"]
    r_svc = service_rate if service_rate is not None else rates["services"]
    cost_per_day = r_rig + r_svc

    batch_cfg = config["batch_drilling"]
    batch_discount_days = 0.0
    if campaign_wells >= batch_cfg["min_wells_for_batch"] and well_index > 1:
        batch_discount_days = batch_cfg["savings_days_per_well"]

    effective_days = max(0.0, time_result.total_days - batch_discount_days)
    rig_cost = effective_days * r_rig
    svc_cost = effective_days * r_svc
    spread_cost = rig_cost + svc_cost

    # --- Material costs (bottom-up) ---
    materials = _calculate_material_costs(design, config, currency)

    # --- Fixed costs ---
    fixed = config["fixed_costs"][currency]
    if include_subsea_system:
        subsea = fixed["subsea_system_first"] if well_index == 1 else fixed["subsea_system_repeat"]
    else:
        subsea = 0.0
    completion_equip = fixed["completion_equipment"]
    mob_demob = fixed["mob_demob_campaign"] / max(1, campaign_wells)
    total_fixed = subsea + completion_equip + mob_demob

    # --- Contingency (cost-only, NOT time) ---
    cont_cfg = config.get("contingency", {})
    cont_rate = cont_cfg.get("rate", 0.15)
    subtotal = spread_cost + materials.total_material + total_fixed
    contingency = subtotal * cont_rate

    total_cost = subtotal + contingency

    return WellCostResult(
        time=time_result,
        rig_cost=rig_cost,
        service_cost=svc_cost,
        spread_cost=spread_cost,
        materials=materials,
        subsea_system=subsea,
        completion_equipment=completion_equip,
        mob_demob_per_well=mob_demob,
        total_fixed=total_fixed,
        contingency=contingency,
        contingency_rate=cont_rate,
        subtotal=subtotal,
        total_cost=total_cost,
        currency=currency.upper(),
        cost_per_day=cost_per_day,
        batch_discount=batch_discount_days,
    )


# ============================================================================
# Convenience: default well design from depth + water depth
# ============================================================================


def default_well_design(
    target_tvd_m: float,
    water_depth_m: float,
    air_gap_m: float = 25.0,
    cra_grade: str = "25Cr_super_duplex",
    config: dict | None = None,
) -> NCSWellDesign:
    """Create a default NCS CO2 well design from TVD and water depth.

    Selects casing program (shallow/moderate/deep) based on TVD,
    computes section depths from mudline.

    Args:
        target_tvd_m: Target vertical depth (m).
        water_depth_m: Water depth (m).
        air_gap_m: Air gap above sea level (m).
        cra_grade: CRA grade for production casing.
        config: Model config dict.

    Returns:
        NCSWellDesign ready for time/cost calculation.
    """
    if config is None:
        config = load_model_config()

    rkb = water_depth_m + air_gap_m
    total_md = target_tvd_m + rkb  # Vertical well: MD = TVD + RKB offset
    # Note: for simplicity this is TVD from sea level. The sections
    # reference MD from RKB.

    # Select casing program
    programs = config["default_casing_programs"]
    if target_tvd_m <= 1200:
        prog = programs["shallow"]
    elif target_tvd_m <= 2200:
        prog = programs["moderate"]
    else:
        prog = programs["deep"]

    sections: list[WellSection] = []
    prev_shoe = 0.0  # MD from RKB

    for i, s in enumerate(prog["sections"]):
        # Conductor top is at mudline (RKB offset), not at 0.
        # Drilling starts at mudline — the water column is traversed
        # by the riser/BOP, handled separately in BOP time.
        if i == 0:
            top_md = float(rkb)
        else:
            top_md = prev_shoe

        if s.get("shoe_at_td"):
            shoe_md = float(total_md)
        elif "shoe_below_mudline_m" in s:
            shoe_md = float(rkb + s["shoe_below_mudline_m"])
        elif "shoe_fraction_of_td" in s:
            shoe_md = float(rkb + target_tvd_m * s["shoe_fraction_of_td"])
        else:
            shoe_md = float(total_md)

        sections.append(
            WellSection(
                name=s["name"],
                hole_size_in=s["hole_in"],
                casing_size_in=s["casing_in"],
                top_md_m=top_md,
                shoe_md_m=shoe_md,
            )
        )
        prev_shoe = shoe_md

    return NCSWellDesign(
        sections=sections,
        water_depth_m=water_depth_m,
        air_gap_m=air_gap_m,
        target_tvd_m=target_tvd_m,
        cra_grade=cra_grade,
    )


# ============================================================================
# Sodir calibration check
# ============================================================================


def sodir_check(
    total_days: float,
    target_tvd_m: float,
    config: dict | None = None,
) -> SodirCalibration | None:
    """Check well time against Sodir percentile bands.

    Returns the matching Sodir band with the well's position, or None
    if TVD is outside calibration range.
    """
    if config is None:
        config = load_model_config()

    cal = config["sodir_calibration"]

    if target_tvd_m < 1000:
        return None

    if target_tvd_m <= 2000:
        band = cal["tvd_1000_2000"]
        tvd_range = "1000-2000m"
    elif target_tvd_m <= 3000:
        band = cal["tvd_2000_3000"]
        tvd_range = "2000-3000m"
    elif target_tvd_m <= 4000:
        band = cal["tvd_3000_4000"]
        tvd_range = "3000-4000m"
    else:
        return None

    return SodirCalibration(
        tvd_range=tvd_range,
        n_wells=band["n"],
        p10=band["p10"],
        p25=band["p25"],
        p50=band["p50"],
        p75=band["p75"],
        p90=band["p90"],
    )


# ============================================================================
# Campaign cost (multiple wells)
# ============================================================================


def calculate_campaign_cost(
    n_wells: int,
    target_tvd_m: float,
    water_depth_m: float,
    config: dict | None = None,
    reference_rop_mhr: float | None = None,
    npt_scenario: Literal["optimistic", "base", "conservative"] = "base",
    currency: Literal["nok", "usd"] = "nok",
    cra_grade: str = "25Cr_super_duplex",
) -> list[WellCostResult]:
    """Calculate costs for a multi-well drilling campaign.

    Applies batch drilling savings to wells 2..N.

    Returns:
        List of WellCostResult, one per well.
    """
    if config is None:
        config = load_model_config()

    design = default_well_design(
        target_tvd_m, water_depth_m, cra_grade=cra_grade, config=config
    )

    results = []
    for i in range(1, n_wells + 1):
        result = calculate_well_cost(
            design=design,
            config=config,
            reference_rop_mhr=reference_rop_mhr,
            npt_scenario=npt_scenario,
            currency=currency,
            campaign_wells=n_wells,
            well_index=i,
        )
        results.append(result)

    return results


# ============================================================================
# DrillingRegression protocol adapter
# ============================================================================


class NCSActivityDrillingRegression:
    """NCS activity-based drilling cost regression.

    Satisfies the DrillingRegression protocol from drilling.py.
    Internally uses the bottom-up activity model to compute well cost.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        currency: Literal["nok", "usd"] = "nok",
        npt_scenario: Literal["optimistic", "base", "conservative"] = "base",
        reference_rop_mhr: float | None = None,
        cra_grade: str = "25Cr_super_duplex",
    ):
        self.name = "ncs_activity"
        self.region = "norway-ncs"
        self._currency = currency
        self._npt_scenario = npt_scenario
        self._reference_rop = reference_rop_mhr
        self._cra_grade = cra_grade
        self._config = load_model_config(
            Path(config_path) if config_path else None
        )

        rates = self._config["day_rates"][currency]
        self.base_year = 2026
        self.currency = currency.upper()

    def cost(
        self,
        depth_m: float,
        water_depth_m: float = 0.0,
        well_type: str = "injection",
    ) -> float:
        """Return per-well cost for DrillingRegression protocol.

        Creates a default well design from depth and water depth,
        then runs the full activity model.
        """
        if water_depth_m <= 0:
            water_depth_m = 200.0  # Default NCS offshore

        design = default_well_design(
            target_tvd_m=depth_m,
            water_depth_m=water_depth_m,
            cra_grade=self._cra_grade,
            config=self._config,
        )

        result = calculate_well_cost(
            design=design,
            config=self._config,
            reference_rop_mhr=self._reference_rop,
            npt_scenario=self._npt_scenario,
            currency=self._currency,
        )

        return result.total_cost

    def well_time(
        self,
        depth_m: float,
        water_depth_m: float = 200.0,
    ) -> WellTimeResult:
        """Calculate well time (not part of protocol, but useful)."""
        design = default_well_design(
            target_tvd_m=depth_m,
            water_depth_m=water_depth_m,
            cra_grade=self._cra_grade,
            config=self._config,
        )
        return calculate_well_time(
            design=design,
            config=self._config,
            reference_rop_mhr=self._reference_rop,
            npt_scenario=self._npt_scenario,
        )

    def detailed_cost(
        self,
        depth_m: float,
        water_depth_m: float = 200.0,
        campaign_wells: int = 1,
        well_index: int = 1,
    ) -> WellCostResult:
        """Full cost breakdown (not part of protocol)."""
        design = default_well_design(
            target_tvd_m=depth_m,
            water_depth_m=water_depth_m,
            cra_grade=self._cra_grade,
            config=self._config,
        )
        return calculate_well_cost(
            design=design,
            config=self._config,
            reference_rop_mhr=self._reference_rop,
            npt_scenario=self._npt_scenario,
            currency=self._currency,
            campaign_wells=campaign_wells,
            well_index=well_index,
        )

"""CRA material cost model for CO2 injection wells.

Standalone module for computing bottom-up casing material costs with
CRA (Corrosion Resistant Alloy) pricing, equipment costs, and
default casing program generation for NCS CO2 wells.

CRA applies only to production casing and tubing (~15-20% of total
steel by weight). Net CRA impact on total well cost: +5-12%.

Sources:
    IEAGHG 2018-08: CRA cost multipliers (Table 5, Wojtanowicz et al.)
    Argus Pipe Logix May 2025: Carbon steel OCTG base price
    NL Phase 1 Aker Solutions contract: Subsea tree/wellhead pricing
    well_cost_reference.yaml: 6 Oliasoft reference wells (casing programs)
    ncs_drilling_model.yaml: NCS drilling model parameters
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field


# ============================================================================
# Constants
# ============================================================================

PPF_TO_KGM = 1.4882  # 1 lb/ft = 1.4882 kg/m


# ============================================================================
# Data models
# ============================================================================


class CasingSection(BaseModel):
    """Single casing string section."""

    name: str  # e.g. "conductor", "surface", "intermediate", "production", "liner"
    outer_diameter_in: float
    weight_ppf: float  # pounds per foot
    length_m: float
    material_grade: str = "carbon_steel"  # "carbon_steel", "13Cr", "22Cr", "25Cr"
    shoe_depth_m: float


class CRAMaterialModel(BaseModel):
    """CRA material cost parameters.

    Sources: IEAGHG 2018-08 (CRA multipliers), Argus Pipe Logix May 2025
    (carbon steel base price).
    """

    carbon_steel_price_usd_per_tonne: float = 2285.0  # Argus May 2025, L80 SML
    cra_multipliers: dict[str, float] = Field(
        default_factory=lambda: {
            "carbon_steel": 1.0,
            "13Cr": 3.0,    # IEAGHG 2018-08
            "22Cr": 4.5,    # IEAGHG 2018-08
            "25Cr": 5.5,    # IEAGHG 2018-08
        }
    )
    norway_premium: float = 1.4  # NORSOK compliance + freight
    usd_to_nok: float = 10.5    # approximate 2024-2025 rate
    grade_factors: dict[str, float] = Field(
        default_factory=lambda: {
            "X56": 0.90,   # conductor
            "K55": 0.90,   # surface
            "L80": 1.00,   # reference
            "P110": 1.15,  # intermediate
            "Q125": 1.25,  # production (carbon steel)
        }
    )


class CasingSectionCost(BaseModel):
    """Cost result for a single casing section."""

    name: str
    outer_diameter_in: float
    length_m: float
    weight_kg_per_m: float
    weight_tonnes: float
    material_grade: str
    multiplier: float
    cost_usd: float
    cost_mnok: float


class CasingCostResult(BaseModel):
    """Aggregated casing cost result."""

    sections: list[CasingSectionCost]
    total_steel_tonnes: float
    total_cost_usd: float
    total_cost_mnok: float
    carbon_steel_only_cost_mnok: float
    cra_premium_mnok: float
    cra_premium_pct: float  # CRA premium as % of carbon-steel-only cost


class EquipmentCosts(BaseModel):
    """Fixed equipment costs per well. All values in MNOK.

    Source: subsea-tree-pricing.md (NL Phase 1 Aker Solutions contract),
    IEAGHG 2018-08, industry data.
    """

    subsea_xt_mnok: float = 112.5       # NOK 100-125M (NL Phase 1)
    wellhead_mnok: float = 7.5           # NOK 5-10M
    completion_mnok: float = 12.0        # NOK 7-17M (DHSV + packer + gauges)
    monitoring_mnok: float = 6.25        # NOK 3.5-9M (DTS + gauges)
    mob_demob_mnok: float = 15.5         # NOK 8-23M (per-well share of campaign)
    cement_co2_premium_mnok: float = 1.75  # NOK ~1.75M (+25% on production cement)

    @property
    def total_mnok(self) -> float:
        return (
            self.subsea_xt_mnok
            + self.wellhead_mnok
            + self.completion_mnok
            + self.monitoring_mnok
            + self.mob_demob_mnok
            + self.cement_co2_premium_mnok
        )


# ============================================================================
# Core calculations
# ============================================================================


def ppf_to_kgm(weight_ppf: float) -> float:
    """Convert pounds per foot to kg/m."""
    return weight_ppf * PPF_TO_KGM


def calculate_casing_cost(
    sections: list[CasingSection],
    model: CRAMaterialModel | None = None,
) -> CasingCostResult:
    """Calculate section-by-section casing material cost.

    CRA (25Cr) applies to production casing and tubing/liner only, which
    represents ~15-20% of total steel weight. Net CRA impact on total
    casing cost: approximately 2x the production section cost.

    Args:
        sections: List of casing sections with geometry and material grade.
        model: CRA material cost parameters. Uses defaults if None.

    Returns:
        CasingCostResult with per-section costs and totals in both USD and MNOK.
    """
    if model is None:
        model = CRAMaterialModel()

    section_costs: list[CasingSectionCost] = []
    total_usd = 0.0
    cs_only_usd = 0.0
    total_tonnes = 0.0

    for sec in sections:
        weight_kgm = ppf_to_kgm(sec.weight_ppf)
        weight_tonnes = weight_kgm * sec.length_m / 1000.0
        total_tonnes += weight_tonnes

        # Determine multiplier
        if sec.material_grade in model.cra_multipliers:
            mult = model.cra_multipliers[sec.material_grade]
        elif sec.material_grade in model.grade_factors:
            mult = model.grade_factors[sec.material_grade]
        else:
            mult = 1.0

        # Actual cost with CRA/grade multiplier
        price_usd_per_t = (
            model.carbon_steel_price_usd_per_tonne * mult * model.norway_premium
        )
        cost_usd = weight_tonnes * price_usd_per_t

        # Carbon-steel-only baseline (grade factor for the section type)
        cs_grade = _default_grade_for_section(sec.name)
        cs_mult = model.grade_factors.get(cs_grade, 1.0)
        cs_price = (
            model.carbon_steel_price_usd_per_tonne * cs_mult * model.norway_premium
        )
        cs_cost_usd = weight_tonnes * cs_price

        total_usd += cost_usd
        cs_only_usd += cs_cost_usd

        section_costs.append(
            CasingSectionCost(
                name=sec.name,
                outer_diameter_in=sec.outer_diameter_in,
                length_m=sec.length_m,
                weight_kg_per_m=weight_kgm,
                weight_tonnes=weight_tonnes,
                material_grade=sec.material_grade,
                multiplier=mult,
                cost_usd=cost_usd,
                cost_mnok=cost_usd * model.usd_to_nok / 1e6,
            )
        )

    total_mnok = total_usd * model.usd_to_nok / 1e6
    cs_only_mnok = cs_only_usd * model.usd_to_nok / 1e6
    cra_prem_mnok = total_mnok - cs_only_mnok
    cra_prem_pct = (cra_prem_mnok / cs_only_mnok * 100.0) if cs_only_mnok > 0 else 0.0

    return CasingCostResult(
        sections=section_costs,
        total_steel_tonnes=total_tonnes,
        total_cost_usd=total_usd,
        total_cost_mnok=total_mnok,
        carbon_steel_only_cost_mnok=cs_only_mnok,
        cra_premium_mnok=cra_prem_mnok,
        cra_premium_pct=cra_prem_pct,
    )


def calculate_equipment_costs(
    subsea_xt_mnok: float = 112.5,
    wellhead_mnok: float = 7.5,
    completion_mnok: float = 12.0,
    monitoring_mnok: float = 6.25,
    mob_demob_mnok: float = 15.5,
    cement_co2_premium_mnok: float = 1.75,
) -> EquipmentCosts:
    """Fixed equipment costs per well. All values in MNOK.

    Source: NL Phase 1 Aker Solutions contract, IEAGHG 2018-08, industry.

    Returns:
        EquipmentCosts with itemized and total costs.
    """
    return EquipmentCosts(
        subsea_xt_mnok=subsea_xt_mnok,
        wellhead_mnok=wellhead_mnok,
        completion_mnok=completion_mnok,
        monitoring_mnok=monitoring_mnok,
        mob_demob_mnok=mob_demob_mnok,
        cement_co2_premium_mnok=cement_co2_premium_mnok,
    )


def calculate_cement_cost(
    sections: list[CasingSection],
    cement_usd_per_m3: float = 500.0,
    co2_premium: float = 0.25,
    excess_factor: float = 1.30,
    usd_to_nok: float = 10.5,
) -> float:
    """CO2-resistant cement cost for production sections.

    Base cement ~NOK 7M for a full well. CO2-resistant cement (EverCRETE type)
    adds +25% on production/liner sections.

    Args:
        sections: Casing sections with geometry.
        cement_usd_per_m3: Base cement cost per m3 delivered offshore.
        co2_premium: Fractional premium for CO2-resistant cement.
        excess_factor: Washout/loss factor (typically 1.3).
        usd_to_nok: Exchange rate.

    Returns:
        Total cement cost in MNOK.
    """
    total_usd = 0.0
    for sec in sections:
        hole_d_m = sec.outer_diameter_in * 0.0254 * _hole_to_casing_ratio(sec.name)
        casing_d_m = sec.outer_diameter_in * 0.0254
        annular_vol = math.pi / 4 * (hole_d_m**2 - casing_d_m**2) * sec.length_m * excess_factor
        is_production = sec.name in ("production", "liner")
        price = cement_usd_per_m3 * (1 + co2_premium) if is_production else cement_usd_per_m3
        total_usd += annular_vol * price

    return total_usd * usd_to_nok / 1e6


def default_casing_program(
    tvd_m: float,
    water_depth_m: float = 300.0,
    air_gap_m: float = 25.0,
    cra_grade: str = "25Cr",
) -> list[CasingSection]:
    """Generate default NCS CO2 well casing program based on TVD.

    Uses reference well data from well_cost_reference.yaml. CRA (25Cr)
    applied to production casing and liner only. Upper sections use
    carbon steel.

    Args:
        tvd_m: Target vertical depth (m).
        water_depth_m: Water depth (m).
        air_gap_m: Air gap above sea level (m).
        cra_grade: CRA grade for production casing ("25Cr", "22Cr", "13Cr").

    Returns:
        List of CasingSection defining the well casing program.
    """
    rkb = water_depth_m + air_gap_m
    td_md = tvd_m + rkb  # vertical well, MD = TVD + RKB offset

    sections: list[CasingSection] = []

    # Conductor: 30" @ 100m below mudline
    conductor_shoe = rkb + 100.0
    sections.append(
        CasingSection(
            name="conductor",
            outer_diameter_in=30.0,
            weight_ppf=309.7,
            length_m=conductor_shoe,
            material_grade="carbon_steel",
            shoe_depth_m=conductor_shoe,
        )
    )

    # Surface: 20" @ 300-400m below mudline
    surface_depth_below_ml = 300.0 if tvd_m < 2000 else 400.0
    surface_shoe = rkb + surface_depth_below_ml
    sections.append(
        CasingSection(
            name="surface",
            outer_diameter_in=20.0,
            weight_ppf=133.0,
            length_m=surface_shoe - conductor_shoe,
            material_grade="carbon_steel",
            shoe_depth_m=surface_shoe,
        )
    )

    # Intermediate: 13-3/8" @ 55-65% of TD (for wells > 1200m TVD)
    if tvd_m > 1200:
        inter_fraction = 0.55 if tvd_m < 2000 else 0.65
        inter_shoe = rkb + tvd_m * inter_fraction
        sections.append(
            CasingSection(
                name="intermediate",
                outer_diameter_in=13.375,
                weight_ppf=72.0,
                length_m=inter_shoe - surface_shoe,
                material_grade="carbon_steel",
                shoe_depth_m=inter_shoe,
            )
        )
        prod_top = inter_shoe
    else:
        prod_top = surface_shoe

    # Production: 9-5/8" to TD — CRA grade
    sections.append(
        CasingSection(
            name="production",
            outer_diameter_in=9.625,
            weight_ppf=53.5,
            length_m=td_md - prod_top,
            material_grade=cra_grade,
            shoe_depth_m=td_md,
        )
    )

    # Liner: 7" for deep wells (TVD > 2800m) — additional 500m below TD
    if tvd_m > 2800:
        liner_shoe = td_md + 500.0
        sections.append(
            CasingSection(
                name="liner",
                outer_diameter_in=7.0,
                weight_ppf=35.0,
                length_m=500.0,
                material_grade=cra_grade,
                shoe_depth_m=liner_shoe,
            )
        )

    return sections


# ============================================================================
# Helpers
# ============================================================================


def _default_grade_for_section(name: str) -> str:
    """Return the default carbon steel grade for a section name."""
    mapping = {
        "conductor": "X56",
        "surface": "K55",
        "intermediate": "P110",
        "production": "Q125",
        "liner": "Q125",
    }
    return mapping.get(name, "L80")


def _hole_to_casing_ratio(name: str) -> float:
    """Return hole/casing diameter ratio for cement volume estimation.

    Based on standard NCS hole/casing combinations from reference wells.
    """
    ratios = {
        "conductor": 36.0 / 30.0,
        "surface": 26.0 / 20.0,
        "intermediate": 17.5 / 13.375,
        "production": 12.25 / 9.625,
        "liner": 8.5 / 7.0,
    }
    return ratios.get(name, 12.25 / 9.625)

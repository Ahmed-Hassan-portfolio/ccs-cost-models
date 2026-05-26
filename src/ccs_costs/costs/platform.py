"""Platform jacket and subsea tieback infrastructure cost models.

Two infrastructure paradigms:
1. PLATFORM_JACKET: Dedicated jacket platform + satellite (NETL/GOA model)
2. SUBSEA_TIEBACK: Subsea injection system tied to existing platform (Norwegian CCS paradigm)

The jacket model uses QUE$TOR regressions extracted from NETL Offshore_Eq sheet:
    Substructure cost = f(water_depth_ft), linear regression
    Superstructure cost = f(injection_rate_Mtpa), linear regression
    O&M = f(water_depth_ft, injection_rate_Mtpa), linear regressions
    Decommissioning = f(water_depth_ft), linear regression

NETL cost structure (from Back-End_Cost Items analysis):
    - CAPEX = (structure_regression) * 1.15 process contingency
    - Ops O&M = annual_regression * ops_years + additional_per_5yr * n_events
    - PISC "O&M" = decommissioning cost (one-time at PISC end, NOT annual O&M)
    - No ongoing platform O&M during PISC

NETL uses two structure types:
    Primary: Jacket (4-legged) — supports injection wells
    Satellite: Caisson — supports monitoring wells

References:
    NETL CO2_S_COM_Offshore v1.1: Offshore_Eq sheet, Back-End_Cost Items
    QUE$TOR: Offshore cost estimation tool (regressions extracted by NETL)
    Meld. St. 33 (2019-2020): Northern Lights cost chapter
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)


# ============================================================================
# Infrastructure model types
# ============================================================================


class InfrastructureModel(str, Enum):
    """Available infrastructure model types."""

    PLATFORM_JACKET = "jacket"
    SUBSEA_TIEBACK = "subsea_tieback"


# ============================================================================
# Output model
# ============================================================================


class PlatformCosts(BaseModel):
    """Complete infrastructure cost output."""

    infrastructure_model: str
    capex: float
    opex_annual: float = 0.0
    opex_total: float = 0.0
    decommissioning: float = 0.0
    confidence_level: str = "A"
    base_year: int = 2008
    currency: str = "USD"
    items: list[CostItem] = []


# ============================================================================
# QUE$TOR regressions from NETL Offshore_Eq sheet
# ============================================================================

# Escalation factors (NETL Key_Inputs AC28/AC29, hardcoded):
#   CAPEX: divide by (1 + (-0.0897)) = 0.9103 to convert 2022$ → 2008$
#   OPEX:  divide by (1 + 0.0065)    = 1.0065 to convert 2022$ → 2008$
_CAPEX_ESC = 1.0 + (-0.0897)  # 0.9103
_OPEX_ESC = 1.0 + 0.0065      # 1.0065

# Process contingency applied to all platform CAPEX (NETL Back-End_Cost Items AQ column)
_PROCESS_CONTINGENCY = 1.15

# 1 metre = 3.28084 feet
_M_TO_FT = 3.28084


def _jacket_primary_costs(water_depth_ft: float, rate_mtpa: float) -> dict:
    """Primary jacket platform costs (2008$).

    Regressions from NETL Offshore_Eq for Jacket, New, Mobile Rig.
    """
    # Structure CAPEX (2022$)
    sub_capex = 136_507 * water_depth_ft + 16_864_498
    super_capex = 697_900 * rate_mtpa + 8_094_300
    capex_2008 = (sub_capex + super_capex) / _CAPEX_ESC * _PROCESS_CONTINGENCY

    # Annual O&M (2022$ → 2008$/yr)
    sub_om = 3_497.73 * water_depth_ft + 725_401.54
    super_om = 10_900 * rate_mtpa + 124_100
    om_annual_2008 = (sub_om + super_om) / _OPEX_ESC

    # Additional superstructure O&M every 5 years (2022$ → 2008$)
    add_om = 27_100 * rate_mtpa + 285_500
    add_om_2008 = add_om / _OPEX_ESC

    # Decommissioning (2022$ → 2008$)
    decom = 52_649 * water_depth_ft + 6_000_000
    decom_2008 = decom / _OPEX_ESC

    # Scrap revenue (2022$ → 2008$)
    scrap = 6_107 * water_depth_ft + 210_553
    scrap_2008 = scrap / _OPEX_ESC

    return {
        "capex": capex_2008,
        "om_annual": om_annual_2008,
        "add_om_per_5yr": add_om_2008,
        "decom": decom_2008,
        "scrap": scrap_2008,
    }


def _caisson_satellite_costs(water_depth_ft: float) -> dict:
    """Satellite caisson platform costs (2008$).

    Regressions from NETL Offshore_Eq for Caisson, New.
    """
    # Structure CAPEX (2022$)
    sub_capex = 8_801.5 * water_depth_ft + 6_172_382
    super_capex = 8_272_000  # fixed
    capex_2008 = (sub_capex + super_capex) / _CAPEX_ESC * _PROCESS_CONTINGENCY

    # Annual O&M (2022$ → 2008$/yr)
    sub_om = 3_157.47 * water_depth_ft + 731_928.05
    super_om = 131_000  # fixed
    om_annual_2008 = (sub_om + super_om) / _OPEX_ESC

    # Additional superstructure O&M every 5 years (2022$ → 2008$)
    add_om_2008 = 272_000 / _OPEX_ESC

    # Decommissioning (2022$ → 2008$)
    decom = 2_049.8 * water_depth_ft + 5_000_000
    decom_2008 = decom / _OPEX_ESC

    # Scrap revenue (2022$ → 2008$)
    scrap = 513.83 * water_depth_ft + 37_165
    scrap_2008 = scrap / _OPEX_ESC

    return {
        "capex": capex_2008,
        "om_annual": om_annual_2008,
        "add_om_per_5yr": add_om_2008,
        "decom": decom_2008,
        "scrap": scrap_2008,
    }


def platform_cost_jacket(
    water_depth_m: float,
    n_wells: int,
    is_primary: bool = True,
    base_year: int = 2008,
    currency: str = "USD",
    construction_year: int = 6,
    operations_begin: int = 9,
    operations_end: int = 38,
    pisc_end: int = 88,
    decom_year: int = 84,
    injection_rate_tpa: float = 4_000_000,
    om_ops_total: float | None = None,
    om_pisc_total: float | None = None,
) -> PlatformCosts:
    """Calculate jacket platform costs using QUE$TOR regressions.

    Uses linear regressions from NETL Offshore_Eq with 1.15 process
    contingency on CAPEX. O&M is split into ops (annual + periodic)
    and PISC (decommissioning only, no ongoing O&M).

    The NETL cost structure (from Back-End_Cost Items decomposition):
        - r929: CAPEX = regression * 1.15 contingency
        - r930: Annual O&M during ops (regression rate)
        - r931: Additional O&M every 5yr during ops
        - r932: Decommissioning at PISC end (NOT annual PISC O&M)

    Args:
        water_depth_m: Water depth in metres.
        n_wells: Number of injection wells.
        is_primary: True for primary (jacket), False for satellite (caisson).
        base_year: Cost base year.
        currency: Currency code.
        construction_year: Project year for construction.
        operations_begin: First year of operations.
        operations_end: Last year of operations.
        pisc_end: Last year of PISC.
        decom_year: Year of decommissioning.
        injection_rate_tpa: Annual CO2 injection rate (tonnes/yr).
        om_ops_total: Override total ops O&M (unused, kept for API compat).
        om_pisc_total: Override total PISC O&M (unused, kept for API compat).

    Returns:
        PlatformCosts with CAPEX, O&M, decommissioning, and CostItems.
    """
    wd_ft = water_depth_m * _M_TO_FT

    if is_primary:
        costs = _jacket_primary_costs(wd_ft, injection_rate_tpa / 1e6)
        label = "Primary"
        prefix = "PLAT-PRI"
    else:
        costs = _caisson_satellite_costs(wd_ft)
        label = "Satellite"
        prefix = "PLAT-SAT"

    ops_years = operations_end - operations_begin + 1
    pisc_years = pisc_end - operations_end

    # Ops O&M: annual rate + periodic additional every 5 years
    # NETL amortizes periodic into ops total: annual*30 + additional*n_events
    n_add_events = ops_years // 5 if ops_years > 0 else 0
    ops_om_total = costs["om_annual"] * ops_years + costs["add_om_per_5yr"] * n_add_events
    # Amortized annual rate for CostItem (uniform over ops years)
    ops_annual_amortized = ops_om_total / ops_years if ops_years > 0 else 0.0

    # PISC: decommissioning only (one-time), no ongoing O&M
    decom_net = costs["decom"] - costs["scrap"]

    # Total O&M = ops O&M + decom (matches NETL Cost Breakdown 1 total)
    opex_total = ops_om_total + costs["decom"]

    items: list[CostItem] = [
        # CAPEX
        CostItem(
            id=f"{prefix}-CAPEX",
            name=f"{label} offshore structure construction",
            category="infrastructure",
            subcategory=f"platform_{label.lower()}_capex",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=costs["capex"],
            base_year=base_year,
            currency=currency,
            begin_year=construction_year,
            end_year=construction_year,
            recurrence="one-time",
            quantity=1.0,
            notes=f"QUE$TOR regression * 1.15 contingency (wd={water_depth_m:.0f}m)",
        ),
        # Ops O&M (amortized annual including periodic additional)
        CostItem(
            id=f"{prefix}-OPEX-OPS",
            name=f"{label} offshore structure O&M (operations)",
            category="infrastructure",
            subcategory=f"platform_{label.lower()}_om",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=ops_annual_amortized,
            base_year=base_year,
            currency=currency,
            begin_year=operations_begin,
            end_year=operations_end,
            recurrence="annual",
            quantity=1.0,
            notes=f"{label} O&M: annual + periodic additional (amortized)",
        ),
        # PISC: decommissioning (one-time at end)
        CostItem(
            id=f"{prefix}-OPEX-PISC",
            name=f"{label} offshore structure decommissioning",
            category="infrastructure",
            subcategory=f"platform_{label.lower()}_om",
            stage="pisc",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=costs["decom"],
            base_year=base_year,
            currency=currency,
            begin_year=pisc_end,
            end_year=pisc_end,
            recurrence="one-time",
            quantity=1.0,
            notes=f"{label} decom: QUE$TOR regression (wd={water_depth_m:.0f}m)",
        ),
    ]

    return PlatformCosts(
        infrastructure_model="jacket",
        capex=costs["capex"],
        opex_annual=ops_annual_amortized,
        opex_total=opex_total,
        decommissioning=costs["decom"],
        confidence_level="A",
        base_year=base_year,
        currency=currency,
        items=items,
    )


# ============================================================================
# Subsea tieback model (Northern Lights anchored)
# ============================================================================

_NL_SUBSEA_INJECTION_PER_WELL_NOK = 250_000_000
_NL_PLATFORM_CONTROL_NOK = 140_000_000
_NL_MANIFOLD_PER_TEMPLATE_NOK = 80_000_000
_NL_UMBILICAL_PER_KM_NOK = 5_000_000


def subsea_tieback_cost(
    n_wells: int,
    water_depth_m: float,
    distance_to_host_km: float = 0.0,
    base_year: int = 2024,
    currency: str = "NOK",
    construction_year: int = 6,
    operations_begin: int = 9,
    operations_end: int = 38,
    pisc_end: int = 58,
    decom_year: int = 54,
    **kwargs,
) -> PlatformCosts:
    """Calculate subsea tieback infrastructure costs.

    Norwegian CCS paradigm: subsea injection system, no dedicated platform.
    Based on Northern Lights Phase 1 contract values.

    Confidence level C: Limited evidence, primarily Northern Lights anchored.
    """
    injection_system = n_wells * _NL_SUBSEA_INJECTION_PER_WELL_NOK
    control_system = _NL_PLATFORM_CONTROL_NOK
    n_templates = max(1, (n_wells + 1) // 2)
    manifold = n_templates * _NL_MANIFOLD_PER_TEMPLATE_NOK
    umbilical = distance_to_host_km * _NL_UMBILICAL_PER_KM_NOK if distance_to_host_km > 0 else 0.0

    capex = injection_system + control_system + manifold + umbilical
    opex_annual = capex * 0.03
    total_om_years = (operations_end - operations_begin + 1) + (pisc_end - operations_end)
    opex_total = opex_annual * total_om_years

    items: list[CostItem] = [
        CostItem(
            id="SUBSEA-INJECT", name="Subsea injection system",
            category="infrastructure", subcategory="subsea_injection",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=float(injection_system),
            base_year=base_year, currency=currency,
            begin_year=construction_year, end_year=construction_year,
            recurrence="one-time", quantity=1.0,
            notes=f"NOK 250M/well x {n_wells} wells",
        ),
        CostItem(
            id="SUBSEA-CONTROL", name="Platform control system",
            category="infrastructure", subcategory="platform_control",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=float(control_system),
            base_year=base_year, currency=currency,
            begin_year=construction_year, end_year=construction_year,
            recurrence="one-time", quantity=1.0,
            notes="NOK 140M (Aibel NL contract)",
        ),
        CostItem(
            id="SUBSEA-MANIFOLD", name="Subsea manifold/template",
            category="infrastructure", subcategory="subsea_manifold",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=float(manifold),
            base_year=base_year, currency=currency,
            begin_year=construction_year, end_year=construction_year,
            recurrence="one-time", quantity=1.0,
            notes=f"{n_templates} template(s), NOK 80M each",
        ),
    ]

    if umbilical > 0:
        items.append(CostItem(
            id="SUBSEA-UMBILICAL", name="Umbilical to host platform",
            category="infrastructure", subcategory="umbilical",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=float(umbilical),
            base_year=base_year, currency=currency,
            begin_year=construction_year, end_year=construction_year,
            recurrence="one-time", quantity=1.0,
            notes=f"NOK 5M/km x {distance_to_host_km:.1f} km",
        ))

    items.extend([
        CostItem(
            id="SUBSEA-OPEX-OPS", name="Subsea infrastructure O&M (operations)",
            category="infrastructure", subcategory="subsea_om",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=opex_annual,
            base_year=base_year, currency=currency,
            begin_year=operations_begin, end_year=operations_end,
            recurrence="annual", quantity=1.0,
            notes="3% of CAPEX annual O&M",
        ),
        CostItem(
            id="SUBSEA-OPEX-PISC", name="Subsea infrastructure O&M (PISC)",
            category="infrastructure", subcategory="subsea_om",
            stage="pisc",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=opex_annual,
            base_year=base_year, currency=currency,
            begin_year=operations_end + 1, end_year=pisc_end,
            recurrence="annual", quantity=1.0,
            notes="3% of CAPEX annual O&M (PISC period)",
        ),
    ])

    return PlatformCosts(
        infrastructure_model="subsea_tieback",
        capex=capex, opex_annual=opex_annual, opex_total=opex_total,
        decommissioning=0.0, confidence_level="C",
        base_year=base_year, currency=currency, items=items,
    )


# ============================================================================
# Dispatcher
# ============================================================================


def calculate_infrastructure_costs(
    model_type: InfrastructureModel,
    water_depth_m: float,
    n_wells: int,
    **kwargs,
) -> PlatformCosts:
    """Dispatch to appropriate infrastructure cost model."""
    if model_type == InfrastructureModel.PLATFORM_JACKET:
        return platform_cost_jacket(
            water_depth_m=water_depth_m, n_wells=n_wells,
            is_primary=True, **kwargs,
        )
    elif model_type == InfrastructureModel.SUBSEA_TIEBACK:
        return subsea_tieback_cost(
            n_wells=n_wells, water_depth_m=water_depth_m, **kwargs,
        )
    else:
        raise ValueError(f"Unknown infrastructure model: {model_type}")

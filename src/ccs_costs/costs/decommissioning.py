"""End-of-life decommissioning cost calculations.

Calculates costs for well plugging & abandonment, pipeline abandonment,
and platform removal. All decommissioning items occur during the PISC
(post-injection site care) stage.

Components:
    - Well P&A: cost per well from region config
    - Pipeline abandonment: rate per km (BSEE $1,593,000/mile for US)
    - Platform removal: scaled by water depth and structure type

References:
    NETL CO2_S_COM_Offshore v1.1: Back-End_Cost Items sheet
    BSEE Pacific OCS: Pipeline decommissioning rates
"""

from __future__ import annotations

from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)
from ccs_costs.geo.schedule import WellPlan


# ============================================================================
# Constants
# ============================================================================

_MI_TO_KM = 1.609344
_FT_TO_M = 0.3048

# BSEE default pipeline decommissioning rate (2008$)
_BSEE_DECOM_RATE_PER_MI = 1_593_000.0  # USD/mile
_BSEE_DECOM_RATE_PER_KM = _BSEE_DECOM_RATE_PER_MI / _MI_TO_KM  # USD/km

# Default well P&A costs (2008$ from NETL)
# NETL implied: PISC capital ($61,147,836) - 3D seismic PISC ($54,123,108)
# - 2D seismic PISC ($1,558,544) = $5,466,184 for 7 wells = $780,883/well
_DEFAULT_WELL_PA_COST = 780_883.0  # USD per well (NETL calibrated)

# Platform removal base cost (2008$, approximate from QUE$TOR)
_PLATFORM_REMOVAL_BASE = 5_000_000.0  # USD base
_PLATFORM_REMOVAL_DEPTH_FACTOR = 50_000.0  # USD per meter of water depth


# ============================================================================
# Data models
# ============================================================================


class DecommissioningCosts(BaseModel):
    """Complete decommissioning cost output."""

    total: float
    items: list[CostItem]


# ============================================================================
# Cost calculation
# ============================================================================


def calculate_decommissioning_costs(
    well_plan: WellPlan,
    pipeline_length_km: float,
    water_depth_m: float = 21.0,
    pisc_start_year: int = 36,
    pisc_end_year: int = 85,
    base_year: int = 2008,
    currency: str = "USD",
    pipeline_decom_rate_per_km: float | None = None,
    well_pa_cost_per_well: float | None = None,
    platform_removal_cost: float | None = None,
) -> DecommissioningCosts:
    """Calculate all decommissioning costs.

    All items are placed in the PISC stage, typically near the end
    of the PISC period (last year or years).

    Args:
        well_plan: WellPlan with well type counts.
        pipeline_length_km: Pipeline length in km.
        water_depth_m: Water depth in meters (for platform removal scaling).
        pisc_start_year: First project year of PISC stage.
        pisc_end_year: Last project year of PISC stage.
        base_year: Cost base year.
        currency: Currency code.
        pipeline_decom_rate_per_km: Pipeline decom rate per km. Defaults to BSEE rate.
        well_pa_cost_per_well: Well P&A cost per well. Defaults to NETL estimate.
        platform_removal_cost: Total platform removal cost. If None, estimated from water depth.

    Returns:
        DecommissioningCosts with total and itemized list.
    """
    items: list[CostItem] = []
    total = 0.0

    # Decommissioning occurs in the last year of PISC
    decom_year = pisc_end_year

    # ---------------------------------------------------------------
    # Pipeline abandonment
    # ---------------------------------------------------------------
    rate_per_km = pipeline_decom_rate_per_km or _BSEE_DECOM_RATE_PER_KM
    pipe_decom = rate_per_km * pipeline_length_km

    items.append(CostItem(
        id="DECOM-PIPELINE",
        name="Pipeline decommissioning/abandonment",
        category="decommissioning",
        subcategory="pipeline_decom",
        stage="pisc",
        classification=CostClassification.EXPENSE,
        depreciation_category=DepreciationCategory.NONE,
        amount_base_year=pipe_decom,
        base_year=base_year,
        currency=currency,
        begin_year=decom_year,
        end_year=decom_year,
        recurrence="one-time",
    ))
    total += pipe_decom

    # ---------------------------------------------------------------
    # Well plugging & abandonment
    # ---------------------------------------------------------------
    # Only injection and monitoring wells require PISC decommissioning.
    # Stratigraphic test wells are plugged during characterization (not PISC).
    # NETL PISC capital: 61,147,836 - 54,123,108 (3D seismic) - 1,558,543 (2D seismic)
    # = 5,466,185 for 7 wells (5 injection + 2 monitoring) = 780,883/well
    pa_cost = well_pa_cost_per_well or _DEFAULT_WELL_PA_COST
    decom_wells = well_plan.n_injection + well_plan.n_monitoring

    items.append(CostItem(
        id="DECOM-WELLS",
        name="Well plugging & abandonment",
        category="decommissioning",
        subcategory="well_plugging",
        stage="pisc",
        classification=CostClassification.CAPITAL,
        depreciation_category=DepreciationCategory.PLUG_ABANDON,
        amount_base_year=pa_cost,
        base_year=base_year,
        currency=currency,
        begin_year=decom_year,
        end_year=decom_year,
        recurrence="one-time",
        quantity=float(decom_wells),
        notes=f"{decom_wells} wells (injection+monitoring) at ${pa_cost:,.0f}/well",
    ))
    total += pa_cost * decom_wells

    # ---------------------------------------------------------------
    # Platform removal
    # ---------------------------------------------------------------
    if platform_removal_cost is not None:
        plat_removal = platform_removal_cost
    else:
        # Estimate from water depth (simplified QUE$TOR regression)
        plat_removal = _PLATFORM_REMOVAL_BASE + _PLATFORM_REMOVAL_DEPTH_FACTOR * water_depth_m

    items.append(CostItem(
        id="DECOM-PLATFORM",
        name="Platform/infrastructure removal",
        category="decommissioning",
        subcategory="platform_removal",
        stage="pisc",
        classification=CostClassification.EXPENSE,
        depreciation_category=DepreciationCategory.NONE,
        amount_base_year=plat_removal,
        base_year=base_year,
        currency=currency,
        begin_year=decom_year,
        end_year=decom_year,
        recurrence="one-time",
    ))
    total += plat_removal

    return DecommissioningCosts(total=total, items=items)

"""Ship transport cost model for CO2.

Provides ship CAPEX regressions, operating cost models, liquefaction costs,
and pipeline-vs-ship crossover analysis for CO2 transport.

Ship transport is the alternative to pipeline for CO2 delivery, particularly
competitive at long distances (>1000 km) and low volumes (<2.5 Mtpa).

Sources:
    GCCSI 2025: Ship CAPEX power-law regressions (LP and MP vessels)
    d'Amore et al. 2021: Ship operating cost linear model by flow bin
    Roussanaly et al. 2024: Liquefaction cost range (12-15.5 EUR/t)
    Vikra 2025 (NTNU thesis): Charter rate $14.6M/vessel/year
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# GCCSI 2025 ship CAPEX regression coefficients
# y = a * x^b, where y = M USD (2023), x = ship capacity (tonnes)
_LP_COEFF_A = 1.8083
_LP_COEFF_B = 0.3966
_LP_R2 = 0.72

_MP_COEFF_A = 0.1334
_MP_COEFF_B = 0.6159
_MP_R2 = 0.70

# d'Amore 2021 ship transport cost: Cost = intercept + slope * distance_km [EUR/tCO2]
_DAMORE_SLOPE = 0.00609  # EUR/tCO2 per km

# d'Amore 2021 flow bin intercepts (EUR/tCO2)
_DAMORE_INTERCEPTS = {
    "250-1500": 12.911,
    "1500-2500": 11.911,
    "2500-7500": 7.911,
    "7500-30000": 7.911,
}

# Liquefaction cost (Roussanaly 2024)
LIQUEFACTION_COST_LOW = 12.0    # EUR/tCO2
LIQUEFACTION_COST_HIGH = 15.5   # EUR/tCO2
LIQUEFACTION_COST_MID = 13.75   # EUR/tCO2 (midpoint)

# Impurity premium on liquefaction (GCCSI 2025)
MAX_IMPURITY_PREMIUM = 0.34  # +34%

# Charter rate (Vikra 2025 thesis, Lloydslist/Baltic Exchange)
CHARTER_RATE_USD_PER_YEAR = 14_600_000  # $14.6M/vessel/year


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class ShipPressure(str, Enum):
    """Ship pressure class."""
    LP = "LP"   # Low pressure, ~7 bar, -50C
    MP = "MP"   # Medium pressure, ~15 bar, -30C


class ShipTransportCosts(BaseModel):
    """Complete ship transport cost output."""

    ship_capex_musd: float
    ship_pressure: str
    ship_capacity_tonnes: float
    n_vessels: int
    liquefaction_eur_per_t: float
    transport_eur_per_t: float
    total_eur_per_t: float
    charter_rate_usd_per_year: float
    base_year: int
    currency: str
    items: list[CostItem] = []


class TransportComparison(BaseModel):
    """Pipeline vs ship cost comparison result."""

    flow_mtpa: float
    distance_km: float
    pipeline_eur_per_t: float | None
    ship_eur_per_t: float
    preferred_mode: str
    ship_advantage_eur_per_t: float | None


# ---------------------------------------------------------------------------
# Ship CAPEX (GCCSI 2025)
# ---------------------------------------------------------------------------


def ship_capex_musd(capacity_tonnes: float, pressure: ShipPressure = ShipPressure.LP) -> float:
    """GCCSI 2025 ship CAPEX regression.

    Power-law regression from global CO2 carrier cost data:
        LP (7 bar, -50C): CAPEX = 1.8083 * capacity^0.3966  (R²=0.72)
        MP (15 bar, -30C): CAPEX = 0.1334 * capacity^0.6159  (R²=0.70)

    Args:
        capacity_tonnes: Ship cargo capacity in tonnes.
        pressure: Ship pressure class (LP or MP).

    Returns:
        Ship CAPEX in million USD (2023 basis).
    """
    if pressure == ShipPressure.LP:
        return _LP_COEFF_A * capacity_tonnes ** _LP_COEFF_B
    else:
        return _MP_COEFF_A * capacity_tonnes ** _MP_COEFF_B


# ---------------------------------------------------------------------------
# Operating cost (d'Amore 2021)
# ---------------------------------------------------------------------------


def _flow_bin(flow_ktpa: float) -> str:
    """Map annual flow rate to d'Amore flow bin."""
    if flow_ktpa <= 1500:
        return "250-1500"
    elif flow_ktpa <= 2500:
        return "1500-2500"
    elif flow_ktpa <= 7500:
        return "2500-7500"
    else:
        return "7500-30000"


def ship_transport_cost_eur_per_t(
    distance_km: float,
    flow_mtpa: float = 2.5,
) -> float:
    """d'Amore 2021 ship operating cost model.

    Linear model: Cost = Intercept + 0.00609 * distance_km [EUR/tCO2]
    Intercept depends on flow volume bin (economies of scale).

    Args:
        distance_km: One-way shipping distance in km.
        flow_mtpa: Annual CO2 flow rate in Mtpa (for flow bin selection).

    Returns:
        Ship operating cost in EUR/tCO2 (2018 basis).
    """
    flow_ktpa = flow_mtpa * 1000
    bin_key = _flow_bin(flow_ktpa)
    intercept = _DAMORE_INTERCEPTS[bin_key]
    return intercept + _DAMORE_SLOPE * distance_km


# ---------------------------------------------------------------------------
# Liquefaction
# ---------------------------------------------------------------------------


def liquefaction_cost_eur_per_t(
    base_cost: float = LIQUEFACTION_COST_MID,
    impurity_premium: float = 0.0,
) -> float:
    """Liquefaction cost for ship transport.

    Converts gaseous CO2 to liquid for ship loading. Includes cooling,
    compression, and buffer storage.

    Source: Roussanaly 2024: 12-15.5 EUR/t.
    Impurity premium up to +34% (GCCSI 2025).

    Args:
        base_cost: Base liquefaction cost in EUR/tCO2 (default 13.75, midpoint).
        impurity_premium: Fractional premium for impurities (0.0 to 0.34).

    Returns:
        Liquefaction cost in EUR/tCO2.
    """
    return base_cost * (1.0 + impurity_premium)


# ---------------------------------------------------------------------------
# Number of vessels required
# ---------------------------------------------------------------------------


def vessels_required(
    flow_mtpa: float,
    capacity_tonnes: float,
    distance_km: float,
    speed_knots: float = 12.0,
    port_days: float = 2.0,
    utilization: float = 0.90,
) -> int:
    """Estimate number of vessels needed for a given flow and distance.

    Simple round-trip model: time = 2 * distance / speed + port_time.
    Trips per year per vessel = available_days / round_trip_days.
    n_vessels = ceil(required_trips / trips_per_vessel).

    Args:
        flow_mtpa: Annual CO2 flow rate in Mtpa.
        capacity_tonnes: Ship cargo capacity in tonnes per trip.
        distance_km: One-way distance in km.
        speed_knots: Average sailing speed in knots (default 12).
        port_days: Total port time per round trip in days (default 2).
        utilization: Vessel utilization factor (default 0.90).

    Returns:
        Number of vessels required (integer, rounded up).
    """
    import math

    km_per_knot_day = 24 * 1.852  # knots to km/day
    sail_days = 2 * distance_km / (speed_knots * km_per_knot_day)
    round_trip_days = sail_days + port_days

    available_days = 365.25 * utilization
    trips_per_vessel = available_days / round_trip_days

    flow_tonnes = flow_mtpa * 1e6
    required_trips = flow_tonnes / capacity_tonnes

    return max(1, math.ceil(required_trips / trips_per_vessel))


# ---------------------------------------------------------------------------
# Pipeline vs ship crossover
# ---------------------------------------------------------------------------


def transport_mode_comparison(
    flow_mtpa: float,
    distance_km: float,
    pipeline_eur_per_t: float | None = None,
) -> TransportComparison:
    """Compare pipeline vs ship cost for CO2 transport.

    Uses d'Amore model for ship costs. If pipeline cost is not provided,
    uses heuristic crossover boundaries from literature:
        - Pipeline preferred: >5 Mtpa AND <500 km
        - Ship preferred: <2.5 Mtpa AND >1000 km
        - Mixed zone: everything else

    Args:
        flow_mtpa: Annual CO2 flow rate in Mtpa.
        distance_km: Transport distance in km.
        pipeline_eur_per_t: Pipeline transport cost in EUR/tCO2 (if known).

    Returns:
        TransportComparison with costs and preferred mode.
    """
    ship_cost = ship_transport_cost_eur_per_t(distance_km, flow_mtpa)
    liq_cost = liquefaction_cost_eur_per_t()
    total_ship = ship_cost + liq_cost

    if pipeline_eur_per_t is not None:
        advantage = pipeline_eur_per_t - total_ship
        if advantage > 0:
            preferred = "ship"
        elif advantage < 0:
            preferred = "pipeline"
        else:
            preferred = "indifferent"
        return TransportComparison(
            flow_mtpa=flow_mtpa,
            distance_km=distance_km,
            pipeline_eur_per_t=pipeline_eur_per_t,
            ship_eur_per_t=total_ship,
            preferred_mode=preferred,
            ship_advantage_eur_per_t=advantage,
        )

    # Heuristic crossover (no pipeline cost provided)
    if flow_mtpa >= 5.0 and distance_km <= 500:
        preferred = "pipeline"
    elif flow_mtpa <= 2.5 and distance_km >= 1000:
        preferred = "ship"
    else:
        preferred = "depends_on_specifics"

    return TransportComparison(
        flow_mtpa=flow_mtpa,
        distance_km=distance_km,
        pipeline_eur_per_t=pipeline_eur_per_t,
        ship_eur_per_t=total_ship,
        preferred_mode=preferred,
        ship_advantage_eur_per_t=None,
    )


# ---------------------------------------------------------------------------
# Full ship transport cost calculation with CostItems
# ---------------------------------------------------------------------------


def calculate_ship_transport_costs(
    flow_mtpa: float,
    distance_km: float,
    ship_capacity_tonnes: float = 7500,
    pressure: ShipPressure = ShipPressure.LP,
    impurity_premium: float = 0.0,
    base_year: int = 2023,
    currency: str = "USD",
    construction_year: int = 3,
    operations_begin: int = 4,
    operations_end: int = 33,
) -> ShipTransportCosts:
    """Calculate complete ship transport costs with CostItems.

    Args:
        flow_mtpa: Annual CO2 flow rate in Mtpa.
        distance_km: One-way shipping distance in km.
        ship_capacity_tonnes: Cargo capacity per vessel in tonnes.
        pressure: Ship pressure class (LP or MP).
        impurity_premium: Fractional premium on liquefaction (0 to 0.34).
        base_year: Cost base year.
        currency: Currency code.
        construction_year: Project year for ship/terminal construction.
        operations_begin: First year of operations.
        operations_end: Last year of operations.

    Returns:
        ShipTransportCosts with CostItem list.
    """
    # Ship CAPEX
    capex_per_ship = ship_capex_musd(ship_capacity_tonnes, pressure)
    n_ships = vessels_required(flow_mtpa, ship_capacity_tonnes, distance_km)
    total_ship_capex = capex_per_ship * n_ships  # M USD

    # Liquefaction terminal CAPEX (rough: ~50% of ship fleet CAPEX, from ZEP/GCCSI)
    liq_capex = total_ship_capex * 0.5  # M USD

    # Operating costs
    transport_cost = ship_transport_cost_eur_per_t(distance_km, flow_mtpa)
    liq_cost = liquefaction_cost_eur_per_t(impurity_premium=impurity_premium)
    total_per_t = transport_cost + liq_cost

    # Annual OPEX
    annual_charter = CHARTER_RATE_USD_PER_YEAR * n_ships  # USD/year
    annual_liq_opex = liq_cost * flow_mtpa * 1e6  # EUR/year (converted from per-tonne)

    items = [
        CostItem(
            id="SHIP-CAPEX",
            name="CO2 carrier vessel fleet",
            category="ship_transport",
            subcategory="vessel_capex",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PIPELINE,  # Reuse transport category
            amount_base_year=total_ship_capex * 1e6,  # Convert M USD to USD
            base_year=base_year,
            currency=currency,
            begin_year=construction_year,
            end_year=construction_year,
            recurrence="one-time",
            quantity=1.0,
            notes=f"{n_ships} x {pressure.value} vessels @ {ship_capacity_tonnes}t capacity",
        ),
        CostItem(
            id="SHIP-LIQ-CAPEX",
            name="Liquefaction terminal",
            category="ship_transport",
            subcategory="liquefaction_capex",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PIPELINE,
            amount_base_year=liq_capex * 1e6,  # Convert M USD to USD
            base_year=base_year,
            currency=currency,
            begin_year=construction_year,
            end_year=construction_year,
            recurrence="one-time",
            quantity=1.0,
            notes="Liquefaction terminal (approx 50% of fleet CAPEX)",
        ),
        CostItem(
            id="SHIP-CHARTER-OPEX",
            name="Vessel charter and operating costs",
            category="ship_transport",
            subcategory="vessel_opex",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=annual_charter,
            base_year=base_year,
            currency=currency,
            begin_year=operations_begin,
            end_year=operations_end,
            recurrence="annual",
            quantity=1.0,
            notes=f"Charter rate ${CHARTER_RATE_USD_PER_YEAR/1e6:.1f}M/vessel/yr x {n_ships} vessels",
        ),
        CostItem(
            id="SHIP-LIQ-OPEX",
            name="Liquefaction operating costs",
            category="ship_transport",
            subcategory="liquefaction_opex",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=annual_liq_opex,
            base_year=base_year,
            currency="EUR",
            begin_year=operations_begin,
            end_year=operations_end,
            recurrence="annual",
            quantity=1.0,
            notes=f"Liquefaction @ {liq_cost:.2f} EUR/t x {flow_mtpa} Mtpa",
        ),
    ]

    return ShipTransportCosts(
        ship_capex_musd=total_ship_capex,
        ship_pressure=pressure.value,
        ship_capacity_tonnes=ship_capacity_tonnes,
        n_vessels=n_ships,
        liquefaction_eur_per_t=liq_cost,
        transport_eur_per_t=transport_cost,
        total_eur_per_t=total_per_t,
        charter_rate_usd_per_year=CHARTER_RATE_USD_PER_YEAR,
        base_year=base_year,
        currency=currency,
        items=items,
    )

"""Geological engine: formation database, storage coefficients, and reservoir calculations.

Public API:
    Formations:
        - FormationProperties: Pydantic model for geological formation data
        - load_formations: Load all formations for a region
        - get_formation: Look up a single formation by ID
        - search_formations: Filter formations by property ranges

    Storage coefficients:
        - storage_coefficient: IEA GHG 2009/12 storage efficiency lookup
        - StorageCoefficientMethod: Enum for lookup vs user-specified
        - get_coefficient_for_formation: Convenience wrapper

    Plume areas:
        - plume_area: CO2 plume area from mass, storage coefficient, reservoir properties
        - uncertainty_area: Expanded plume envelope (plume * multiplier)
        - pressure_front_area: Pressure front / AoR (uncertainty * multiplier)
        - plume_areas: Convenience returning all three

    Injectivity:
        - InjectionMethod: Enum for Valluri / Zhou / user-specified
        - max_injection_rate_valluri: Valluri et al. two-phase radial flow
        - max_injection_rate_zhou: Simplified Zhou single-phase flow
        - estimate_fracture_pressure: Fracture pressure from depth
        - required_injection_wells: Well count from target rate
        - max_wells_from_capacity: Storage capacity constraint on well count
        - monitoring_well_count: Monitoring wells from injection well count
        - compute_injection_rate: Dispatcher for any method

    Schedule:
        - ProjectTimeline: Configuration for schedule stage durations
        - WellPlan: Well plan (injection, monitoring, strat test, water prod)
        - AnnualSchedule: Single year in project schedule
        - ProjectSchedule: Complete project schedule with timeline
        - build_schedule: Build year-by-year project schedule
"""

from ccs_costs.geo.formations import (
    FormationProperties,
    get_formation,
    load_formations,
    search_formations,
)
from ccs_costs.geo.injectivity import (
    InjectionMethod,
    compute_injection_rate,
    estimate_fracture_pressure,
    max_injection_rate_valluri,
    max_injection_rate_zhou,
    max_wells_from_capacity,
    monitoring_well_count,
    required_injection_wells,
)
from ccs_costs.geo.plume import (
    plume_area,
    plume_areas,
    pressure_front_area,
    uncertainty_area,
)
from ccs_costs.geo.schedule import (
    AnnualSchedule,
    ProjectSchedule,
    ProjectTimeline,
    WellPlan,
    build_schedule,
)
from ccs_costs.geo.storage import (
    StorageCoefficientMethod,
    get_coefficient_for_formation,
    storage_coefficient,
)

__all__ = [
    # Formations
    "FormationProperties",
    "get_formation",
    "load_formations",
    "search_formations",
    # Storage coefficients
    "StorageCoefficientMethod",
    "get_coefficient_for_formation",
    "storage_coefficient",
    # Plume areas
    "plume_area",
    "plume_areas",
    "pressure_front_area",
    "uncertainty_area",
    # Injectivity
    "InjectionMethod",
    "compute_injection_rate",
    "estimate_fracture_pressure",
    "max_injection_rate_valluri",
    "max_injection_rate_zhou",
    "max_wells_from_capacity",
    "monitoring_well_count",
    "required_injection_wells",
    # Schedule
    "AnnualSchedule",
    "ProjectSchedule",
    "ProjectTimeline",
    "WellPlan",
    "build_schedule",
]

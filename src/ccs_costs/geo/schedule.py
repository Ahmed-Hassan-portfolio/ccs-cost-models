"""Project schedule generator with year-by-year plume tracking.

Builds an 85-year (configurable) project schedule mapping to NETL's
Plume&Well Schedule sheet. The schedule tracks:
    - Project stages: screening, characterization, permitting, construction,
      operations, PISC (post-injection site care)
    - Well drilling during construction/early operations
    - Annual CO2 injection during operations
    - Plume area growth during operations, stabilization during PISC
    - Seismic survey area requirements

The schedule is the bridge between geological calculations and cost
calculations -- it determines when wells are drilled, when plume
monitoring areas expand, and when each cost item occurs.

NETL reference (default scenario):
    85-year timeline: 1 screening + 2 characterization + 2 permitting
    + 0 explicit construction + 30 operations + 50 PISC
    (Construction is modeled as overlapping with early operations
    for well drilling purposes.)
"""

from __future__ import annotations

import math
import warnings
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, computed_field

from ccs_costs.geo.plume import plume_area, pressure_front_area, uncertainty_area

if TYPE_CHECKING:
    from ccs_costs.geo.formations import FormationProperties


class ProjectTimeline(BaseModel):
    """Configuration for project schedule stage durations.

    All durations are in years. Configurable per region.

    NETL US defaults:
        screening=1, characterization=2, permitting=2, construction=3,
        pisc=50 (US regulatory)

    Norwegian overrides:
        pisc=20 (shorter regulatory requirement)
    """

    screening_years: int = 1
    characterization_years: int = 2
    permitting_years: int = 2
    construction_years: int = 3
    operations_years: int | None = None  # None = calculate from total/rate
    pisc_years: int = 50  # US default; Norway = 20
    pisc_minimum_years: int = 50  # Regulatory minimum for warning
    drilling_rate_wells_per_year: int = 2
    start_year: int = 2024
    operations_mode: str = "target"  # "target" or "duration"

    def validate_pisc(self) -> None:
        """Warn (not error) if PISC is shorter than regulatory minimum."""
        if self.pisc_years < self.pisc_minimum_years:
            warnings.warn(
                f"PISC duration ({self.pisc_years} years) is less than "
                f"regulatory minimum ({self.pisc_minimum_years} years). "
                f"This may not satisfy regulatory requirements.",
                UserWarning,
                stacklevel=2,
            )


class WellPlan(BaseModel):
    """Complete well plan for a storage project.

    Tracks all well types needed for the project.
    """

    n_injection: int
    n_monitoring: int
    n_stratigraphic_test: int = 1
    n_water_production: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_wells(self) -> int:
        """Total number of wells across all types."""
        return (
            self.n_injection
            + self.n_monitoring
            + self.n_stratigraphic_test
            + self.n_water_production
        )


class AnnualSchedule(BaseModel):
    """Single year in the project schedule.

    Tracks CO2 injection, plume growth, well drilling, and monitoring
    area requirements for a single calendar year.
    """

    year: int  # Calendar year
    project_year: int  # 1-based project year
    stage: str  # screening, characterization, permitting, construction, operations, pisc
    wells_drilled: int = 0
    cumulative_wells: int = 0
    co2_injected_tonnes: float = 0.0
    cumulative_co2_tonnes: float = 0.0
    plume_area_km2: float = 0.0
    uncertainty_area_km2: float = 0.0
    pressure_front_area_km2: float = 0.0
    seismic_area_needed_km2: float = 0.0


class ProjectSchedule(BaseModel):
    """Complete project schedule with well plan and year-by-year timeline."""

    well_plan: WellPlan
    timeline: list[AnnualSchedule]

    @property
    def operations_years(self) -> int:
        """Number of operations years in the schedule."""
        return len([y for y in self.timeline if y.stage == "operations"])

    @property
    def total_co2_tonnes(self) -> float:
        """Total CO2 injected across all years."""
        return sum(y.co2_injected_tonnes for y in self.timeline)

    @property
    def total_years(self) -> int:
        """Total number of years in the schedule."""
        return len(self.timeline)


def build_schedule(
    formation: FormationProperties,
    co2_density_kgm3: float,
    storage_coefficient: float,
    well_plan: WellPlan,
    injection_rate_tpa: float,
    timeline: ProjectTimeline,
    total_co2_tonnes: float = 120e6,
    uncertainty_multiplier: float = 1.25,
    aor_multiplier: float = 5.0,
) -> ProjectSchedule:
    """Build complete project schedule with year-by-year plume tracking.

    The schedule maps to NETL's Plume&Well Schedule sheet and produces
    the timeline consumed by cost modules.

    Args:
        formation: FormationProperties for the storage formation.
        co2_density_kgm3: CO2 density at reservoir conditions (kg/m3).
        storage_coefficient: IEA GHG storage efficiency factor.
        well_plan: WellPlan with injection, monitoring, and test well counts.
        injection_rate_tpa: Annual CO2 injection rate (tonnes/year).
        timeline: ProjectTimeline configuration.
        total_co2_tonnes: Total CO2 to inject over project lifetime (tonnes).
        uncertainty_multiplier: Plume uncertainty multiplier (default 1.25).
        aor_multiplier: Pressure front / AoR multiplier (default 5.0).

    Returns:
        ProjectSchedule with complete year-by-year timeline.
    """
    # Determine operations years
    if timeline.operations_mode == "duration" and timeline.operations_years is not None:
        ops_years = timeline.operations_years
        # In duration mode, annual rate = total / ops_years
        annual_rate = total_co2_tonnes / ops_years
    else:
        # Target mode: ops_years = total / annual rate
        ops_years = math.ceil(total_co2_tonnes / injection_rate_tpa)
        annual_rate = injection_rate_tpa

    # Build stage plan
    stages: list[tuple[str, int]] = [
        ("screening", timeline.screening_years),
        ("characterization", timeline.characterization_years),
        ("permitting", timeline.permitting_years),
        ("construction", timeline.construction_years),
        ("operations", ops_years),
        ("pisc", timeline.pisc_years),
    ]

    # Plan well drilling schedule
    # Strat test well: first year of characterization
    # Injection + monitoring wells: during construction at drilling_rate
    # If not all drilled during construction, continue into early operations
    wells_to_drill = _plan_well_drilling(well_plan, timeline, stages)

    # Build year-by-year timeline
    schedule: list[AnnualSchedule] = []
    project_year = 0
    cumulative_co2 = 0.0
    cumulative_wells = 0
    final_plume_km2 = 0.0
    final_uncertainty_km2 = 0.0
    final_pressure_front_km2 = 0.0

    for stage_name, stage_duration in stages:
        for year_in_stage in range(stage_duration):
            project_year += 1
            calendar_year = timeline.start_year + project_year - 1

            # Wells drilled this year
            drilled = wells_to_drill.get(project_year, 0)
            cumulative_wells += drilled

            # CO2 injection (only during operations)
            co2_this_year = 0.0
            if stage_name == "operations":
                # Last year may inject less to hit exact total
                remaining = total_co2_tonnes - cumulative_co2
                co2_this_year = min(annual_rate, remaining)
                cumulative_co2 += co2_this_year

            # Plume area calculations
            pa_km2 = 0.0
            ua_km2 = 0.0
            pf_km2 = 0.0

            if cumulative_co2 > 0:
                pa_km2 = plume_area(
                    cumulative_co2,
                    storage_coefficient,
                    formation.thickness_m,
                    formation.porosity,
                    co2_density_kgm3,
                )
                ua_km2 = uncertainty_area(pa_km2, uncertainty_multiplier)
                pf_km2 = pressure_front_area(ua_km2, aor_multiplier)

            if stage_name == "operations":
                final_plume_km2 = pa_km2
                final_uncertainty_km2 = ua_km2
                final_pressure_front_km2 = pf_km2

            # During PISC, plume stabilizes at final operations value
            if stage_name == "pisc":
                pa_km2 = final_plume_km2
                ua_km2 = final_uncertainty_km2
                pf_km2 = final_pressure_front_km2

            # Seismic area: uncertainty during ops, pressure front during PISC
            if stage_name == "operations":
                seismic_km2 = ua_km2
            elif stage_name == "pisc":
                seismic_km2 = pf_km2
            else:
                seismic_km2 = 0.0

            schedule.append(
                AnnualSchedule(
                    year=calendar_year,
                    project_year=project_year,
                    stage=stage_name,
                    wells_drilled=drilled,
                    cumulative_wells=cumulative_wells,
                    co2_injected_tonnes=co2_this_year,
                    cumulative_co2_tonnes=cumulative_co2,
                    plume_area_km2=pa_km2,
                    uncertainty_area_km2=ua_km2,
                    pressure_front_area_km2=pf_km2,
                    seismic_area_needed_km2=seismic_km2,
                )
            )

    return ProjectSchedule(well_plan=well_plan, timeline=schedule)


def _plan_well_drilling(
    well_plan: WellPlan,
    timeline: ProjectTimeline,
    stages: list[tuple[str, int]],
) -> dict[int, int]:
    """Plan which project year each well is drilled.

    Returns dict mapping project_year -> wells_drilled_that_year.

    Drilling schedule:
        - 1 stratigraphic test well: first year of characterization
        - Injection + monitoring wells: starting in construction at
          drilling_rate_wells_per_year, continuing into operations if needed
    """
    wells_by_year: dict[int, int] = {}
    rate = timeline.drilling_rate_wells_per_year

    # Find the project year where each stage starts
    stage_start: dict[str, int] = {}
    py = 1
    for stage_name, duration in stages:
        stage_start[stage_name] = py
        py += duration

    # Strat test wells: drill in first year of characterization
    char_start = stage_start.get("characterization", 2)
    remaining_strat = well_plan.n_stratigraphic_test
    drill_year = char_start
    while remaining_strat > 0:
        to_drill = min(remaining_strat, rate)
        wells_by_year[drill_year] = wells_by_year.get(drill_year, 0) + to_drill
        remaining_strat -= to_drill
        drill_year += 1

    # Injection + monitoring + water production wells: drill during construction
    injection_monitoring = (
        well_plan.n_injection
        + well_plan.n_monitoring
        + well_plan.n_water_production
    )
    construction_start = stage_start.get("construction", 6)
    remaining = injection_monitoring
    drill_year = construction_start

    while remaining > 0:
        to_drill = min(remaining, rate)
        wells_by_year[drill_year] = wells_by_year.get(drill_year, 0) + to_drill
        remaining -= to_drill
        drill_year += 1

    return wells_by_year

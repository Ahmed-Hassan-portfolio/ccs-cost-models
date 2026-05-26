"""Injection rate calculations and well count determination.

Implements three injection rate methods:
    1. Valluri et al. (Method 7) -- default, vertical wells, two-phase radial flow
    2. Simplified Zhou et al. (Method 1) -- single-phase radial flow
    3. User-specified rate (Method 8) -- direct input bypass

The Valluri method uses steady-state radial Darcy flow with CO2 viscosity
in the Darcy denominator. NETL uses CO2 viscosity (single-phase Darcy;
far-field brine not rate-limiting at this scale). This matches the NETL
model's Valluri implementation (Method 7).

Fracture pressure estimation uses a minimum-gradient approach calibrated
to the NETL "min calculated frac pressure" (approach 2).

References:
    Valluri, M.K., S. Mukherjee, R. Mishra, and A. Gilmore (2021).
    "An improved understanding of CO2 injectivity," International Journal
    of Greenhouse Gas Control, Vol. 112.

    Zhou, Q., J.T. Birkholzer, C.F. Tsang, and J. Rutqvist (2008).
    "A method for quick assessment of CO2 storage capacity in closed and
    semi-closed saline formations," International Journal of Greenhouse
    Gas Control, Vol. 2, Issue 4, pp. 626-639.
"""

from __future__ import annotations

import math
from enum import Enum


class InjectionMethod(str, Enum):
    """Available injection rate calculation methods."""

    VALLURI = "valluri"
    ZHOU_SIMPLIFIED = "zhou_simplified"
    USER_SPECIFIED = "user_specified"


# ============================================================================
# Default constants
# ============================================================================

# Default well geometry
_DEFAULT_WELL_RADIUS_M = 0.1  # ~4 inch wellbore radius
_DEFAULT_DRAINAGE_RADIUS_M = 10000  # 10 km drainage radius

# Default maximum injection rate per well (NETL default: 3660 t/day)
_DEFAULT_MAX_RATE_PER_WELL_TPD = 3660.0

# Fracture pressure gradient (minimum gradient approach)
# Calibrated to NETL "min calculated frac pressure" (approach 2)
# Approximately 0.72 psi/ft -- standard minimum fracture gradient for
# sedimentary basins. The effective gradient depends on depth, overburden,
# and pore pressure, but this default produces NETL-consistent results
# (5 injection wells for Formation 1 at 4 Mt/yr, 0.85 capacity factor).
_DEFAULT_FRAC_GRADIENT_MPA_PER_M = 0.01638

# Overburden/lithostatic gradient (standard value for sedimentary rocks)
_LITHOSTATIC_GRADIENT_MPA_PER_M = 0.0226


# ============================================================================
# Fracture pressure estimation
# ============================================================================


def estimate_fracture_pressure(
    depth_m: float,
    method: str = "min_gradient",
    frac_gradient_mpa_per_m: float = _DEFAULT_FRAC_GRADIENT_MPA_PER_M,
) -> float:
    """Estimate fracture pressure from depth.

    Provides conservative fracture pressure estimate for injection well
    design. The default method uses a minimum gradient approach calibrated
    to produce NETL-consistent results.

    Args:
        depth_m: Formation depth in metres (must be > 0).
        method: Estimation method. Currently supports:
            - "min_gradient": P_frac = gradient * depth (default)
        frac_gradient_mpa_per_m: Fracture gradient in MPa/m (default
            0.01632, equivalent to ~0.72 psi/ft).

    Returns:
        Estimated fracture pressure in MPa.

    Raises:
        ValueError: If depth_m <= 0.
    """
    if depth_m <= 0:
        raise ValueError(
            f"depth_m must be positive, got {depth_m}. "
            f"Fracture pressure requires a valid formation depth."
        )

    if method == "min_gradient":
        return frac_gradient_mpa_per_m * depth_m
    else:
        raise ValueError(f"Unknown fracture pressure method: '{method}'")


# ============================================================================
# Valluri et al. injection rate (Method 7)
# ============================================================================


def max_injection_rate_valluri(
    permeability_md: float,
    thickness_m: float,
    co2_viscosity_pas: float,
    brine_viscosity_pas: float,
    co2_density_kgm3: float,
    brine_density_kgm3: float,
    reservoir_pressure_mpa: float,
    fracture_pressure_mpa: float,
    well_radius_m: float = _DEFAULT_WELL_RADIUS_M,
    drainage_radius_m: float = _DEFAULT_DRAINAGE_RADIUS_M,
    max_rate_per_well_tpd: float = _DEFAULT_MAX_RATE_PER_WELL_TPD,
) -> float:
    """Calculate maximum CO2 injection rate per well via Valluri et al. method.

    Uses steady-state radial Darcy flow for CO2 injection into a brine-
    saturated formation. CO2 viscosity is used in the Darcy denominator --
    NETL uses CO2 viscosity (single-phase Darcy; far-field brine not
    rate-limiting at this scale). This matches the NETL model's Valluri
    implementation (Method 7).

    The injection pressure is constrained by the fracture pressure: the
    available pressure differential is (fracture_pressure - reservoir_pressure).

    Args:
        permeability_md: Formation permeability in millidarcies.
        thickness_m: Formation thickness in metres (gross or net, depending
            on context).
        co2_viscosity_pas: CO2 viscosity at reservoir conditions (Pa-s).
            Used in Darcy denominator -- NETL uses CO2 viscosity for single-
            phase flow at formation scale.
        brine_viscosity_pas: Brine viscosity at reservoir conditions (Pa-s).
            Included for API consistency and future mobility ratio corrections.
        co2_density_kgm3: CO2 density at reservoir conditions (kg/m3).
            Used to convert volumetric to mass flow rate.
        brine_density_kgm3: Brine density at reservoir conditions (kg/m3).
            Included for API consistency and future mobility ratio corrections.
        reservoir_pressure_mpa: Reservoir pressure in MPa.
        fracture_pressure_mpa: Maximum allowable injection pressure (MPa).
        well_radius_m: Wellbore radius in metres (default 0.1 m).
        drainage_radius_m: Drainage radius in metres (default 10000 m).
        max_rate_per_well_tpd: Maximum rate cap in tonnes/day (default 3660).

    Returns:
        Maximum injection rate in tonnes/day per well. Returns 0 if
        fracture_pressure <= reservoir_pressure (no available delta-P).
    """
    # Available pressure differential
    delta_p_mpa = fracture_pressure_mpa - reservoir_pressure_mpa
    if delta_p_mpa <= 0:
        return 0.0

    # Convert units
    k_m2 = permeability_md * 9.869233e-16  # mD to m2
    delta_p_pa = delta_p_mpa * 1e6  # MPa to Pa

    # Radial Darcy flow: Q_vol = (2 * pi * k * h * dP) / (mu_eff * ln(re/rw))
    # NETL uses CO2 viscosity (single-phase Darcy; far-field brine not rate-limiting at this scale)
    ln_ratio = math.log(drainage_radius_m / well_radius_m)
    q_vol_m3_s = (2 * math.pi * k_m2 * thickness_m * delta_p_pa) / (
        co2_viscosity_pas * ln_ratio
    )

    # Convert volumetric to mass flow rate
    q_mass_kg_s = q_vol_m3_s * co2_density_kgm3
    q_tonnes_day = q_mass_kg_s * 86400 / 1000

    # Cap at maximum rate per well
    return min(q_tonnes_day, max_rate_per_well_tpd)


# ============================================================================
# Simplified Zhou et al. injection rate (Method 1)
# ============================================================================


def max_injection_rate_zhou(
    permeability_md: float,
    thickness_m: float,
    co2_viscosity_pas: float,
    reservoir_pressure_mpa: float,
    fracture_pressure_mpa: float,
    co2_density_kgm3: float,
    well_radius_m: float = _DEFAULT_WELL_RADIUS_M,
    drainage_radius_m: float = _DEFAULT_DRAINAGE_RADIUS_M,
    max_rate_per_well_tpd: float = _DEFAULT_MAX_RATE_PER_WELL_TPD,
) -> float:
    """Calculate maximum CO2 injection rate per well via simplified Zhou method.

    Simplified single-phase radial Darcy flow using CO2 viscosity only.
    This gives the upper-bound injection rate (no brine displacement resistance).
    Generally produces higher rates than Valluri.

    Args:
        permeability_md: Formation permeability in millidarcies.
        thickness_m: Formation thickness in metres.
        co2_viscosity_pas: CO2 viscosity at reservoir conditions (Pa-s).
        reservoir_pressure_mpa: Reservoir pressure in MPa.
        fracture_pressure_mpa: Maximum allowable injection pressure (MPa).
        co2_density_kgm3: CO2 density at reservoir conditions (kg/m3).
        well_radius_m: Wellbore radius in metres (default 0.1 m).
        drainage_radius_m: Drainage radius in metres (default 10000 m).
        max_rate_per_well_tpd: Maximum rate cap in tonnes/day (default 3660).

    Returns:
        Maximum injection rate in tonnes/day per well. Returns 0 if
        fracture_pressure <= reservoir_pressure.
    """
    delta_p_mpa = fracture_pressure_mpa - reservoir_pressure_mpa
    if delta_p_mpa <= 0:
        return 0.0

    k_m2 = permeability_md * 9.869233e-16
    delta_p_pa = delta_p_mpa * 1e6

    ln_ratio = math.log(drainage_radius_m / well_radius_m)
    q_vol_m3_s = (2 * math.pi * k_m2 * thickness_m * delta_p_pa) / (
        co2_viscosity_pas * ln_ratio
    )

    q_mass_kg_s = q_vol_m3_s * co2_density_kgm3
    q_tonnes_day = q_mass_kg_s * 86400 / 1000

    return min(q_tonnes_day, max_rate_per_well_tpd)


# ============================================================================
# Well count calculation
# ============================================================================


def max_wells_from_capacity(
    capacity_mt: float | None,
    injection_rate_tpa: float,
    operations_years: int,
    max_rate_per_well_tpd: float,
    capacity_factor: float = 0.85,
) -> int | None:
    """Maximum wells supportable by formation storage capacity.

    If total planned injection exceeds capacity, reduce well count so
    that total injection equals capacity. If capacity is None or sufficient,
    returns None (no constraint).

    This prevents small-capacity formations from being over-drilled.
    Only activates when capacity_mt is available (e.g., NCS formations
    from CO2 Storage Atlas). GOA formations without capacity_mt are
    unaffected (backward compatible).

    Args:
        capacity_mt: Total formation CO2 storage capacity in Mt.
            None means no capacity data available (no constraint).
        injection_rate_tpa: Target annual injection rate (tonnes/year).
        operations_years: Number of years of injection operations.
        max_rate_per_well_tpd: Maximum rate per well (tonnes/day).
        capacity_factor: Operating efficiency factor (default 0.85).

    Returns:
        Max number of total wells (active + spare), or None if
        unconstrained (capacity sufficient or unknown).
    """
    if capacity_mt is None or capacity_mt <= 0:
        return None

    # Total CO2 to inject over project lifetime
    total_co2_t = injection_rate_tpa * operations_years

    if total_co2_t <= capacity_mt * 1e6:
        # Capacity sufficient for target injection -- no constraint
        return None

    # Capacity constrains: reduce effective injection rate to fit capacity
    effective_rate_tpa = capacity_mt * 1e6 / operations_years
    effective_rate_tpd = effective_rate_tpa / (365.25 * capacity_factor)
    n_active = max(1, math.ceil(effective_rate_tpd / max_rate_per_well_tpd))
    return n_active + 1  # + 1 spare


def required_injection_wells(
    target_rate_tpa: float,
    max_rate_per_well_tpd: float,
    capacity_factor: float = 0.85,
) -> int:
    """Calculate number of injection wells needed.

    Args:
        target_rate_tpa: Target annual injection rate in tonnes/year.
        max_rate_per_well_tpd: Maximum injection rate per well (tonnes/day).
            If 0 (e.g., overpressured formation where fracture pressure <=
            reservoir pressure), raises ValueError.
        capacity_factor: Operating efficiency factor (default 0.85 per NETL).
            Accounts for planned and unplanned downtime.

    Returns:
        Number of injection wells (always >= 1, rounded up).

    Raises:
        ValueError: If max_rate_per_well_tpd <= 0 (injection not feasible).
    """
    if max_rate_per_well_tpd <= 0:
        raise ValueError(
            f"max_rate_per_well_tpd must be positive, got {max_rate_per_well_tpd}. "
            f"This may indicate an overpressured formation where fracture pressure "
            f"<= reservoir pressure, making injection infeasible."
        )
    daily_target = target_rate_tpa / 365.25
    effective_rate = max_rate_per_well_tpd * capacity_factor
    return math.ceil(daily_target / effective_rate)


# ============================================================================
# Convenience dispatcher
# ============================================================================


def compute_injection_rate(
    method: InjectionMethod = InjectionMethod.VALLURI,
    *,
    # Formation properties (required for VALLURI and ZHOU)
    permeability_md: float | None = None,
    thickness_m: float | None = None,
    reservoir_pressure_mpa: float | None = None,
    fracture_pressure_mpa: float | None = None,
    # CO2/brine properties (required for VALLURI and ZHOU)
    co2_viscosity_pas: float | None = None,
    brine_viscosity_pas: float | None = None,
    co2_density_kgm3: float | None = None,
    brine_density_kgm3: float | None = None,
    # Well geometry
    well_radius_m: float = _DEFAULT_WELL_RADIUS_M,
    drainage_radius_m: float = _DEFAULT_DRAINAGE_RADIUS_M,
    max_rate_per_well_tpd: float = _DEFAULT_MAX_RATE_PER_WELL_TPD,
    # User-specified
    user_rate_tpd: float | None = None,
) -> float:
    """Dispatch to the appropriate injection rate method.

    Convenience function that routes to Valluri, Zhou, or user-specified
    method based on the `method` parameter.

    Args:
        method: InjectionMethod enum value.
        permeability_md: Formation permeability (mD).
        thickness_m: Formation thickness (m).
        reservoir_pressure_mpa: Reservoir pressure (MPa).
        fracture_pressure_mpa: Fracture pressure (MPa).
        co2_viscosity_pas: CO2 viscosity (Pa-s).
        brine_viscosity_pas: Brine viscosity (Pa-s).
        co2_density_kgm3: CO2 density (kg/m3).
        brine_density_kgm3: Brine density (kg/m3).
        well_radius_m: Well radius (m).
        drainage_radius_m: Drainage radius (m).
        max_rate_per_well_tpd: Max rate cap (t/day).
        user_rate_tpd: User-specified rate (t/day), required for USER_SPECIFIED.

    Returns:
        Maximum injection rate per well in tonnes/day.
    """
    if method == InjectionMethod.USER_SPECIFIED:
        if user_rate_tpd is None:
            raise ValueError(
                "user_rate_tpd must be provided when method is USER_SPECIFIED. "
                "Pass a float value for the per-well injection rate in tonnes/day."
            )
        return user_rate_tpd

    if method == InjectionMethod.VALLURI:
        assert permeability_md is not None
        assert thickness_m is not None
        assert co2_viscosity_pas is not None
        assert brine_viscosity_pas is not None
        assert co2_density_kgm3 is not None
        assert brine_density_kgm3 is not None
        assert reservoir_pressure_mpa is not None
        assert fracture_pressure_mpa is not None
        return max_injection_rate_valluri(
            permeability_md=permeability_md,
            thickness_m=thickness_m,
            co2_viscosity_pas=co2_viscosity_pas,
            brine_viscosity_pas=brine_viscosity_pas,
            co2_density_kgm3=co2_density_kgm3,
            brine_density_kgm3=brine_density_kgm3,
            reservoir_pressure_mpa=reservoir_pressure_mpa,
            fracture_pressure_mpa=fracture_pressure_mpa,
            well_radius_m=well_radius_m,
            drainage_radius_m=drainage_radius_m,
            max_rate_per_well_tpd=max_rate_per_well_tpd,
        )

    if method == InjectionMethod.ZHOU_SIMPLIFIED:
        assert permeability_md is not None
        assert thickness_m is not None
        assert co2_viscosity_pas is not None
        assert reservoir_pressure_mpa is not None
        assert fracture_pressure_mpa is not None
        assert co2_density_kgm3 is not None
        return max_injection_rate_zhou(
            permeability_md=permeability_md,
            thickness_m=thickness_m,
            co2_viscosity_pas=co2_viscosity_pas,
            reservoir_pressure_mpa=reservoir_pressure_mpa,
            fracture_pressure_mpa=fracture_pressure_mpa,
            co2_density_kgm3=co2_density_kgm3,
            well_radius_m=well_radius_m,
            drainage_radius_m=drainage_radius_m,
            max_rate_per_well_tpd=max_rate_per_well_tpd,
        )

    raise ValueError(f"Unknown injection method: {method}")


# ============================================================================
# Monitoring well count
# ============================================================================


def monitoring_well_count(
    n_injection_wells: int,
    n_reservoir_per_satellite: int = 2,
    n_above_seal_per_satellite: int = 2,
) -> int:
    """Calculate number of monitoring wells based on injection wells.

    NETL uses a satellite-based monitoring well pattern:
    each injection well gets its own set of monitoring wells (in-reservoir
    and above-seal). An additional primary monitoring station also gets
    the same monitoring well complement.

    Total = (n_injection + 1) * (n_reservoir + n_above_seal)

    For NETL defaults (5 injection wells): (5+1) * (2+2) = 24 monitoring wells.

    Args:
        n_injection_wells: Number of injection wells.
        n_reservoir_per_satellite: In-reservoir monitoring wells per
            satellite (default 2).
        n_above_seal_per_satellite: Above-seal monitoring wells per
            satellite (default 2).

    Returns:
        Total number of monitoring wells.
    """
    wells_per_satellite = n_reservoir_per_satellite + n_above_seal_per_satellite
    # One satellite per injection well, plus one primary monitoring station
    n_stations = n_injection_wells + 1
    return n_stations * wells_per_satellite

"""Plume area, uncertainty area, and pressure front (AoR) calculations.

Core equation:
    A_plume = m_CO2 / (E * h * phi * rho_CO2)

Where:
    m_CO2   = total CO2 mass injected (kg) = tonnes * 1000
    E       = storage efficiency coefficient (dimensionless)
    h       = formation thickness (m) -- gross thickness when using NETL "Gross
              Thickness" setting (default), since E already incorporates net-to-gross
              per IEA GHG methodology
    phi     = porosity (fraction)
    rho_CO2 = CO2 density at reservoir P,T (kg/m3) from thermo/co2.py

Result is in m2, converted to km2 by dividing by 1e6.

Multipliers:
    uncertainty_area = plume_area * uncertainty_multiplier (default 1.25)
    pressure_front   = uncertainty_area * aor_multiplier   (default 5.0)

Reference:
    NETL CO2_S_COM Offshore v1.1, Geol Sal sheet
    IEA GHG 2009/12 storage coefficient methodology
"""

from __future__ import annotations


def plume_area(
    total_co2_tonnes: float,
    storage_coefficient: float,
    thickness_m: float,
    porosity: float,
    co2_density_kgm3: float,
) -> float:
    """Calculate CO2 plume area in km2.

    Args:
        total_co2_tonnes: Total CO2 mass to inject (tonnes).
        storage_coefficient: IEA GHG storage efficiency factor (dimensionless,
            typically 0.01-0.25). Already incorporates net-to-gross.
        thickness_m: Formation thickness in metres. Pass gross thickness when
            using NETL "Gross Thickness" setting (default), or net thickness
            otherwise.
        porosity: Formation porosity (fraction, 0-1).
        co2_density_kgm3: CO2 density at reservoir P,T in kg/m3.

    Returns:
        Plume area in km2.

    Raises:
        ValueError: If any input is zero or negative.
    """
    _validate_positive("total_co2_tonnes", total_co2_tonnes)
    _validate_positive("storage_coefficient", storage_coefficient)
    _validate_positive("thickness_m", thickness_m)
    _validate_positive("porosity", porosity)
    _validate_positive("co2_density_kgm3", co2_density_kgm3)

    # Convert tonnes to kg
    mass_kg = total_co2_tonnes * 1000.0

    # Pore volume available (m3) = E * h * phi * rho_CO2 gives kg/m2
    # A_plume (m2) = mass_kg / (E * h * phi * rho_CO2)
    area_m2 = mass_kg / (storage_coefficient * thickness_m * porosity * co2_density_kgm3)

    # Convert m2 to km2
    return area_m2 / 1e6


def uncertainty_area(
    plume_area_km2: float,
    uncertainty_multiplier: float = 1.25,
) -> float:
    """Calculate uncertainty area (expanded plume envelope).

    The uncertainty multiplier accounts for plume migration uncertainty
    and caprock topography effects.

    Args:
        plume_area_km2: Plume area in km2.
        uncertainty_multiplier: Multiplier applied to plume area (default 1.25,
            per NETL).

    Returns:
        Uncertainty area in km2.
    """
    return plume_area_km2 * uncertainty_multiplier


def pressure_front_area(
    uncertainty_area_km2: float,
    aor_multiplier: float = 5.0,
) -> float:
    """Calculate pressure front / Area of Review (AoR).

    The AoR multiplier accounts for the pressure perturbation extending
    well beyond the CO2 plume itself.

    Args:
        uncertainty_area_km2: Uncertainty area in km2.
        aor_multiplier: Multiplier applied to uncertainty area (default 5.0,
            per NETL).

    Returns:
        Pressure front (AoR) area in km2.
    """
    return uncertainty_area_km2 * aor_multiplier


def plume_areas(
    total_co2_tonnes: float,
    storage_coefficient: float,
    thickness_m: float,
    porosity: float,
    co2_density_kgm3: float,
    uncertainty_multiplier: float = 1.25,
    aor_multiplier: float = 5.0,
) -> tuple[float, float, float]:
    """Convenience function returning all three plume-related areas.

    Args:
        total_co2_tonnes: Total CO2 mass to inject (tonnes).
        storage_coefficient: IEA GHG storage efficiency factor.
        thickness_m: Formation thickness in metres.
        porosity: Formation porosity (fraction).
        co2_density_kgm3: CO2 density at reservoir P,T in kg/m3.
        uncertainty_multiplier: Plume uncertainty multiplier (default 1.25).
        aor_multiplier: Pressure front / AoR multiplier (default 5.0).

    Returns:
        Tuple of (plume_area_km2, uncertainty_area_km2, pressure_front_area_km2).
    """
    pa = plume_area(total_co2_tonnes, storage_coefficient, thickness_m, porosity, co2_density_kgm3)
    ua = uncertainty_area(pa, uncertainty_multiplier)
    pf = pressure_front_area(ua, aor_multiplier)
    return pa, ua, pf


def _validate_positive(name: str, value: float) -> None:
    """Validate that a value is strictly positive.

    Args:
        name: Parameter name for error message.
        value: Value to check.

    Raises:
        ValueError: If value <= 0.
    """
    if value <= 0:
        raise ValueError(
            f"{name} must be positive, got {value}. "
            f"All plume area inputs must be > 0."
        )

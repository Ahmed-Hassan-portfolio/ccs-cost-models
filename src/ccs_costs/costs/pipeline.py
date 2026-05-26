"""Pipeline hydraulic sizing and cost estimation.

Two sub-problems:
1. Hydraulic sizing: Determine minimum pipeline diameter from flow rate, distance,
   pressures, and CO2 properties using Darcy-Weisbach with Colebrook-White friction.
2. Cost estimation: CAPEX, OPEX, decommissioning from diameter and length using
   NETL/QUE$TOR regressions (for cross-verification) and Knoope 2014 (for Norway).

The hydraulic sizing faithfully translates the NETL VBA Dia_in_min() function
(modEng_Calcs.bas) for the incompressible liquid method (Meth=1).

References:
    NETL CO2_S_COM_Offshore v1.1 VBA: modEng_Calcs.bas
    Knoope et al. (2014) Int. J. Greenh. Gas Control, 22, 25-46
    McCoy & Rubin (2008) Int. J. Greenh. Gas Control, 2, 219-229
"""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)

# ============================================================================
# Constants
# ============================================================================

_G = 9.80665  # acceleration due to gravity (m/s2)
_PI = math.pi
_INCHES_TO_METERS = 0.0254
_METERS_TO_INCHES = 1.0 / _INCHES_TO_METERS
_MI_TO_M = 1609.344
_KM_TO_M = 1000.0
_FT_TO_M = 0.3048
_PSI_TO_PA = 6894.757
_SECONDS_PER_YEAR = 365.25 * 86400.0

# Standard pipe sizes from NETL VBA Pipe_Size function
# Mapping: max inner diameter (inches) -> nominal pipe size (inches)
_PIPE_SIZE_THRESHOLDS = [
    (4.0, 4),
    (6.0, 6),
    (8.0, 8),
    (10.0, 10),
    (12.0, 12),
    (15.162, 16),
    (18.952, 20),
    (22.742, 24),
    (28.428, 30),
    (34.114, 36),
    (39.8, 42),
    (45.5, 48),
]

# NETL offshore model only supports these sizes
_OFFSHORE_SIZES = {6, 8, 12, 16, 20}


# ============================================================================
# Hydraulic functions
# ============================================================================


def reynolds_number(
    mass_flow_kgs: float,
    viscosity_pas: float,
    diameter_m: float,
) -> float:
    """Calculate Reynolds number for pipe flow.

    Matches VBA Reyn_N: Re = 4 * qm / (pi * mu * D)

    Args:
        mass_flow_kgs: Mass flow rate in kg/s.
        viscosity_pas: Dynamic viscosity in Pa-s.
        diameter_m: Pipe inner diameter in meters.

    Returns:
        Reynolds number (dimensionless).
    """
    return 4.0 * mass_flow_kgs / (_PI * viscosity_pas * diameter_m)


def _haaland_fanning(diameter_m: float, re: float, roughness_m: float) -> float:
    """Haaland approximation for Fanning friction factor.

    Matches VBA F_Fact with FF_Eq=0 (Haaland/McCollum-Ogden variant).
    Returns Fanning friction factor = Darcy/4.

    Args:
        diameter_m: Pipe inner diameter in meters.
        re: Reynolds number.
        roughness_m: Surface roughness in meters.

    Returns:
        Fanning friction factor.
    """
    rel_rough = roughness_m / diameter_m
    calc_temp = math.log10(6.91 / re + (rel_rough / 3.7) ** 1.11)
    return 1.0 / (4.0 * (-1.8 * calc_temp) ** 2)


def colebrook_white_fanning(
    re: float,
    diameter_m: float,
    roughness_m: float,
    max_iter: int = 1000,
    tol: float = 1e-5,
) -> float:
    """Fanning friction factor via Colebrook-White equation (Newton-Raphson).

    Faithfully translates VBA FFF_Cole(). The Colebrook-White equation is
    implicit in the Darcy friction factor f_D:
        1/sqrt(f_D) = -2*log10(eps/(3.7*D) + 2.51/(Re*sqrt(f_D)))

    We solve for a = 1/sqrt(f_D) using Newton-Raphson, then return
    the Fanning friction factor = f_D / 4 = 1 / (4 * a^2).

    Args:
        re: Reynolds number.
        diameter_m: Pipe inner diameter in meters.
        roughness_m: Pipe surface roughness in meters.
        max_iter: Maximum Newton-Raphson iterations.
        tol: Convergence tolerance (fractional).

    Returns:
        Fanning friction factor (= Darcy/4).

    Raises:
        RuntimeError: If Newton-Raphson fails to converge.
    """
    rel_rough = roughness_m / diameter_m

    # Initial guess from Haaland (multiply by 4 to get Darcy, as in VBA)
    ff_darcy_init = 4.0 * _haaland_fanning(diameter_m, re, roughness_m)
    a_new = math.sqrt(1.0 / ff_darcy_init)
    a = 0.0  # Initialize for first iteration check

    for ic in range(max_iter):
        a = a_new

        # Colebrook-White residual function:
        # F(a) = a + 2*log10(eps/(3.7*D) + 2.51/(Re*a))
        func_f = a + 2.0 * math.log10(rel_rough / 3.7 + (2.51 / re) * a)

        # Derivative:
        # dF/da = 1 + (2/(ln10)) * (2.51/Re) / (eps/(3.7*D) + 2.51/(Re*a))
        # The VBA uses 2.18/Re which is 2*2.51/(Re*ln(10)) = 2*2.51/Re * 1/2.302585
        # Actually: d/da[2*log10(X)] = 2/(ln10) * (2.51/Re)/X
        # 2/ln(10) = 0.86859, 0.86859 * 2.51 = 2.1802 ~ 2.18
        dfunc_f = 1.0 + (2.18 / re) / (rel_rough / 3.7 + (2.51 / re) * a)

        a_new = a - func_f / dfunc_f

        if abs(a / a_new - 1.0) < tol:
            break
    else:
        raise RuntimeError(
            f"Colebrook-White did not converge after {max_iter} iterations "
            f"(Re={re:.0f}, D={diameter_m:.4f}m, eps={roughness_m:.2e}m)"
        )

    # Fanning friction factor = Darcy/4 = 1/(4*a^2)
    return 1.0 / (4.0 * a_new**2)


def pipeline_diameter_min(
    length_m: float,
    flow_rate_kgs: float,
    p_in_pa: float,
    p_out_pa: float,
    density_kgm3: float,
    viscosity_pas: float,
    roughness_m: float = 4.6e-5,
    elevation_change_m: float = 0.0,
    n_pump: int = 0,
) -> float:
    """Calculate minimum pipeline inner diameter using incompressible Darcy-Weisbach.

    Faithfully translates VBA Dia_in_min() for Meth=1 (incompressible liquid).

    The iterative algorithm:
    1. Guess initial diameter D = 0.5 m
    2. Compute Reynolds number Re = 4*qm/(pi*mu*D)
    3. Compute Fanning friction factor ff via Colebrook-White
    4. Compute new D = (32*ff*qm^2*L / (pi^2*rho*(dp - g*rho*dh)))^0.2
    5. Repeat until convergence (|D_old/D_new - 1| < 1e-6)

    Args:
        length_m: Total pipeline length in meters.
        flow_rate_kgs: Mass flow rate in kg/s.
        p_in_pa: Inlet pressure in Pa.
        p_out_pa: Outlet pressure in Pa.
        density_kgm3: Average CO2 density in kg/m3.
        viscosity_pas: Average CO2 viscosity in Pa-s.
        roughness_m: Pipe inner surface roughness in meters.
        elevation_change_m: Net elevation change from inlet to outlet (m).
            Positive means outlet is higher than inlet.
        n_pump: Number of booster pump stations along the pipeline.

    Returns:
        Minimum inner diameter in meters.

    Raises:
        ValueError: If pressure drop cannot overcome friction + elevation.
        RuntimeError: If iteration does not converge within 1000 steps.
    """
    # Segment calculation (VBA: Nseg = N_Pump + 1)
    n_seg = n_pump + 1
    l_seg = length_m / n_seg
    h_dif_seg = elevation_change_m / n_seg

    # Initialize diameter guess (VBA: Dia_g = 0.5, Dia_old = 0.9 * Dia_g)
    dia_g = 0.5  # m
    dia_old = 0.9 * dia_g

    max_iter = 1001  # VBA: ic > 1000
    for ic in range(max_iter):
        if ic > 0 and abs(dia_old / dia_g - 1.0) < 1e-6:
            break

        # Calculate Fanning friction factor via Colebrook-White
        re = reynolds_number(flow_rate_kgs, viscosity_pas, dia_g)
        ff = colebrook_white_fanning(re, dia_g, roughness_m)

        # Incompressible Darcy-Weisbach formula
        # D = (32*ff*qm^2*L / (pi^2*rho*((p_in - p_out) - g*rho*h_dif)))^0.2
        num = 32.0 * ff * flow_rate_kgs**2 * l_seg
        denom = (
            _PI**2
            * density_kgm3
            * ((p_in_pa - p_out_pa) - _G * density_kgm3 * h_dif_seg)
        )

        if denom <= 0:
            # VBA returns 99.9 inches (converted to meters) indicating
            # pressure drop cannot overcome friction + elevation
            return 99.9 * _INCHES_TO_METERS

        dia_liq = (num / denom) ** 0.2

        # Update diameter
        dia_old = dia_g
        dia_g = dia_liq
    else:
        raise RuntimeError(
            f"Pipeline diameter iteration did not converge after {max_iter} steps"
        )

    return dia_g


def standard_pipe_size(min_diameter_m: float) -> int:
    """Map minimum inner diameter to next standard nominal pipe size.

    Matches VBA Pipe_Size function. Returns the nominal pipe size in inches
    for the smallest standard pipe whose inner diameter exceeds min_diameter_m.

    Args:
        min_diameter_m: Minimum required inner diameter in meters.

    Returns:
        Nominal pipe size in inches (4, 6, 8, 10, 12, 16, 20, 24, 30, 36, 42, 48).
    """
    dia_inches = min_diameter_m * _METERS_TO_INCHES

    for threshold, nominal in _PIPE_SIZE_THRESHOLDS:
        if dia_inches <= threshold:
            return nominal

    # Diameter exceeds all standard sizes
    return 2000  # VBA returns 2000 for oversized


def pipeline_diameter(
    flow_rate_tpa: float,
    length_km: float,
    inlet_pressure_mpa: float,
    outlet_pressure_mpa: float,
    temperature_c: float,
    co2_density_kgm3: float,
    co2_viscosity_pas: float,
    roughness_m: float = 4.6e-5,
    elevation_change_m: float = 0.0,
) -> dict:
    """Calculate pipeline diameter for CO2 transport.

    Public API wrapping the hydraulic sizing functions. Converts from
    user-friendly units to internal SI units.

    Args:
        flow_rate_tpa: CO2 flow rate in tonnes per year.
        length_km: Pipeline length in km.
        inlet_pressure_mpa: Inlet pressure in MPa.
        outlet_pressure_mpa: Outlet pressure in MPa.
        temperature_c: CO2 temperature in Celsius.
        co2_density_kgm3: CO2 density at pipeline conditions in kg/m3.
        co2_viscosity_pas: CO2 dynamic viscosity in Pa-s.
        roughness_m: Pipe surface roughness in meters (default: 4.6e-5, commercial steel).
        elevation_change_m: Net elevation change inlet to outlet in meters.

    Returns:
        Dictionary with:
        - min_diameter_m: Minimum inner diameter (m)
        - min_diameter_inches: Minimum inner diameter (inches)
        - nominal_diameter_inches: Standard nominal pipe size (inches)
        - reynolds_number: Reynolds number at final diameter
        - friction_factor_fanning: Fanning friction factor at final diameter
    """
    # Convert units
    flow_rate_kgs = flow_rate_tpa * 1000.0 / _SECONDS_PER_YEAR
    length_m = length_km * _KM_TO_M
    p_in_pa = inlet_pressure_mpa * 1e6
    p_out_pa = outlet_pressure_mpa * 1e6

    # Calculate minimum diameter
    min_dia_m = pipeline_diameter_min(
        length_m=length_m,
        flow_rate_kgs=flow_rate_kgs,
        p_in_pa=p_in_pa,
        p_out_pa=p_out_pa,
        density_kgm3=co2_density_kgm3,
        viscosity_pas=co2_viscosity_pas,
        roughness_m=roughness_m,
        elevation_change_m=elevation_change_m,
    )

    min_dia_inches = min_dia_m * _METERS_TO_INCHES
    nominal_inches = standard_pipe_size(min_dia_m)

    # Calculate Re and ff at the converged diameter
    re = reynolds_number(flow_rate_kgs, co2_viscosity_pas, min_dia_m)
    ff = colebrook_white_fanning(re, min_dia_m, roughness_m)

    return {
        "min_diameter_m": min_dia_m,
        "min_diameter_inches": min_dia_inches,
        "nominal_diameter_inches": nominal_inches,
        "reynolds_number": re,
        "friction_factor_fanning": ff,
        "flow_rate_kgs": flow_rate_kgs,
        "temperature_c": temperature_c,
    }


# ============================================================================
# Cost estimation models
# ============================================================================


class PipelineCostModel(str, Enum):
    """Available pipeline cost regression models."""

    KNOOPE_2014 = "knoope_2014"  # Primary for Norway
    NETL_QUESTOR = "netl_questor"  # For US cross-verification


def _nearest_netl_diameter(diameter_inches: float, by_diameter: dict) -> int:
    """Find the nearest NETL supported diameter for a given diameter in inches.

    The NETL/QUE$TOR model has piecewise-linear regressions for specific
    standard pipe sizes (6, 8, 12, 16, 20). This maps a nominal or computed
    diameter to the nearest supported size.

    Args:
        diameter_inches: Pipe diameter in inches.
        by_diameter: Dictionary from YAML keyed by nominal diameter (int).

    Returns:
        The nearest supported diameter key (int).
    """
    sizes = sorted(int(k) for k in by_diameter.keys())
    if not sizes:
        return 12  # fallback default
    best = sizes[0]
    best_diff = abs(diameter_inches - best)
    for s in sizes[1:]:
        diff = abs(diameter_inches - s)
        if diff < best_diff:
            best = s
            best_diff = diff
    return best


class PipelineCosts(BaseModel):
    """Complete pipeline cost output."""

    diameter_m: float
    diameter_inches: float
    length_km: float
    capex: float
    opex_annual: float
    decommissioning: float
    model: str
    base_year: int
    currency: str
    items: list[CostItem] = []


def _load_pipeline_cost_models() -> dict:
    """Load pipeline cost model coefficients from YAML."""
    yaml_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "data"
        / "reference"
        / "pipeline_cost_models.yaml"
    )
    if not yaml_path.exists():
        return {}
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def pipeline_capex(
    diameter_m: float,
    length_km: float,
    offshore: bool = True,
    model: PipelineCostModel = PipelineCostModel.KNOOPE_2014,
    water_depth_m: float = 0.0,
) -> float:
    """Calculate pipeline capital cost.

    Args:
        diameter_m: Pipeline inner diameter in meters.
        length_km: Pipeline length in km.
        offshore: Whether pipeline is offshore.
        model: Cost regression model to use.
        water_depth_m: Water depth for offshore pipelines.

    Returns:
        Pipeline CAPEX in the model's base currency.
    """
    config = _load_pipeline_cost_models()

    if model == PipelineCostModel.KNOOPE_2014:
        knoope = config.get("knoope_2014", {}).get("capex", {})
        a = knoope.get("a", 0.0)
        b = knoope.get("b", 0.0)
        offshore_mult = knoope.get("offshore_multiplier", 1.4) if offshore else 1.0
        # Knoope 2014: CAPEX = a * D^b * L (EUR per km * km = EUR)
        # D in meters
        capex_per_km = a * diameter_m**b
        capex = capex_per_km * length_km * offshore_mult
        return capex

    elif model == PipelineCostModel.NETL_QUESTOR:
        netl = config.get("netl_questor", {}).get("capex", {})
        by_diameter = netl.get("by_diameter", {})
        diameter_inches = diameter_m * _METERS_TO_INCHES
        length_mi = length_km / 1.609344

        # Map to nearest supported NETL offshore diameter (6, 8, 12, 16, 20)
        nominal = _nearest_netl_diameter(diameter_inches, by_diameter)
        coeffs = by_diameter.get(nominal, {})
        slope = coeffs.get("slope_per_mi", 0.0)
        intercept = coeffs.get("intercept", 0.0)

        # NETL/QUE$TOR: CAPEX = slope * distance_mi + intercept (2022$)
        capex = slope * length_mi + intercept
        return capex

    else:
        raise ValueError(f"Unknown cost model: {model}")


def pipeline_opex_annual(
    diameter_m: float,
    length_km: float,
    model: PipelineCostModel = PipelineCostModel.KNOOPE_2014,
) -> float:
    """Calculate annual pipeline O&M cost.

    Args:
        diameter_m: Pipeline inner diameter in meters.
        length_km: Pipeline length in km.
        model: Cost regression model to use.

    Returns:
        Annual O&M cost in the model's base currency.
    """
    config = _load_pipeline_cost_models()

    if model == PipelineCostModel.KNOOPE_2014:
        knoope = config.get("knoope_2014", {}).get("opex", {})
        fraction = knoope.get("fraction_of_capex", 0.02)
        capex = pipeline_capex(diameter_m, length_km, offshore=True, model=model)
        return capex * fraction

    elif model == PipelineCostModel.NETL_QUESTOR:
        netl = config.get("netl_questor", {}).get("opex", {})
        by_diameter = netl.get("by_diameter", {})
        diameter_inches = diameter_m * _METERS_TO_INCHES
        length_mi = length_km / 1.609344

        # Map to nearest supported NETL offshore diameter
        nominal = _nearest_netl_diameter(diameter_inches, by_diameter)
        coeffs = by_diameter.get(nominal, {})
        slope = coeffs.get("slope_per_mi", 0.0)
        intercept = coeffs.get("intercept", 0.0)

        # NETL/QUE$TOR: Annual O&M = slope * distance_mi + intercept (2022$)
        opex = slope * length_mi + intercept
        return opex

    else:
        raise ValueError(f"Unknown cost model: {model}")


def pipeline_decommissioning(
    length_km: float,
    offshore: bool = True,
    decom_rate_per_km: float | None = None,
) -> float:
    """Calculate pipeline decommissioning cost.

    Default rate from BSEE Pacific OCS: $1,593,000/mile (2008$).

    Args:
        length_km: Pipeline length in km.
        offshore: Whether pipeline is offshore.
        decom_rate_per_km: Decommissioning rate per km. If None, uses BSEE default.

    Returns:
        Total decommissioning cost in USD (2008$).
    """
    if decom_rate_per_km is None:
        # BSEE rate: $1,593,000/mile = $989,609/km (2008$)
        decom_rate_per_mi = 1_593_000.0
        decom_rate_per_km = decom_rate_per_mi / 1.609344
    return decom_rate_per_km * length_km


def calculate_pipeline_costs(
    diameter_result: dict,
    length_km: float,
    model: PipelineCostModel = PipelineCostModel.KNOOPE_2014,
    offshore: bool = True,
    water_depth_m: float = 0.0,
    base_year: int = 2008,
    currency: str = "USD",
    construction_year: int = 3,
    operations_begin: int = 4,
    operations_end: int = 33,
    pisc_end: int = 83,
    decom_year: int = 84,
) -> PipelineCosts:
    """Calculate complete pipeline costs with properly timed CostItems.

    Args:
        diameter_result: Output from pipeline_diameter().
        length_km: Pipeline length in km.
        model: Cost regression model.
        offshore: Whether pipeline is offshore.
        water_depth_m: Water depth for offshore pipelines.
        base_year: Cost base year.
        currency: Currency code.
        construction_year: Project year for construction.
        operations_begin: First year of operations.
        operations_end: Last year of injection operations.
        pisc_end: Last year of PISC monitoring.
        decom_year: Year of decommissioning.

    Returns:
        PipelineCosts with CostItem list including CAPEX, O&M, and decommissioning.
    """
    diameter_m = diameter_result["min_diameter_m"]
    diameter_inches = diameter_result.get(
        "nominal_diameter_inches",
        diameter_result.get("min_diameter_inches", diameter_m * _METERS_TO_INCHES),
    )

    capex = pipeline_capex(diameter_m, length_km, offshore, model, water_depth_m)
    opex = pipeline_opex_annual(diameter_m, length_km, model)
    decom = pipeline_decommissioning(length_km, offshore)

    items = [
        CostItem(
            id="PIPE-CAPEX",
            name="Pipeline construction",
            category="pipeline",
            subcategory="construction",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PIPELINE,
            amount_base_year=capex,
            base_year=base_year,
            currency=currency,
            begin_year=construction_year,
            end_year=construction_year,
            recurrence="one-time",
            quantity=1.0,
        ),
        CostItem(
            id="PIPE-OPEX-OPS",
            name="Pipeline O&M (operations)",
            category="pipeline",
            subcategory="maintenance",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=opex,
            base_year=base_year,
            currency=currency,
            begin_year=operations_begin,
            end_year=operations_end,
            recurrence="annual",
            quantity=1.0,
        ),
        CostItem(
            id="PIPE-OPEX-PISC",
            name="Pipeline O&M (PISC)",
            category="pipeline",
            subcategory="maintenance",
            stage="pisc",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=opex,
            base_year=base_year,
            currency=currency,
            begin_year=operations_end + 1,
            end_year=pisc_end,
            recurrence="annual",
            quantity=1.0,
        ),
        CostItem(
            id="PIPE-DECOM",
            name="Pipeline decommissioning",
            category="pipeline",
            subcategory="decommissioning",
            stage="pisc",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=decom,
            base_year=base_year,
            currency=currency,
            begin_year=decom_year,
            end_year=decom_year,
            recurrence="one-time",
            quantity=1.0,
        ),
    ]

    return PipelineCosts(
        diameter_m=diameter_m,
        diameter_inches=diameter_inches,
        length_km=length_km,
        capex=capex,
        opex_annual=opex,
        decommissioning=decom,
        model=model.value,
        base_year=base_year,
        currency=currency,
        items=items,
    )

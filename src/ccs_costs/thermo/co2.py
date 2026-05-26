"""CO2 thermodynamic property functions.

Faithfully translated from NETL modCO2Prop.bas VBA module.

Functions:
    co2_density: CO2 density via Duan (1992) or Peng-Robinson EOS
    co2_viscosity: CO2 viscosity via Fenghour, Wakeham & Vesovic (1998)
    co2_compressibility: CO2 compressibility factor Z via Duan EOS

All public functions accept SI units:
    - pressure in MPa
    - temperature in Celsius
    - density in kg/m3
    - viscosity in Pa-s

Internal functions operate in VBA-native units and are prefixed with underscore.

The Duan and PR EOS solvers use scipy.optimize.brentq for robust root-finding
instead of the VBA Newton-Raphson, as recommended by the project spec. The EOS
equations and coefficients are identical to the VBA code.

References:
    Duan, Z., N. Moller, and J. Weare, 1992, "An Equation of State
    for the CH4-CO2-H2O System: I. Pure Systems from 0 to 1000C and
    0 to 8000 bar", Geochimica et Cosmochimica Acta Vol 56, pp. 2605-2617.

    Fenghour, A., W.A. Wakeham and V. Vesovic, 1998, "The Viscosity of
    Carbon Dioxide", J. Phys. Chem. Ref. Data, Vol. 27, No. 1, pg. 31-44.

    Span and Wagner, 1996, "A New Equation of State for Carbon Dioxide
    Covering the Fluid Region from Triple Point Temperature to 1000K at
    Pressures up to 800 MPa", J. Phys. Chem. Reference Data, Vol. 5,
    No. 6, pgs. 1509-1596.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

# ============================================================================
# Constants
# ============================================================================

# CO2 critical properties
_TC_CO2 = 304.1282  # Critical temperature (K)
_PC_CO2 = 7.3773  # Critical pressure (MPa)
_DENCRIT_CO2 = 467.6  # Critical density (kg/m3)
_MW_CO2 = 44.0095  # Molecular weight (g/mol)

# Gas constants in different unit systems
_RGAS_M3MPA = 0.000008314  # m3-MPa/(K-mol) -- for PR EOS
_RGAS_LBAR = 0.08314467  # L-bar/(K-mol) -- for Duan EOS reduced variables

# Unit conversions
_CELSIUS_TO_KELVIN = 273.15

# Validity limits
_P_MIN = 0.0  # MPa (exclusive)
_P_MAX = 100.0  # MPa (inclusive)
_T_MIN_C = -56.6  # Celsius (CO2 triple point)


# ============================================================================
# Input validation
# ============================================================================


def _validate_inputs(pressure_mpa: float, temperature_c: float) -> None:
    """Validate pressure and temperature inputs.

    Raises:
        ValueError: If pressure or temperature is out of valid range.
    """
    if pressure_mpa <= _P_MIN:
        raise ValueError(
            f"Pressure must be > {_P_MIN} MPa, got {pressure_mpa}"
        )
    if pressure_mpa > _P_MAX:
        raise ValueError(
            f"Pressure must be <= {_P_MAX} MPa, got {pressure_mpa}"
        )
    if temperature_c < _T_MIN_C:
        raise ValueError(
            f"Temperature must be >= {_T_MIN_C} C (CO2 triple point), "
            f"got {temperature_c}"
        )


# ============================================================================
# Span-Wagner auxiliary functions (saturation curve)
# ============================================================================


def _vp_sw_co2(tmp_k: float) -> float:
    """Vapor pressure of CO2 along saturation curve (Span & Wagner 1996).

    Args:
        tmp_k: Temperature in Kelvin.

    Returns:
        Vapor pressure in MPa.
    """
    a1, a2, a3, a4 = -7.0602087, 1.9391218, -1.6463597, -3.2995634
    n1, n2, n3, n4 = 1.0, 1.5, 2.0, 4.0

    tau = 1.0 - tmp_k / _TC_CO2
    return _PC_CO2 * math.exp(
        (_TC_CO2 / tmp_k)
        * (a1 * tau**n1 + a2 * tau**n2 + a3 * tau**n3 + a4 * tau**n4)
    )


def _densl_sw_co2(tmp_k: float) -> float:
    """Saturated liquid density of CO2 (Span & Wagner 1996).

    Args:
        tmp_k: Temperature in Kelvin.

    Returns:
        Saturated liquid density in kg/m3.
    """
    a1, a2, a3, a4 = 1.9245108, -0.62385555, -0.32731127, 0.39245142
    n1, n2, n3, n4 = 0.34, 0.5, 10.0 / 6.0, 11.0 / 6.0

    tau = 1.0 - tmp_k / _TC_CO2
    return _DENCRIT_CO2 * math.exp(
        a1 * tau**n1 + a2 * tau**n2 + a3 * tau**n3 + a4 * tau**n4
    )


def _densv_sw_co2(tmp_k: float) -> float:
    """Saturated vapor density of CO2 (Span & Wagner 1996).

    Args:
        tmp_k: Temperature in Kelvin.

    Returns:
        Saturated vapor density in kg/m3.
    """
    a1, a2, a3, a4, a5 = -1.7074879, -0.8227467, -4.6008549, -10.111178, -29.742252
    n1, n2, n3, n4, n5 = 0.34, 0.5, 1.0, 7.0 / 3.0, 14.0 / 3.0

    tau = 1.0 - tmp_k / _TC_CO2
    return _DENCRIT_CO2 * math.exp(
        a1 * tau**n1
        + a2 * tau**n2
        + a3 * tau**n3
        + a4 * tau**n4
        + a5 * tau**n5
    )


# ============================================================================
# Peng-Robinson EOS for CO2
# ============================================================================


def _pr_params(tmp_k: float) -> tuple[float, float]:
    """Calculate Peng-Robinson EOS parameters a(T) and b for CO2.

    Args:
        tmp_k: Temperature in Kelvin.

    Returns:
        (a, b) -- PR EOS parameters in (m3-MPa, m3/mol) units.
    """
    omega = 0.22394  # Acentric factor for CO2
    kappa = 0.37464 + 1.54226 * omega - 0.26992 * omega * omega
    alpha = (1.0 + kappa * (1.0 - math.sqrt(tmp_k / _TC_CO2))) ** 2

    a = 0.45724 * (_RGAS_M3MPA * _TC_CO2) ** 2 * alpha / _PC_CO2
    b = 0.0778 * _RGAS_M3MPA * _TC_CO2 / _PC_CO2
    return a, b


def _pres_pr_co2(vol: float, tmp_k: float) -> float:
    """Calculate pressure from PR EOS given molar volume and temperature.

    Translated from VBA presPRCO2().

    Args:
        vol: Molar volume in m3/mol.
        tmp_k: Temperature in K.

    Returns:
        Pressure in MPa.
    """
    a, b = _pr_params(tmp_k)
    rt = _RGAS_M3MPA * tmp_k

    return rt / (vol - b) - a / (vol * (vol + b) + b * (vol - b))


def _vol_pr_co2(pres_mpa: float, tmp_k: float) -> float:
    """Solve for CO2 molar volume using Peng-Robinson EOS.

    Uses scipy.optimize.brentq for robust root-finding. The PR EOS cubic
    has up to 3 real roots; we select the appropriate one (smallest positive
    for liquid/supercritical, largest for vapor).

    Args:
        pres_mpa: Pressure in MPa.
        tmp_k: Temperature in K.

    Returns:
        Molar volume in m3/mol.
    """
    a, b = _pr_params(tmp_k)

    # The PR cubic in terms of Z = PV/(RT):
    # Z^3 + c2*Z^2 + c1*Z + c0 = 0
    rt = _RGAS_M3MPA * tmp_k
    A = a * pres_mpa / rt**2
    B = b * pres_mpa / rt

    c2 = -(1.0 - B)
    c1 = A - 3.0 * B**2 - 2.0 * B
    c0 = -(A * B - B**2 - B**3)

    # Solve cubic analytically using numpy
    roots = np.roots([1.0, c2, c1, c0])

    # Filter for real, positive roots
    real_roots = []
    for r in roots:
        if abs(r.imag) < 1e-10 and r.real > 0:
            real_roots.append(r.real)

    if not real_roots:
        # Fallback: use ideal gas
        return rt / pres_mpa

    # Select the appropriate root:
    # - For liquid/supercritical at P > Pc: smallest Z (densest phase)
    # - For vapor at P < Pc: largest Z
    if tmp_k > _TC_CO2 and pres_mpa > _PC_CO2:
        z = min(real_roots)
    elif tmp_k <= _TC_CO2:
        # Below Tc: check if above or below vapor pressure
        pvap = _vp_sw_co2(tmp_k)
        if pres_mpa > pvap:
            z = min(real_roots)  # Liquid
        else:
            z = max(real_roots)  # Vapor
    else:
        # T > Tc, P < Pc: vapor-like
        z = max(real_roots)

    vol = z * rt / pres_mpa
    return vol


# ============================================================================
# Duan EOS for CO2
# ============================================================================

# Duan et al. (1992) equation of state constants
_DUAN_A = (
    0.0899288497,      # a1
    -0.494783127,       # a2
    0.0477922245,       # a3
    0.0103808883,       # a4
    -0.0282516861,      # a5
    0.0949887563,       # a6
    0.00052060088,      # a7
    -0.000293540971,    # a8
    -0.00177265112,     # a9
    -0.0000251101973,   # a10
    0.0000893353441,    # a11
    0.0000788998563,    # a12
    -0.0166727022,      # a13
    1.398,              # a14
    0.0296,             # a15
)


def _duan_volcrit() -> float:
    """Duan pseudo-critical volume (not the real critical volume).

    This is R*Tc/(Pc*10) in L/mol units, as defined in the VBA code.
    """
    return _RGAS_LBAR * _TC_CO2 / (_PC_CO2 * 10.0)


def _duan_b_coeffs(tr: float) -> tuple[float, float, float, float, float]:
    """Calculate Duan intermediate coefficients b1-b5 from reduced temperature.

    Args:
        tr: Reduced temperature T/Tc.

    Returns:
        (b1, b2, b3, b4, b5)
    """
    a = _DUAN_A
    tr2 = tr * tr
    tr3 = tr2 * tr

    b1 = a[0] + a[1] / tr2 + a[2] / tr3
    b2 = a[3] + a[4] / tr2 + a[5] / tr3
    b3 = a[6] + a[7] / tr2 + a[8] / tr3
    b4 = a[9] + a[10] / tr2 + a[11] / tr3
    b5 = a[12] / tr3

    return b1, b2, b3, b4, b5


def _pres_duan_co2(vol_m3mol: float, tmp_k: float) -> float:
    """Calculate pressure from Duan EOS given molar volume and temperature.

    Faithfully translated from VBA presDuanCO2(). The VBA function computes
    intermediate b values that include division by Vr powers (unlike fDuanCO2
    which uses different b formulation).

    Args:
        vol_m3mol: Molar volume in m3/mol.
        tmp_k: Temperature in K.

    Returns:
        Pressure in MPa.
    """
    a = _DUAN_A
    volcrit = _duan_volcrit()

    tr = tmp_k / _TC_CO2
    vr = vol_m3mol * 1000.0 / volcrit  # m3/mol -> L/mol -> reduced

    tr2 = tr * tr
    tr3 = tr2 * tr

    # VBA presDuanCO2 intermediate values (NOTE: divided by Vr powers!)
    b1 = (a[0] + a[1] / tr2 + a[2] / tr3) / vr
    b2 = (a[3] + a[4] / tr2 + a[5] / tr3) / vr**2
    b3 = (a[6] + a[7] / tr2 + a[8] / tr3) / vr**4
    b4 = (a[9] + a[10] / tr2 + a[11] / tr3) / vr**5
    b5 = (a[12] / (tr3 * vr**2)) * (a[13] + a[14] / vr**2) * math.exp(-a[14] / vr**2)

    # Reduced pressure
    pr = (tr / vr) * (1.0 + b1 + b2 + b3 + b4 + b5)

    return pr * _PC_CO2


def _vol_duan_co2(pres_mpa: float, tmp_k: float) -> float:
    """Solve for CO2 molar volume using Duan EOS with brentq.

    Uses scipy.optimize.brentq for robust root-finding. The residual function
    is P_duan(V, T) - P_target = 0.

    The correct root is bracketed by choosing volume bounds that correspond
    to the physical phase (liquid/supercritical dense phase when P > Pc,
    vapor phase otherwise).

    Args:
        pres_mpa: Pressure in MPa.
        tmp_k: Temperature in K.

    Returns:
        Molar volume in m3/mol.
    """
    volcrit_m3 = _MW_CO2 * 0.001 / _DENCRIT_CO2  # True critical molar volume (m3/mol)

    def residual(vol: float) -> float:
        """Residual function for Duan EOS volume solver.

        Computes P_duan(V, T) - P_target for brentq root-finding.
        The root of this function gives the molar volume at which the
        Duan EOS pressure equals the target pressure.

        Args:
            vol: Candidate molar volume in m3/mol.

        Returns:
            Pressure residual in MPa (zero at the solution).
        """
        return _pres_duan_co2(vol, tmp_k) - pres_mpa

    # Determine phase region and set bracket bounds
    if tmp_k > _TC_CO2:
        if pres_mpa > _PC_CO2:
            # Supercritical dense phase: volume between b (excluded) and ~volcrit
            # Density will be > critical density, so vol < volcrit
            # Lower bound: very small volume (very high density, ~1200 kg/m3)
            vol_lo = _MW_CO2 * 0.001 / 1200.0
            # Upper bound: ideal gas volume (always too large for dense phase)
            vol_hi = _RGAS_M3MPA * tmp_k / pres_mpa * 2.0
            # For moderate supercritical (near critical), ensure bracket captures root
            if vol_hi < volcrit_m3 * 1.5:
                vol_hi = volcrit_m3 * 1.5
        else:
            # Supercritical vapor-like: volume > volcrit
            vol_lo = volcrit_m3 * 0.5
            vol_hi = _RGAS_M3MPA * tmp_k / pres_mpa * 2.0
    else:
        pvap = _vp_sw_co2(tmp_k)
        if pres_mpa > pvap:
            # Liquid phase: small volume
            vol_lo = _MW_CO2 * 0.001 / 1200.0
            denlsat = _densl_sw_co2(tmp_k)
            vollsat = _MW_CO2 * 0.001 / denlsat
            vol_hi = vollsat * 1.1
        else:
            # Vapor phase
            denvsat = _densv_sw_co2(tmp_k)
            volvsat = _MW_CO2 * 0.001 / denvsat
            vol_lo = volvsat * 0.9
            vol_hi = _RGAS_M3MPA * tmp_k / pres_mpa * 2.0

    # Verify bracket contains a sign change; if not, expand
    try:
        f_lo = residual(vol_lo)
        f_hi = residual(vol_hi)
    except (ValueError, OverflowError, ZeroDivisionError):
        # Fallback to wider bracket
        vol_lo = _MW_CO2 * 0.001 / 1200.0
        vol_hi = _RGAS_M3MPA * tmp_k / pres_mpa * 5.0
        f_lo = residual(vol_lo)
        f_hi = residual(vol_hi)

    if f_lo * f_hi > 0:
        # No sign change -- try expanding bracket
        for expansion in [5.0, 10.0, 20.0, 50.0]:
            vol_hi_expanded = _RGAS_M3MPA * tmp_k / pres_mpa * expansion
            try:
                f_hi = residual(vol_hi_expanded)
                if f_lo * f_hi <= 0:
                    vol_hi = vol_hi_expanded
                    break
            except (ValueError, OverflowError, ZeroDivisionError):
                continue

        if f_lo * f_hi > 0:
            # Try shrinking lower bound
            vol_lo_shrunk = _MW_CO2 * 0.001 / 1500.0
            try:
                f_lo = residual(vol_lo_shrunk)
                if f_lo * f_hi <= 0:
                    vol_lo = vol_lo_shrunk
            except (ValueError, OverflowError, ZeroDivisionError):
                pass

    return brentq(residual, vol_lo, vol_hi, rtol=1e-12, maxiter=200)


# ============================================================================
# Fenghour-Wakeham-Vesovic (1998) viscosity correlation
# ============================================================================


def _vis_fwv_co2(den_kgm3: float, tmp_k: float) -> float:
    """CO2 viscosity via Fenghour, Wakeham & Vesovic (1998).

    Faithful translation of VBA visFWVCO2().

    Args:
        den_kgm3: CO2 density in kg/m3.
        tmp_k: Temperature in K.

    Returns:
        Viscosity in uPa-s (micro-Pascal-seconds).
    """
    # Zero-density viscosity term
    tmpcs = 251.196  # K
    az = [0.235156, -0.491266, 0.05211155, 0.05347906, -0.01537102]

    csr = 0.0
    log_tr = math.log(tmp_k / tmpcs)
    for j in range(5):
        csr += az[j] * log_tr**j

    visz = 1.00697 * math.sqrt(tmp_k) / math.exp(csr)

    # Excess viscosity term (density correction)
    d11 = 0.004071119
    d21 = 0.00007198037
    d64 = 2.411697e-17
    d81 = 2.971072e-23
    d82 = -1.627888e-23

    den = den_kgm3
    tr = tmp_k / tmpcs

    visexc = (
        d11 * den
        + d21 * den**2
        + d64 * den**6 * tr**-3
        + d81 * den**8
        + d82 * den**8 * tr**-1
    )

    return visz + visexc


# ============================================================================
# Public API
# ============================================================================


def co2_density(
    pressure_mpa: float,
    temperature_c: float,
    method: str = "duan",
) -> float:
    """Calculate CO2 density at given pressure and temperature.

    Args:
        pressure_mpa: Pressure in MPa. Must be > 0 and <= 100.
        temperature_c: Temperature in Celsius. Must be >= -56.6 (CO2 triple point).
        method: EOS method - "duan" (default) or "peng-robinson".

    Returns:
        CO2 density in kg/m3.

    Raises:
        ValueError: If pressure or temperature is out of valid range.
        ValueError: If method is not recognized.
    """
    _validate_inputs(pressure_mpa, temperature_c)

    if method not in ("duan", "peng-robinson"):
        raise ValueError(
            f"Method must be 'duan' or 'peng-robinson', got '{method}'"
        )

    tmp_k = temperature_c + _CELSIUS_TO_KELVIN

    if method == "duan":
        vol = _vol_duan_co2(pressure_mpa, tmp_k)
    else:
        vol = _vol_pr_co2(pressure_mpa, tmp_k)

    # density = MW / molar_volume
    # MW in g/mol, vol in m3/mol -> density in g/m3 -> /1000 = kg/m3
    # density_kg_m3 = (MW g/mol * 0.001 kg/g) / (vol m3/mol)
    return _MW_CO2 * 0.001 / vol


def co2_viscosity(
    density_kgm3: float,
    temperature_c: float,
) -> float:
    """Calculate CO2 dynamic viscosity using Fenghour-Wakeham-Vesovic (1998).

    Args:
        density_kgm3: CO2 density in kg/m3 (from co2_density).
        temperature_c: Temperature in Celsius.

    Returns:
        CO2 dynamic viscosity in Pa-s.
    """
    tmp_k = temperature_c + _CELSIUS_TO_KELVIN

    # FWV returns viscosity in uPa-s, convert to Pa-s
    vis_upas = _vis_fwv_co2(density_kgm3, tmp_k)
    return vis_upas * 1e-6


def co2_compressibility(
    pressure_mpa: float,
    temperature_c: float,
) -> float:
    """Calculate CO2 compressibility factor Z = PV/(nRT) using Duan EOS.

    Args:
        pressure_mpa: Pressure in MPa.
        temperature_c: Temperature in Celsius.

    Returns:
        Compressibility factor Z (dimensionless).
    """
    _validate_inputs(pressure_mpa, temperature_c)

    tmp_k = temperature_c + _CELSIUS_TO_KELVIN
    vol = _vol_duan_co2(pressure_mpa, tmp_k)

    # Z = PV / (nRT) where n=1 mol
    return (pressure_mpa * vol) / (_RGAS_M3MPA * tmp_k)

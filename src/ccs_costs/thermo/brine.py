"""Brine thermodynamic property functions.

Faithfully translated from NETL modBrineProp.bas VBA module (Karl Bandilla /
Princeton correlations, adapted by David Morgan at NETL).

Functions:
    brine_density: Brine density via Battistelli/Haas approach
    brine_viscosity: Brine viscosity via Phillips et al. (1981)

All public functions accept SI units:
    - temperature in Celsius
    - pressure in MPa
    - salinity in ppm (mg/L)
    - density in kg/m3
    - viscosity in Pa-s

Internal functions operate in VBA-native units (C, Pa, mass fraction).

References:
    Battistelli, A., C. Calore and K. Pruess (1997) The simulator TOUGH2/EWASG
    for modelling geothermal reservoirs with brines and non-condensible gas.
    Geothermics 26(4), pp. 437-464.

    Haas, J.L. (1976) Physical properties of the coexisting phases and
    Thermochemical properties of the H2O component in boiling NaCl solutions.
    USGS Bulletin 1421-A, Washington, DC, 73 pp.

    Phillips, S.L., A. Igbene, J.A. Fair, H. Ozbek and M. Tavana (1981)
    A Technical Databook for Geothermal Energy Utilization. Lawrence Berkeley
    Laboratory Report LBL-12810.

    1967 IFC Formulation for Industrial Use (ASME Steam Tables) for pure water
    density and viscosity.
"""

from __future__ import annotations

import math

# ============================================================================
# Constants
# ============================================================================

_MPA_TO_PA = 1.0e6
_PPM_TO_MASS_FRACTION = 1.0e-6

# Molecular weights
_MW_NACL = 58.448  # g/mol
_MW_WATER = 18.016  # g/mol

# Validity limits
_T_MIN_C = 0.01  # Celsius (above freezing)
_T_MAX_C = 350.0  # Celsius
_P_MIN_MPA = 0.0  # MPa (exclusive)
_P_MAX_MPA = 100.0  # MPa
_SAL_MIN_PPM = 0.0  # ppm (inclusive)
_SAL_MAX_PPM = 400000.0  # ppm (exclusive)


# ============================================================================
# Input validation
# ============================================================================


def _validate_brine_inputs(
    temperature_c: float, pressure_mpa: float, salinity_ppm: float
) -> None:
    """Validate brine property inputs.

    Raises:
        ValueError: If any input is out of valid range.
    """
    if temperature_c < _T_MIN_C or temperature_c > _T_MAX_C:
        raise ValueError(
            f"Temperature must be between {_T_MIN_C} and {_T_MAX_C} C, "
            f"got {temperature_c}"
        )
    if pressure_mpa <= _P_MIN_MPA:
        raise ValueError(
            f"Pressure must be > {_P_MIN_MPA} MPa, got {pressure_mpa}"
        )
    if pressure_mpa > _P_MAX_MPA:
        raise ValueError(
            f"Pressure must be <= {_P_MAX_MPA} MPa, got {pressure_mpa}"
        )
    if salinity_ppm < _SAL_MIN_PPM:
        raise ValueError(
            f"Salinity must be >= {_SAL_MIN_PPM} ppm, got {salinity_ppm}"
        )
    if salinity_ppm >= _SAL_MAX_PPM:
        raise ValueError(
            f"Salinity must be < {_SAL_MAX_PPM} ppm, got {salinity_ppm}"
        )


# ============================================================================
# Internal helper functions (translated from VBA)
# ============================================================================


def _sat(t_c: float) -> float:
    """Saturation pressure for pure water (Pa).

    Based on the 1967 IFC Formulation for Industrial Use (ASME Steam Tables,
    Appendix 1). Translated from VBA SAT().

    Args:
        t_c: Temperature in degrees Celsius.

    Returns:
        Saturation pressure in Pa.
    """
    k1 = -7.691234564
    k2 = -26.08023696
    k3 = -168.1706546
    k4 = 64.23285504
    k5 = -118.9646225
    k6 = 4.16711732
    k7 = 20.9750676
    k8 = 1_000_000_000.0
    k9 = 6.0

    # Dimensionless temperature
    th = (t_c + 273.15) / 647.3

    # 1 - theta
    x = 1.0 - th

    # Summation term
    sc = k5 * x + k4
    sc = sc * x + k3
    sc = sc * x + k2
    sc = sc * x + k1
    sc = sc * x

    beta_k = math.exp(
        sc / (th * (1.0 + k6 * x + k7 * x**2))
        - x / (k8 * x**2 + k9)
    )

    return beta_k * 22_120_000.0


def _satb(t_c: float, xs: float) -> float:
    """Vapor pressure of brine (Pa).

    From Haas (1976). Translated from VBA SATB().

    Args:
        t_c: Temperature in degrees Celsius.
        xs: Salinity as mass fraction.

    Returns:
        Saturation pressure of brine in Pa.
    """
    if xs <= 0.0:
        return _sat(t_c)

    xg = 0.0

    # Convert to molal concentration
    smol = xs / _MW_NACL / (1.0 - xs - xg) * 1000.0

    # Haas equation (4)
    a = (
        1.0
        + 0.00000593582 * smol
        - 0.0000519386 * smol**2
        + 0.0000123156 * smol**3
    )

    # Haas equation (5)
    b = (
        0.0000011542 * smol
        + 0.000000141254 * smol**2
        - 0.0000000192476 * smol**3
        - 0.00000000170717 * smol**4
        + 0.00000000010539 * smol**5
    )

    tk = t_c + 273.15
    if tk <= 0.0:
        tk = 0.01  # Guard against log(0)

    # Haas equation (3): equivalent temperature
    tz = math.exp(math.log(tk) / (a + b * tk)) - 273.15

    return _sat(tz)


def _brine_crit_temp(xs: float) -> float:
    """Critical temperature of brine (deg C).

    Newton iteration of equation (27) from Battistelli et al. (1997).
    Translated from VBA BrineCritTemp().

    Args:
        xs: Salinity as mass fraction.

    Returns:
        Critical temperature in degrees Celsius.
    """
    xnew = 374.1  # Initial guess
    xpc = xs * 100.0

    for _ in range(31):
        # Equation (27) * 100
        fx = (
            -92.682482
            + 0.0000001852385
            + 0.43077335 * xnew
            - 0.00062561155 * xnew**2
            + 0.00000036441625 * xnew**3
            - xpc
        )

        # Derivative
        fdx = (
            0.43077335
            - 0.00062561155 * 2.0 * xnew
            + 0.00000036441625 * 3.0 * xnew**2
        )

        dx = -fx / fdx
        xnew = xnew + dx

        if abs(dx) < 0.1:
            break

    tc = xnew
    if tc < 374.15:
        tc = 374.15

    return tc


def _pure_water_density(t_c: float, p_sat_pa: float) -> float:
    """Pure water density (kg/m3).

    Based on 1967 IFC Formulation (ASME Steam Tables, Appendix 1, Section 7.1.1:
    Sub-region 1, Reduced volume). Translated from VBA PureWatDen().

    Args:
        t_c: Temperature in degrees Celsius.
        p_sat_pa: Pressure in Pa (saturation or actual).

    Returns:
        Pure water density in kg/m3.
    """
    # Constants from section 7.1.1 (lowercase a)
    sa1 = 0.8438375405
    sa2 = 0.0005362162162
    sa3 = 1.72
    sa4 = 0.07342278489
    sa5 = 0.0497585887
    sa6 = 0.65371543
    sa7 = 0.00000115
    sa8 = 0.000015108
    sa9 = 0.14188
    sa10 = 7.002753165
    sa11 = 0.0002995284926
    sa12 = 0.204

    # Constants (uppercase A)
    a11 = 7.982692717
    a12 = -0.02616571843
    a13 = 0.00152241179
    a14 = 0.02284279054
    a15 = 242.1647003
    a16 = 1.269716088e-10
    a17 = 2.074838328e-07
    a18 = 2.17402035e-08
    a19 = 1.105710498e-09
    a20 = 12.93441934
    a21 = 0.00001308119072
    a22 = 6.047626338e-14

    # Dimensionless temperature and pressure
    tkr = (t_c + 273.15) / 647.3
    pnmr = p_sat_pa / 22_120_000.0

    # Sub-region 1: Reduced volume
    y = 1.0 - sa1 * tkr**2 - sa2 / tkr**6
    zp = sa3 * y**2 - 2.0 * sa4 * tkr + 2.0 * sa5 * pnmr
    z = y + math.sqrt(zp)

    # Chi terms
    par1 = a11 * sa5 * z ** (-5.0 / 17.0)

    par2 = (
        a12
        + a13 * tkr
        + a14 * tkr**2
        + a15 * (sa6 - tkr) ** 10
        + a16 * (sa7 + tkr**19) ** -1
    )

    par3 = (a17 + 2.0 * a18 * pnmr + 3.0 * a19 * pnmr**2) * (
        sa8 + tkr**11
    ) ** -1

    par4 = (
        a20
        * tkr**18
        * (sa9 + tkr**2)
        * (-3.0 * (sa10 + pnmr) ** -4 + sa11)
    )

    par5 = 3.0 * a21 * (sa12 - tkr) * pnmr**2

    par6 = 4.0 * a22 * tkr ** (-20) * pnmr**3

    chi = par1 + par2 - par3 - par4 + par5 + par6

    # Convert from dimensionless specific volume to density
    v = chi * 0.00317  # m3/kg
    return 1.0 / v


def _pure_water_viscosity(t_c: float, density_kgm3: float) -> float:
    """Pure water dynamic viscosity (Pa-s).

    Based on the Eighth International Conference on the Properties of Steam
    (ASME Steam Tables, Appendix 6). Translated from VBA PureWatVisc().

    Args:
        t_c: Temperature in degrees Celsius.
        density_kgm3: Pure water density in kg/m3.

    Returns:
        Pure water viscosity in Pa-s.
    """
    # Constants from Appendix C equation (4)
    a0 = 0.0181583
    a1 = 0.0177624
    a2 = 0.0105287
    a3 = -0.0036744

    # Constants from Appendix C table A (bij matrix, i=0-5, j=0-4)
    b = [
        [0.501938, 0.235622, -0.274637, 0.145831, -0.0270448],
        [0.162888, 0.789393, -0.743539, 0.263129, -0.0253093],
        [-0.130356, 0.673665, -0.959456, 0.347247, -0.0267758],
        [0.907919, 1.207552, -0.687343, 0.213486, -0.0822904],
        [-0.551119, 0.0670665, -0.497089, 0.100754, 0.0602253],
        [0.146543, -0.084337, 0.195286, -0.032932, -0.0202595],
    ]

    # Dimensionless T*/T
    tr = 647.27 / (t_c + 273.15)

    # T/T*
    tri = 1.0 / tr

    # T*/T - 1
    tr1 = tr - 1.0

    # Dimensionless density rho/rho*
    dx1 = max(density_kgm3, 1.0)  # Guard against non-positive density
    dr = dx1 / 317.763

    # rho/rho* - 1
    dr1 = dr - 1.0

    # Equation (2): zero-density term
    amu0_denom = a0 + a1 * tr + a2 * tr**2 + a3 * tr**3
    amu0 = math.sqrt(tri) / amu0_denom * 1e-6

    # Equation (1): summation over i=0..5
    sun = 0.0
    for i in range(6):
        row_sum = 0.0
        for j in range(5):
            row_sum += b[i][j] * dr1**j
        sun += row_sum * tr1**i

    return amu0 * math.exp(dr * sun)


# ============================================================================
# Public API
# ============================================================================


def brine_density(
    temperature_c: float,
    pressure_mpa: float,
    salinity_ppm: float,
) -> float:
    """Calculate brine density at given conditions.

    Uses the Battistelli, Calore & Pruess (1997) / Haas (1976) approach,
    faithfully translated from NETL VBA BrineDen().

    Args:
        temperature_c: Temperature in Celsius. Must be between 0.01 and 350.
        pressure_mpa: Pressure in MPa. Must be > 0 and <= 100.
        salinity_ppm: Salinity in ppm (mg/L). Must be >= 0 and < 400000.

    Returns:
        Brine density in kg/m3.

    Raises:
        ValueError: If any input is out of valid range.
    """
    _validate_brine_inputs(temperature_c, pressure_mpa, salinity_ppm)

    # Convert to VBA internal units
    p_pa = pressure_mpa * _MPA_TO_PA
    xs = salinity_ppm * _PPM_TO_MASS_FRACTION  # mass fraction

    # Pure water saturation pressure
    psatw = _sat(temperature_c)

    # Pure water density at saturation
    dws = _pure_water_density(temperature_c, psatw)

    if xs <= 0.0:
        # Pure water: apply pressure correction using Battistelli eq. (24)
        # with c = 0 (no salinity effect), just pressure correction
        dp = p_pa - psatw
        if dp < 1000.0:
            dp = 1000.0
        # For pure water, use the density at actual pressure
        return _pure_water_density(temperature_c, psatw + dp)

    xncgl = 0.0

    # Convert to molal concentration
    smol = xs / _MW_NACL / (1.0 - xs - xncgl) * 1000.0

    # Specific volume in cm3/g (VBA: v0 = 1000 / dws)
    v0 = 1000.0 / dws

    # Haas (1976) equation (10): sk parameter
    sk = (-13.644 + 13.97 * v0) * (3.1975 / (3.1975 - v0)) ** 2

    # Haas (1976) equation (8): apparent molal volume (fi)
    fi = -167.219 + 448.55 * v0 - 261.07 * v0**2 + sk * math.sqrt(smol)

    # Haas (1976) equation (10): brine density at saturation (kg/m3)
    dbs = (1000.0 + smol * _MW_NACL) / (1000.0 * v0 + smol * fi) * 1000.0

    # Battistelli et al. (1997): critical temperature
    tc = _brine_crit_temp(xs)

    # Equation (26): tau
    tau = 1.0 - (temperature_c + 273.15) / (tc + 273.15)

    # Convert to mole fraction
    xmol = smol / (1000.0 / _MW_WATER + smol)

    # Equation (25): compressibility coefficient c
    denom = tau**1.25 - 5.6 * xmol**1.5 + 0.005
    c = -0.00000000016534 / denom

    # Saturated vapor pressure of brine
    psat = _satb(temperature_c, xs)

    # Equation (24): pressure correction
    return dbs / (1.0 + c * (p_pa - psat))


def brine_viscosity(
    temperature_c: float,
    pressure_mpa: float,
    salinity_ppm: float,
) -> float:
    """Calculate brine dynamic viscosity at given conditions.

    Uses Phillips, Igbene, Fair, Ozbek & Tavana (1981), faithfully translated
    from NETL VBA BrineVisc().

    Args:
        temperature_c: Temperature in Celsius. Must be between 0.01 and 350.
        pressure_mpa: Pressure in MPa. Must be > 0 and <= 100.
        salinity_ppm: Salinity in ppm (mg/L). Must be >= 0 and < 400000.

    Returns:
        Brine dynamic viscosity in Pa-s.

    Raises:
        ValueError: If any input is out of valid range.
    """
    _validate_brine_inputs(temperature_c, pressure_mpa, salinity_ppm)

    # Convert to VBA internal units
    p_pa = pressure_mpa * _MPA_TO_PA
    xs = salinity_ppm * _PPM_TO_MASS_FRACTION  # mass fraction

    # Pure water saturation pressure
    psatw = _sat(temperature_c)

    xncgl = 0.0

    if xs > 0.0:
        # Convert to molal concentration
        smol = xs / _MW_NACL / (1.0 - xs - xncgl) * 1000.0
    else:
        smol = 0.0

    # Phillips et al. (1981) equation (1): viscosity ratio
    ratio = (
        1.0
        + 0.0816 * smol
        + 0.0122 * smol**2
        + 0.000128 * smol**3
        + 0.000629 * temperature_c * (1.0 - math.exp(-0.7 * smol))
    )

    # Pressure difference for water density calculation
    dp = p_pa - psatw
    if dp < 1000.0:
        dp = 1000.0

    # Pure water density at the given pressure
    dw0 = _pure_water_density(temperature_c, psatw + dp)

    return ratio * _pure_water_viscosity(temperature_c, dw0)

"""Standalone CO2 thermodynamic property lookup.

Exercises just the thermo module (Duan 1992 EOS) without touching the
geological or financial pipeline. Useful for spot-checking against the
NIST Chemistry WebBook.

Run:
    python examples/03_co2_properties.py
"""

from ccs_costs.thermo import co2_density, co2_viscosity


CONDITIONS = [
    # (P_MPa, T_C, description)
    (10.0, 35.0, "shallow supercritical"),
    (20.0, 50.0, "deep aquifer (warm)"),
    (20.0,  4.0, "NCS seabed"),
    (30.0, 100.0, "deep, hot reservoir"),
]


def main() -> None:
    print(f"{'P (MPa)':>8} {'T (C)':>6} {'rho (kg/m3)':>12} {'mu (uPa.s)':>11}  context")
    print("-" * 60)
    for p_mpa, t_c, label in CONDITIONS:
        rho = co2_density(p_mpa, t_c, method="duan")
        mu_pa_s = co2_viscosity(p_mpa, t_c)
        print(f"{p_mpa:>8.1f} {t_c:>6.1f} {rho:>12.2f} {mu_pa_s * 1e6:>11.2f}  {label}")


if __name__ == "__main__":
    main()

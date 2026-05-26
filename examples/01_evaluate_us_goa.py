"""Single-formation FYBE evaluation (US Gulf of America).

Runs the full thermo -> geo -> costs -> finance chain for the NETL
default formation (1241_1, Chandeleur Area). Cross-verifies against
the published NETL CO2_S_COM_Offshore v1.1 reference value of $25.34/t
in 2008 dollars.

Run:
    python examples/01_evaluate_us_goa.py
"""

from ccs_costs.scenario import ScenarioConfig, evaluate_scenario


def main() -> None:
    config = ScenarioConfig(
        formation_id="1241_1",
        region="us-goa",
        injection_rate_tpa=4_000_000,
    )

    result = evaluate_scenario(config)

    print(f"Formation       : {config.formation_id} ({config.region})")
    print(f"Injection rate  : {config.injection_rate_tpa / 1e6:.2f} Mt/yr")
    print(f"Injection wells : {result.n_injection_wells}")
    print(f"Pipeline        : {result.pipeline_diameter_inches:.0f} inch")
    print(f"Total CAPEX     : ${result.total_capex / 1e6:>9,.1f} M (2008$)")
    print(f"Total OPEX      : ${result.total_opex / 1e6:>9,.1f} M (2008$)")
    print(f"FYBE (2008$)    : ${result.fybe:>6.2f} / t")
    print(f"FYBE (2024$)    : ${result.fybe_current_year:>6.2f} / t")
    print()
    print("NETL reference  : $25.34/t (2008$) | $72.20/t (2024$)")


if __name__ == "__main__":
    main()

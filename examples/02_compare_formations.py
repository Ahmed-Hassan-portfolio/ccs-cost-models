"""Compare FYBE across multiple formations.

Builds a small supply curve by sweeping a handful of US-GOA formations,
then prints them sorted ascending by break-even price.

Run:
    python examples/02_compare_formations.py
"""

from ccs_costs.scenario import ScenarioConfig, evaluate_scenario


FORMATIONS = ["1241_1", "1241_2", "1241_3", "1241_4", "1261_1"]


def main() -> None:
    rows = []
    for fid in FORMATIONS:
        try:
            result = evaluate_scenario(
                ScenarioConfig(formation_id=fid, region="us-goa")
            )
            rows.append((fid, result.fybe, result.n_injection_wells))
        except Exception as exc:
            print(f"  skip {fid}: {exc}")

    rows.sort(key=lambda r: r[1])

    print(f"{'Formation':<10} {'FYBE 2008$':>12} {'Wells':>6}")
    print("-" * 32)
    for fid, fybe, n_wells in rows:
        print(f"{fid:<10} {fybe:>10.2f} $/t {n_wells:>6}")


if __name__ == "__main__":
    main()

"""CLI entry point: python -m ccs_costs evaluate|list-formations|list-regions.

Usage:
    python -m ccs_costs list-regions
    python -m ccs_costs list-formations --region us-goa
    python -m ccs_costs evaluate --region us-goa --formation 1241_1
    python -m ccs_costs evaluate --region us-goa --all --output results.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time


def cmd_list_regions(args):
    from ccs_costs.config import list_available_regions, load_region

    regions = list_available_regions()
    print(f"{'Region':<15} {'Formations':>10} {'Currency':>8} {'Base Year':>10}")
    print("-" * 48)
    for rid in regions:
        r = load_region(rid)
        print(f"{rid:<15} {len(r.formations):>10} {r.currency:>8} {r.base_year:>10}")


def cmd_list_formations(args):
    from ccs_costs.config import load_region

    region = load_region(args.region)
    fmt = f"{'ID':<12} {'Name':<20} {'Depth(m)':>8} {'WD(m)':>6} {'Porosity':>8} {'Perm(mD)':>8}"
    print(fmt)
    print("-" * len(fmt))
    for fid, f in sorted(region.formations.items()):
        print(
            f"{fid:<12} {f.name:<20} {f.depth_m:>8.0f} {f.water_depth_m:>6.0f} "
            f"{f.porosity:>8.3f} {f.permeability_md:>8.1f}"
        )
    print(f"\n{len(region.formations)} formations in {args.region}")


def cmd_evaluate(args):
    from ccs_costs.config import load_region
    from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

    region = load_region(args.region)
    currency_sym = {"USD": "$", "NOK": "NOK ", "EUR": "\u20ac"}.get(region.currency, "")

    if args.all:
        _evaluate_all(args, region, currency_sym)
        return

    if not args.formation:
        print("Error: --formation is required (or use --all)", file=sys.stderr)
        sys.exit(1)

    config = ScenarioConfig(formation_id=args.formation, region=args.region)
    result = evaluate_scenario(config)

    print(f"\n{'=' * 50}")
    print(f"  CO2 Storage Cost Estimate")
    print(f"  Formation: {result.formation_name} ({result.formation_id})")
    print(f"  Region:    {result.region}")
    print(f"{'=' * 50}")
    print(f"  Break-Even Cost:  {currency_sym}{result.fybe:.2f}/t ({result.base_year} {result.currency})")
    print(f"  FBYE (2024 est.): {currency_sym}{result.fybe_current_year:.1f}/t")
    print(f"")
    print(f"  Injection wells:  {result.n_injection_wells}")
    print(f"  Monitoring wells: {result.n_monitoring_wells}")
    print(f'  Pipeline:         {result.pipeline_diameter_inches:.0f}" x {result.pipeline_length_km:.0f} km')
    print(f"  CO2 stored:       {result.total_co2_stored_mt:.0f} Mt")
    print(f"  Project duration: {result.project_duration_years} yr")
    print(f"")
    print(f"  CAPEX: {currency_sym}{result.total_capex / 1e6:,.0f}M")
    print(f"  OPEX:  {currency_sym}{result.total_opex / 1e6:,.0f}M")

    if result.cost_breakdown:
        total = result.total_capex + result.total_opex
        print(f"\n  Cost Drivers:")
        for cat, val in sorted(result.cost_breakdown.items(), key=lambda x: -x[1]):
            pct = val / total * 100 if total > 0 else 0
            print(f"    {cat:<20s}  {currency_sym}{val / 1e6:>8.1f}M  ({pct:>4.1f}%)")

    print(f"{'=' * 50}\n")


def _evaluate_all(args, region, currency_sym):
    from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

    formations = list(region.formations.items())
    n = len(formations)
    results = []

    print(f"Evaluating {n} formations in {args.region}...")
    t0 = time.time()

    for i, (fid, f) in enumerate(formations):
        try:
            r = evaluate_scenario(ScenarioConfig(formation_id=fid, region=args.region))
            results.append({
                "formation_id": fid,
                "formation_name": f.name,
                "fybe": round(r.fybe, 2),
                "fybe_2024": round(r.fybe_current_year, 2),
                "wells": r.n_injection_wells,
                "pipeline_inches": r.pipeline_diameter_inches,
                "pipeline_km": round(r.pipeline_length_km, 1),
                "capex_m": round(r.total_capex / 1e6, 1),
                "opex_m": round(r.total_opex / 1e6, 1),
                "co2_mt": round(r.total_co2_stored_mt, 1),
                "status": "ok",
            })
        except Exception as e:
            results.append({
                "formation_id": fid,
                "formation_name": f.name,
                "fbye": None,
                "status": f"error: {str(e)[:60]}",
            })

        if (i + 1) % 10 == 0 or i == n - 1:
            elapsed = time.time() - t0
            print(f"  [{i + 1}/{n}] {elapsed:.1f}s elapsed")

    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] != "ok"]
    print(f"\nDone: {len(ok)} succeeded, {len(failed)} failed in {time.time() - t0:.1f}s")

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"Results saved to {args.output}")
    else:
        # Print sorted table
        ok_sorted = sorted(ok, key=lambda x: x["fbye"])
        print(f"\n{'ID':<10} {'Name':<15} {'FBYE':>8} {'Wells':>5} {'CAPEX(M)':>8}")
        print("-" * 50)
        for r in ok_sorted[:20]:
            print(
                f"{r['formation_id']:<10} {r['formation_name']:<15} "
                f"{currency_sym}{r['fbye']:>6.2f} {r['wells']:>5} "
                f"{currency_sym}{r['capex_m']:>6.0f}M"
            )
        if len(ok_sorted) > 20:
            print(f"  ... and {len(ok_sorted) - 20} more")


def main():
    parser = argparse.ArgumentParser(
        prog="ccs_costs",
        description="CO2 Storage Cost Estimation Engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list-regions
    subparsers.add_parser("list-regions", help="List available regions")

    # list-formations
    p_lf = subparsers.add_parser("list-formations", help="List formations in a region")
    p_lf.add_argument("--region", required=True, help="Region ID (e.g., us-goa)")

    # evaluate
    p_ev = subparsers.add_parser("evaluate", help="Evaluate a formation or all formations")
    p_ev.add_argument("--region", required=True, help="Region ID")
    p_ev.add_argument("--formation", help="Formation ID (e.g., 1241_1)")
    p_ev.add_argument("--all", action="store_true", help="Evaluate all formations")
    p_ev.add_argument("--output", help="Output CSV file path (with --all)")

    args = parser.parse_args()

    if args.command == "list-regions":
        cmd_list_regions(args)
    elif args.command == "list-formations":
        cmd_list_formations(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

"""FastMCP server exposing CCS cost estimation tools.

This is a thin wrapper around the engine modules. No calculation logic
lives here -- all logic stays in scenario.py, config.py, and the engine
modules (thermo, geo, costs, finance).

Tools:
    Essential v1 (4 core):
        estimate_storage_cost - Full scenario FYBE calculation
        co2_properties - CO2 thermophysical properties
        calculate_pipeline - Pipeline sizing and costing
        get_scenario_history - Query past scenario runs

    Discovery (3):
        list_regions - Available regions with summary info
        list_formations - Formations in a region
        compare_formations - Multi-formation FYBE comparison

    Phase 6 analysis tools (3):
        run_sensitivity - One-way and tornado sensitivity analysis (Phase 6 implemented)
        run_supply_curve - Multi-formation FYBE ranking (Phase 6 implemented)
        run_monte_carlo - Probabilistic FYBE simulation (Phase 6 implemented)
"""

from __future__ import annotations

from fastmcp import FastMCP

from ccs_costs import history as history_mod
from ccs_costs.config import list_available_regions, load_region
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario
from ccs_costs.thermo import co2_compressibility, co2_density, co2_viscosity
from ccs_costs.costs.pipeline import pipeline_diameter

mcp = FastMCP("ccs-cost-model")


# ============================================================================
# Essential v1 tools
# ============================================================================


@mcp.tool
def estimate_storage_cost(
    formation: str,
    region: str,
    injection_rate_mtpa: float = 3.0,
    operations_years: int | None = None,
    infrastructure: str | None = None,
) -> dict:
    """Estimate break-even CO2 storage cost (FYBE) for a formation.

    Runs the full calculation chain: thermodynamics, geology, costs, finance.
    Returns the first-year break-even price and key project parameters.

    Args:
        formation: Formation ID (e.g. '1241_1' for US-GOA).
        region: Region identifier (e.g. 'us-goa', 'norway-ncs').
        injection_rate_mtpa: CO2 injection rate in million tonnes per year.
        operations_years: Override for injection period length.
        infrastructure: Override infrastructure model ('platform_jacket' or 'subsea_tieback').

    Returns:
        Dict with ~15 key fields: fybe, well count, pipeline specs, costs.
    """
    config = ScenarioConfig(
        formation_id=formation,
        region=region,
        injection_rate_tpa=injection_rate_mtpa * 1_000_000,
        operations_years=operations_years,
        infrastructure_model=infrastructure,
    )

    results = evaluate_scenario(config)

    # Save to history (best effort -- don't fail the tool if history save fails)
    try:
        history_mod.save_scenario(config, results)
    except Exception:
        pass

    return results.to_compact_dict()


@mcp.tool
def co2_properties(
    pressure_mpa: float,
    temperature_c: float,
    method: str = "duan",
) -> dict:
    """Get CO2 thermophysical properties at given conditions.

    Pure thermodynamic lookup -- no region parameter needed.

    Args:
        pressure_mpa: Pressure in MPa.
        temperature_c: Temperature in degrees Celsius.
        method: EOS method ('duan' or 'peng-robinson').

    Returns:
        Dict with pressure, temperature, density, viscosity, compressibility, method.
    """
    density = co2_density(pressure_mpa, temperature_c, method=method)
    viscosity = co2_viscosity(density, temperature_c)
    compressibility = co2_compressibility(pressure_mpa, temperature_c)

    return {
        "pressure_mpa": pressure_mpa,
        "temperature_c": temperature_c,
        "density_kgm3": round(density, 4),
        "viscosity_pas": viscosity,
        "compressibility_z": round(compressibility, 6),
        "method": method,
    }


@mcp.tool
def calculate_pipeline(
    flow_rate_mtpa: float,
    distance_km: float,
    region: str,
    inlet_pressure_mpa: float = 15.0,
    outlet_pressure_mpa: float = 8.0,
    temperature_c: float = 4.0,
) -> dict:
    """Size a CO2 pipeline and estimate costs.

    Computes CO2 properties at pipeline conditions, then determines
    the minimum pipeline diameter using Darcy-Weisbach hydraulics.

    Args:
        flow_rate_mtpa: CO2 flow rate in million tonnes per year.
        distance_km: Pipeline length in km.
        region: Region identifier for cost model selection.
        inlet_pressure_mpa: Pipeline inlet pressure (MPa).
        outlet_pressure_mpa: Pipeline outlet pressure (MPa).
        temperature_c: Pipeline temperature (Celsius).

    Returns:
        Dict with diameter_inches, velocity, flow details.
    """
    # CO2 properties at pipeline conditions
    avg_pressure = (inlet_pressure_mpa + outlet_pressure_mpa) / 2.0
    density = co2_density(avg_pressure, temperature_c, method="duan")
    viscosity = co2_viscosity(density, temperature_c)

    flow_rate_tpa = flow_rate_mtpa * 1_000_000

    dia_result = pipeline_diameter(
        flow_rate_tpa=flow_rate_tpa,
        length_km=distance_km,
        inlet_pressure_mpa=inlet_pressure_mpa,
        outlet_pressure_mpa=outlet_pressure_mpa,
        temperature_c=temperature_c,
        co2_density_kgm3=density,
        co2_viscosity_pas=viscosity,
    )

    # Compute velocity from flow rate and nominal diameter
    import math
    nominal_d_m = dia_result["nominal_diameter_inches"] * 0.0254
    area_m2 = math.pi / 4 * nominal_d_m**2
    velocity_ms = dia_result["flow_rate_kgs"] / density / area_m2

    return {
        "diameter_inches": dia_result["nominal_diameter_inches"],
        "diameter_min_inches": round(dia_result["min_diameter_inches"], 2),
        "velocity_ms": round(velocity_ms, 3),
        "flow_rate_mtpa": flow_rate_mtpa,
        "distance_km": distance_km,
        "co2_density_kgm3": round(density, 1),
        "region": region,
    }


@mcp.tool
def get_scenario_history(
    region: str | None = None,
    formation_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Retrieve recent scenario results from SQLite history.

    Args:
        region: Filter by region (optional).
        formation_id: Filter by formation ID (optional).
        limit: Maximum results to return (default 20).

    Returns:
        List of scenario summaries with id, timestamp, region, formation_id, fybe.
    """
    return history_mod.query_history(
        region=region,
        formation_id=formation_id,
        limit=limit,
    )


# ============================================================================
# Discovery tools
# ============================================================================


@mcp.tool
def list_regions() -> list[dict]:
    """List available regions with summary info.

    Returns:
        List of dicts with name, currency, base_year, formation_count.
    """
    regions = list_available_regions()
    result = []
    for r in regions:
        try:
            rc = load_region(r)
            result.append({
                "name": rc.name,
                "currency": rc.currency,
                "base_year": rc.base_year,
                "formation_count": len(rc.formations),
            })
        except Exception:
            result.append({
                "name": r,
                "currency": "unknown",
                "base_year": 0,
                "formation_count": 0,
            })
    return result


@mcp.tool
def list_formations(region: str) -> list[dict]:
    """List available formations with key properties.

    Args:
        region: Region identifier (e.g. 'us-goa', 'norway-ncs').

    Returns:
        List of dicts with id, name, depth, porosity, permeability for each formation.
    """
    rc = load_region(region)
    result = []
    for fid, fp in rc.formations.items():
        result.append({
            "id": fid,
            "name": fp.name,
            "depth_m": fp.depth_m,
            "porosity": fp.porosity,
            "permeability_md": fp.permeability_md,
            "thickness_m": fp.thickness_m,
            "water_depth_m": fp.water_depth_m,
        })
    return result


@mcp.tool
def compare_formations(
    formations: list[str],
    region: str,
    injection_rate_mtpa: float = 3.0,
) -> list[dict]:
    """Compare storage costs across multiple formations, sorted by FYBE.

    Evaluates each formation and returns results sorted cheapest first.

    Args:
        formations: List of formation IDs to compare.
        region: Region identifier.
        injection_rate_mtpa: CO2 injection rate in Mt/yr.

    Returns:
        List of compact result dicts sorted by FYBE ascending.
    """
    results = []
    for fid in formations:
        try:
            config = ScenarioConfig(
                formation_id=fid,
                region=region,
                injection_rate_tpa=injection_rate_mtpa * 1_000_000,
            )
            scenario_results = evaluate_scenario(config)

            # Save to history (best effort)
            try:
                history_mod.save_scenario(config, scenario_results)
            except Exception:
                pass

            results.append(scenario_results.to_compact_dict())
        except Exception as e:
            results.append({
                "formation_id": fid,
                "error": str(e),
                "fybe": float("inf"),
            })

    # Sort by FYBE ascending (cheapest first), errors at end
    results.sort(key=lambda r: r.get("fybe", float("inf")))
    return results


# ============================================================================
# Phase 6 stub tools
# ============================================================================


@mcp.tool
def run_sensitivity(
    formation: str,
    region: str,
    parameter_ranges: dict,
    parameter: str | None = None,
    steps: int = 7,
) -> dict:
    """Sensitivity analysis on formation economics.

    Two modes:
    - One-way (parameter specified): sweeps a single parameter across its range.
    - Tornado (parameter omitted): sweeps all parameters in parameter_ranges and ranks by impact.

    Args:
        formation: Formation ID.
        region: Region identifier.
        parameter_ranges: Dict of {param_name: [min_value, max_value]}. Caller specifies bounds.
        parameter: If specified, runs one-way sensitivity for this parameter only.
                   If omitted, runs tornado analysis across all parameters in parameter_ranges.
        steps: Number of sweep steps per parameter (default 7).

    Supported parameters:
        Geological: porosity, permeability_md, depth_m, thickness_m, area_km2, net_to_gross,
                    temperature_c, pressure_mpa (and short aliases without unit suffix)
        Economic: injection_rate_mtpa, operations_years, ets_price, co2_tax_rate

    Returns:
        One-way mode: {"mode": "one_way", "formation": str, "region": str,
                       "parameter": str, "steps": list[{param_value, fybe}]}
        Tornado mode: {"mode": "tornado", "formation": str, "region": str,
                       "parameters": list[{parameter, swing, fybe_at_low, fybe_base, fybe_at_high}]}
    """
    from ccs_costs.analysis import run_one_way_sensitivity, run_tornado_sensitivity

    if parameter is not None:
        # One-way mode
        if parameter not in parameter_ranges:
            return {"error": f"parameter '{parameter}' not in parameter_ranges"}
        bounds = parameter_ranges[parameter]
        results = run_one_way_sensitivity(
            formation_id=formation,
            region=region,
            parameter=parameter,
            min_value=bounds[0],
            max_value=bounds[1],
            steps=steps,
        )
        return {
            "mode": "one_way",
            "formation": formation,
            "region": region,
            "parameter": parameter,
            "steps": results,
        }
    else:
        # Tornado mode
        tornado = run_tornado_sensitivity(
            formation_id=formation,
            region=region,
            parameter_ranges=parameter_ranges,
            steps=steps,
        )
        return {
            "mode": "tornado",
            "formation": formation,
            "region": region,
            "parameters": tornado,
        }


@mcp.tool
def run_supply_curve(
    region: str,
    injection_rate_mtpa: float,
) -> dict:
    """Evaluate all formations in a region and rank by FYBE (cheapest first).

    Failed formations are appended at the end with fybe=null and error field.
    Nothing is silently dropped.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").
        injection_rate_mtpa: Target CO2 injection rate in Mt/yr.

    Returns:
        Dict with formations list (sorted by fybe asc, failures at end) and summary.
        Per formation: formation_id, formation_name, fybe, well_count,
                       capex_musd, opex_musd, storage_capacity_gt.
        Failures have fybe=null and error field instead.
        Summary: total, evaluated, failed, fybe_min, fybe_max, fybe_median.
    """
    from ccs_costs.analysis import run_supply_curve as _run_supply_curve
    return _run_supply_curve(region=region, injection_rate_mtpa=injection_rate_mtpa)


@mcp.tool
def run_monte_carlo(
    formation: str,
    region: str,
    n_samples: int = 1000,
    uncertainty_config: dict | None = None,
    seed: int = 42,
) -> dict:
    """Probabilistic FYBE analysis via Monte Carlo simulation.

    Samples parameter distributions from data/regions/{region}/uncertainty.yaml.
    Uses multiprocessing (ProcessPoolExecutor) for performance -- 1000 samples
    typically completes in approximately 100-120 seconds.

    Args:
        formation: Formation ID.
        region: Region identifier.
        n_samples: Number of Monte Carlo samples (default 1000).
        uncertainty_config: Optional per-parameter distribution overrides.
        seed: RNG seed for reproducibility (default 42).

    Returns:
        Dict with p10, p50, p90, mean, std_dev, min, max, n_success, n_failed, seed.
    """
    from ccs_costs.analysis import run_monte_carlo as _run_monte_carlo
    return _run_monte_carlo(
        formation_id=formation,
        region=region,
        n_samples=n_samples,
        uncertainty_config=uncertainty_config,
        seed=seed,
    )


# ============================================================================
# Entry point
# ============================================================================


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()

"""Analysis module -- sensitivity analysis, supply curve, and Monte Carlo functions.

Provides:
    run_one_way_sensitivity()  -- sweep a single parameter, return FYBE vs. value
    run_tornado_sensitivity()  -- sweep all parameters, rank by FYBE swing
    run_supply_curve()         -- evaluate all formations in a region, rank by FYBE
    run_monte_carlo()          -- probabilistic FYBE analysis via Monte Carlo sampling

These functions wrap evaluate_scenario() with formation_overrides and
economic_overrides, enabling systematic parameter studies without modifying
formation data or region config.

Design decisions:
    - Sensitivity: sequential evaluation -- 19.4s sequential is within 60s target
    - Monte Carlo: ProcessPoolExecutor(8 workers) -- bypasses GIL for CPU-bound cashflow
    - Error isolation per formation/parameter -- one failure doesn't abort the run
    - PARAM_ALIASES maps short names to FormationProperties field names
    - _build_override_config merges overrides rather than replacing them
"""

from __future__ import annotations

import statistics
import yaml
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ccs_costs.scenario import ScenarioConfig, evaluate_scenario
from ccs_costs.config import load_region
from ccs_costs.geo.formations import get_formation


# ============================================================================
# Parameter routing constants
# ============================================================================

GEOLOGICAL_PARAMS = {
    "porosity",
    "permeability_md",
    "permeability",
    "depth_m",
    "depth",
    "thickness_m",
    "thickness",
    "area_km2",
    "area",
    "net_to_gross",
    "temperature_c",
    "temperature",
    "pressure_mpa",
    "pressure",
}

SCENARIO_PARAMS = {"injection_rate_tpa", "operations_years"}
ECONOMIC_PARAMS = {"ets_price", "co2_tax_rate"}

# Canonical name mapping: short aliases -> full field names in FormationProperties
PARAM_ALIASES = {
    "permeability": "permeability_md",
    "depth": "depth_m",
    "thickness": "thickness_m",
    "area": "area_km2",
    "temperature": "temperature_c",
    "pressure": "pressure_mpa",
}


# ============================================================================
# Internal helpers
# ============================================================================


def _build_override_config(
    base_config: ScenarioConfig,
    param: str,
    value: float,
) -> ScenarioConfig:
    """Build a ScenarioConfig with a single parameter overridden.

    Merges with any existing overrides in base_config rather than replacing them.

    Args:
        base_config: Base scenario configuration.
        param: Parameter name (may be a short alias).
        value: New value for the parameter.

    Returns:
        New ScenarioConfig with the override applied.
    """
    # Resolve alias
    resolved = PARAM_ALIASES.get(param, param)

    if resolved in GEOLOGICAL_PARAMS or param in GEOLOGICAL_PARAMS:
        # Apply via formation_overrides, merging with any existing
        existing = base_config.formation_overrides or {}
        merged = {**existing, resolved: value}
        return base_config.model_copy(update={"formation_overrides": merged})

    elif param == "injection_rate_mtpa":
        return base_config.model_copy(update={"injection_rate_tpa": value * 1e6})

    elif param == "operations_years":
        return base_config.model_copy(update={"operations_years": int(value)})

    elif param in ECONOMIC_PARAMS:
        # Apply via economic_overrides, merging with any existing
        existing = base_config.economic_overrides or {}
        merged = {**existing, param: value}
        return base_config.model_copy(update={"economic_overrides": merged})

    else:
        # Unknown parameter -- try as formation override (best-effort)
        existing = base_config.formation_overrides or {}
        merged = {**existing, param: value}
        return base_config.model_copy(update={"formation_overrides": merged})


# ============================================================================
# Public API
# ============================================================================


def run_one_way_sensitivity(
    formation_id: str,
    region: str,
    parameter: str,
    min_value: float,
    max_value: float,
    steps: int = 7,
) -> list[dict]:
    """Sweep a single parameter across a range and return FYBE at each step.

    Args:
        formation_id: Formation ID to evaluate.
        region: Region identifier.
        parameter: Parameter name to vary (geological, scenario, or economic).
        min_value: Minimum parameter value.
        max_value: Maximum parameter value.
        steps: Number of evenly-spaced steps (default 7).

    Returns:
        List of dicts with keys:
            - param_value (float): The parameter value at this step.
            - fybe (float | None): FYBE result, or None if evaluation failed.
            - error (str): Error message, only present on failure.
    """
    base_config = ScenarioConfig(formation_id=formation_id, region=region)
    sweep_values = np.linspace(min_value, max_value, steps)
    results = []

    for val in sweep_values:
        try:
            config = _build_override_config(base_config, parameter, float(val))
            result = evaluate_scenario(config)
            results.append({"param_value": float(val), "fybe": result.fybe})
        except Exception as exc:
            results.append({
                "param_value": float(val),
                "fybe": None,
                "error": str(exc),
            })

    return results


def run_tornado_sensitivity(
    formation_id: str,
    region: str,
    parameter_ranges: dict[str, list[float]],
    steps: int = 7,
) -> list[dict]:
    """Sweep all parameters in parameter_ranges and rank by FYBE swing.

    For each parameter, runs run_one_way_sensitivity at min and max values
    (using the full sweep with `steps` points), computes the FYBE swing
    (max - min of successful results), and returns results sorted by swing
    descending (largest impact first).

    Args:
        formation_id: Formation ID to evaluate.
        region: Region identifier.
        parameter_ranges: Dict of {param_name: [min_value, max_value]}.
        steps: Number of sweep steps per parameter (default 7).

    Returns:
        List of dicts sorted by swing descending:
            - parameter (str): Parameter name.
            - swing (float): max(fybe) - min(fybe) across the sweep.
            - fybe_at_low (float): FYBE at parameter minimum value.
            - fybe_base (float): FYBE with no overrides (baseline).
            - fybe_at_high (float): FYBE at parameter maximum value.
    """
    # Get baseline FYBE (no overrides)
    base_config = ScenarioConfig(formation_id=formation_id, region=region)
    try:
        base_result = evaluate_scenario(base_config)
        fybe_base = base_result.fybe
    except Exception:
        fybe_base = float("nan")

    tornado_entries = []

    for param, (min_val, max_val) in parameter_ranges.items():
        sweep = run_one_way_sensitivity(
            formation_id=formation_id,
            region=region,
            parameter=param,
            min_value=min_val,
            max_value=max_val,
            steps=steps,
        )
        successful = [r for r in sweep if r.get("fybe") is not None]
        if not successful:
            # All evaluations failed for this parameter
            tornado_entries.append({
                "parameter": param,
                "swing": 0.0,
                "fybe_at_low": float("nan"),
                "fybe_base": fybe_base,
                "fybe_at_high": float("nan"),
            })
            continue

        fybe_values = [r["fybe"] for r in successful]
        swing = max(fybe_values) - min(fybe_values)

        # fybe_at_low: FYBE at the minimum parameter value (first sweep point)
        fybe_at_low_entry = next(
            (r for r in sweep if r["param_value"] == min_val and r.get("fybe") is not None),
            successful[0],
        )
        # fybe_at_high: FYBE at the maximum parameter value (last sweep point)
        fybe_at_high_entry = next(
            (r for r in sweep if r["param_value"] == max_val and r.get("fybe") is not None),
            successful[-1],
        )

        tornado_entries.append({
            "parameter": param,
            "swing": swing,
            "fybe_at_low": fybe_at_low_entry["fybe"],
            "fybe_base": fybe_base,
            "fybe_at_high": fybe_at_high_entry["fybe"],
        })

    # Sort by swing descending (largest impact first)
    tornado_entries.sort(key=lambda e: e["swing"], reverse=True)
    return tornado_entries


def run_supply_curve(
    region: str,
    injection_rate_mtpa: float,
) -> dict:
    """Evaluate all formations in a region and rank by FYBE (cheapest first).

    Runs evaluate_scenario for each formation with error isolation.
    Failed formations are appended at the end with fybe=None and an error field.
    Nothing is silently dropped.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").
        injection_rate_mtpa: Target CO2 injection rate in Mt/yr.

    Returns:
        Dict with:
            - region (str): Region identifier.
            - injection_rate_mtpa (float): Injection rate used.
            - formations (list[dict]): Successes sorted by fybe ascending,
              then failures at end. Each entry has:
                formation_id, formation_name, fybe, well_count,
                capex_musd, opex_musd, storage_capacity_gt
              Failures have fybe=None and error field instead.
            - summary (dict): total, evaluated, failed, fybe_min, fybe_max,
              fybe_median.
    """
    region_config = load_region(region)
    formation_ids = list(region_config.formations.keys())
    injection_rate_tpa = injection_rate_mtpa * 1e6

    successes = []
    failures = []

    for fid in formation_ids:
        # Try to get formation name even if evaluation fails
        try:
            formation_props = region_config.formations[fid]
            formation_name = formation_props.name
        except Exception:
            formation_name = fid

        try:
            config = ScenarioConfig(
                formation_id=fid,
                region=region,
                injection_rate_tpa=injection_rate_tpa,
            )
            result = evaluate_scenario(config)
            successes.append({
                "formation_id": fid,
                "formation_name": result.formation_name,
                "fybe": result.fybe,
                "well_count": result.n_injection_wells,
                "capex_musd": result.total_capex / 1e6,
                "opex_musd": result.total_opex / 1e6,
                "storage_capacity_gt": result.total_co2_stored_mt / 1000,
            })
        except Exception as exc:
            failures.append({
                "formation_id": fid,
                "formation_name": formation_name,
                "fybe": None,
                "error": str(exc),
            })

    # Sort successes by fybe ascending (cheapest first)
    successes.sort(key=lambda f: f["fybe"])

    # Build summary
    fybe_values = [f["fybe"] for f in successes]
    summary = {
        "total": len(successes) + len(failures),
        "evaluated": len(successes),
        "failed": len(failures),
        "fybe_min": min(fybe_values) if fybe_values else None,
        "fybe_max": max(fybe_values) if fybe_values else None,
        "fybe_median": float(np.median(fybe_values)) if fybe_values else None,
    }

    return {
        "region": region,
        "injection_rate_mtpa": injection_rate_mtpa,
        "formations": successes + failures,
        "summary": summary,
    }


# ============================================================================
# Monte Carlo simulation
# ============================================================================


def _load_uncertainty_config(region: str, caller_overrides: dict | None = None) -> dict:
    """Load uncertainty distributions from data/regions/{region}/uncertainty.yaml.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").
        caller_overrides: Optional dict to override per-parameter distributions.
            If provided, caller_overrides[param] replaces the YAML entry for that param.

    Returns:
        Dict of {param_name: {distribution, relative, min, ...}} specs.
        Returns {} if uncertainty.yaml does not exist.
    """
    path = Path("data/regions") / region / "uncertainty.yaml"
    if not path.exists():
        return {}

    spec = yaml.safe_load(path.read_text())
    distributions = dict(spec.get("parameters", {}))

    if caller_overrides:
        distributions.update(caller_overrides)

    return distributions


def _sample_distribution(rng: "np.random.Generator", spec: dict, base_value: float) -> float:
    """Sample a value from a distribution specification.

    Args:
        rng: NumPy random Generator (seeded).
        spec: Distribution spec dict with 'distribution', 'relative', and distribution params.
        base_value: Base value for relative distributions (multiplied by sampled factor).

    Returns:
        Sampled parameter value.

    Raises:
        ValueError: If distribution type is unknown.
    """
    distribution = spec["distribution"]
    relative = spec.get("relative", True)

    if distribution == "triangular":
        left = spec["min"]
        mode = spec.get("mode", 1.0)
        right = spec["max"]
        factor = rng.triangular(left, mode, right)
        return base_value * factor if relative else factor

    elif distribution == "uniform":
        low = spec["min"]
        high = spec["max"]
        sample = rng.uniform(low, high)
        return base_value * sample if relative else sample

    elif distribution == "normal":
        mean_val = spec.get("mean", 1.0)
        std_val = spec["std"]
        factor = rng.normal(mean_val, std_val)
        # Clip to optional bounds
        min_bound = spec.get("min", 0.01)
        max_bound = spec.get("max", float("inf"))
        factor = max(min_bound, min(max_bound, factor))
        return base_value * factor if relative else factor

    elif distribution == "lognormal":
        mean_val = spec.get("mean", 0.0)
        sigma_val = spec["sigma"]
        factor = rng.lognormal(mean_val, sigma_val)
        min_bound = spec.get("min", 0.0)
        max_bound = spec.get("max", float("inf"))
        factor = max(min_bound, min(max_bound, factor))
        return base_value * factor if relative else factor

    else:
        raise ValueError(f"Unknown distribution type: '{distribution}'. "
                         f"Supported: triangular, uniform, normal, lognormal.")


def run_monte_carlo(
    formation_id: str,
    region: str,
    n_samples: int = 1000,
    uncertainty_config: dict | None = None,
    seed: int = 42,
) -> dict:
    """Probabilistic FYBE analysis using Monte Carlo sampling.

    Samples parameter distributions defined in data/regions/{region}/uncertainty.yaml.
    Uses ProcessPoolExecutor(max_workers=8) to bypass the GIL for CPU-bound cashflow
    evaluations.

    Args:
        formation_id: Formation ID (base case for relative distributions).
        region: Region identifier.
        n_samples: Number of Monte Carlo samples (default 1000).
        uncertainty_config: Optional dict to override region uncertainty.yaml per-parameter.
        seed: RNG seed for reproducibility (default 42).

    Returns:
        Dict with p10, p50, p90, mean, std_dev, min, max, n_success, n_failed, seed,
        formation_id, region, n_samples.
    """
    rng = np.random.default_rng(seed)
    distributions = _load_uncertainty_config(region, uncertainty_config)

    # Load base formation to get base values for relative distributions.
    # Note: get_formation signature is get_formation(region, formation_id).
    formation = get_formation(region, formation_id)
    base_config = ScenarioConfig(formation_id=formation_id, region=region)

    configs = []
    for _ in range(n_samples):
        geo_overrides: dict = {}
        eco_overrides: dict = {}
        scenario_updates: dict = {}

        for param, spec in distributions.items():
            resolved = PARAM_ALIASES.get(param, param)

            if param in GEOLOGICAL_PARAMS or resolved in GEOLOGICAL_PARAMS:
                # Geological parameter -> formation_overrides
                base_val = getattr(formation, resolved, None)
                if base_val is None or base_val == 0:
                    continue
                sampled = _sample_distribution(rng, spec, float(base_val))
                geo_overrides[resolved] = sampled

            elif param == "injection_rate_mtpa":
                base_val = base_config.injection_rate_tpa / 1e6
                sampled = _sample_distribution(rng, spec, float(base_val))
                scenario_updates["injection_rate_tpa"] = sampled * 1e6

            elif param == "operations_years":
                base_val = float(base_config.operations_years or 30)
                sampled = _sample_distribution(rng, spec, base_val)
                scenario_updates["operations_years"] = max(1, int(round(sampled)))

            elif param in ECONOMIC_PARAMS:
                # Economic parameter -> economic_overrides
                # For absolute distributions, base_val is irrelevant (relative=False in spec).
                # For relative, use 1.0 as the multiplier base (economic_overrides stores raw values).
                base_val = 1.0
                sampled = _sample_distribution(rng, spec, base_val)
                eco_overrides[param] = sampled

        config = base_config.model_copy(update={
            "formation_overrides": geo_overrides if geo_overrides else None,
            "economic_overrides": eco_overrides if eco_overrides else None,
            **scenario_updates,
        })
        configs.append(config)

    # Evaluate in parallel using ProcessPoolExecutor.
    # ProcessPool bypasses GIL -- required for CPU-bound cashflow model.
    # On Windows, spawned processes import the module directly (no fork).
    fybe_values: list[float] = []
    n_failed = 0

    try:
        with ProcessPoolExecutor(max_workers=8) as executor:
            raw_results = list(executor.map(evaluate_scenario, configs, chunksize=50))
    except Exception:
        # Fall back to sequential if ProcessPool fails (e.g., import error in worker)
        raw_results = [evaluate_scenario(c) for c in configs]

    for r in raw_results:
        if r is not None:
            try:
                fybe_values.append(r.fybe)
            except AttributeError:
                n_failed += 1
        else:
            n_failed += 1

    if not fybe_values:
        return {
            "error": "All Monte Carlo evaluations failed",
            "n_failed": n_samples,
            "seed": seed,
        }

    fybe_sorted = sorted(fybe_values)
    n = len(fybe_sorted)

    return {
        "p10": fybe_sorted[max(0, int(0.10 * n))],
        "p50": fybe_sorted[max(0, int(0.50 * n))],
        "p90": fybe_sorted[min(n - 1, int(0.90 * n))],
        "mean": sum(fybe_sorted) / n,
        "std_dev": float(np.std(fybe_sorted)),
        "min": fybe_sorted[0],
        "max": fybe_sorted[-1],
        "n_success": n,
        "n_failed": n_failed,
        "seed": seed,
        "formation_id": formation_id,
        "region": region,
        "n_samples": n_samples,
    }

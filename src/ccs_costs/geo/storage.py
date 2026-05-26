"""Storage coefficient lookup from IEA GHG 2009/12 table.

Storage efficiency factor E = fraction of pore volume occupied by CO2.
Depends on lithology, depositional environment, structure type, and
probability level (P10/P50/P90).

Source: IEA GHG 2009/12, "Development of Storage Coefficients for
CO2 Storage in Deep Saline Formations"

The lookup table is universal (physics-based, not region-specific).
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ccs_costs.geo.formations import FormationProperties

# Reference data path
_DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "reference" / "storage_coefficients.json"

# Module-level lazy-loaded cache
_COEFFICIENTS: dict[str, dict[str, float]] | None = None

# Aliases map Norwegian/European geological terms to NETL lookup keys.
# The IEA GHG 2009 table uses specific NETL terminology; Norwegian
# formation data uses broader geological terms that need mapping.

_LITHOLOGY_ALIASES: dict[str, str] = {
    "sandstone": "clastic",
    "sand": "clastic",
    "shale": "clastic",
    "siltstone": "clastic",
    "chalk": "carbonate",
}

_ENVIRONMENT_ALIASES: dict[str, str] = {
    "deep_shelf": "shelf",
    "deep shelf": "shelf",
    "marine_shelf": "shelf",
    "marine shelf": "shelf",
    "continental_shelf": "shelf",
    "turbidite": "slope basin",
    "submarine_fan": "slope basin",
    "coastal": "strandplain",
    "barrier": "strandplain",
}

_STRUCTURE_ALIASES: dict[str, str] = {
    "regional_dip": "reg_dip",
    "open": "reg_dip",
    "monocline": "reg_dip",
    "structural_trap": "anticline",
    "stratigraphic_trap": "dome",
    "fault_block": "anticline",
}


class StorageCoefficientMethod(str, Enum):
    """Method for determining storage coefficient."""

    LOOKUP = "lookup"
    USER = "user"


def _load_coefficients() -> dict[str, dict[str, float]]:
    """Load storage coefficients from JSON reference data.

    Returns:
        Dict keyed by lowercase "{lithology}-{dep_env}-{structure}"
        with values {"p10": float, "p50": float, "p90": float}.
    """
    global _COEFFICIENTS

    if _COEFFICIENTS is not None:
        return _COEFFICIENTS

    with open(_DATA_PATH) as f:
        data = json.load(f)

    coefficients: dict[str, dict[str, float]] = {}
    for entry in data["coefficients"]:
        key = entry["lookup_key"].lower()
        coefficients[key] = {
            "p10": entry["p10"],
            "p50": entry["p50"],
            "p90": entry["p90"],
        }

    _COEFFICIENTS = coefficients
    return _COEFFICIENTS


def storage_coefficient(
    lithology: str,
    depositional_environment: str,
    structure_type: str,
    probability: str = "P50",
    method: StorageCoefficientMethod = StorageCoefficientMethod.LOOKUP,
    user_value: float | None = None,
) -> float:
    """Look up storage efficiency coefficient.

    Args:
        lithology: Rock type (clastic, limestone, carbonate, dolomite).
        depositional_environment: Depositional setting (shallow shelf, delta, etc.).
        structure_type: Structural setting (anticline, dome, reg_dip, etc.).
        probability: Probability level - "P10", "P50", or "P90".
        method: Lookup method (LOOKUP or USER).
        user_value: User-specified value (required if method=USER).

    Returns:
        Storage efficiency coefficient (dimensionless, typically 0.01-0.25).

    Raises:
        ValueError: If combination not found or user_value missing.
    """
    if method == StorageCoefficientMethod.USER:
        if user_value is None:
            raise ValueError(
                "user_value must be provided when method is USER. "
                "Pass a float value for the storage coefficient."
            )
        return user_value

    coefficients = _load_coefficients()

    # Normalize inputs to lowercase, apply aliases
    lith_lower = lithology.lower()
    lith_lower = _LITHOLOGY_ALIASES.get(lith_lower, lith_lower)
    env_lower = depositional_environment.lower()
    env_lower = _ENVIRONMENT_ALIASES.get(env_lower, env_lower)
    struct_lower = structure_type.lower()
    struct_lower = _STRUCTURE_ALIASES.get(struct_lower, struct_lower)
    key = f"{lith_lower}-{env_lower}-{struct_lower}"
    prob_key = probability.lower()

    if prob_key not in ("p10", "p50", "p90"):
        raise ValueError(
            f"Invalid probability '{probability}'. Must be one of: P10, P50, P90"
        )

    if key not in coefficients:
        # Collect available options for helpful error message
        available_lithologies = sorted({k.split("-")[0] for k in coefficients})
        available_envs = sorted({k.split("-")[1] for k in coefficients})
        available_structs = sorted({k.split("-")[2] for k in coefficients})
        raise ValueError(
            f"Storage coefficient not found for key '{key}'.\n"
            f"  Available lithologies: {available_lithologies}\n"
            f"  Available environments: {available_envs}\n"
            f"  Available structures: {available_structs}"
        )

    return coefficients[key][prob_key]


def get_coefficient_for_formation(
    formation: FormationProperties,
    probability: str = "P50",
) -> float:
    """Convenience function to get storage coefficient from a FormationProperties.

    Extracts lithology, depositional_environment, and structure_type from
    the formation and calls storage_coefficient.

    Args:
        formation: FormationProperties instance.
        probability: Probability level - "P10", "P50", or "P90".

    Returns:
        Storage efficiency coefficient.
    """
    return storage_coefficient(
        lithology=formation.lithology,
        depositional_environment=formation.depositional_environment,
        structure_type=formation.structure_type,
        probability=probability,
    )

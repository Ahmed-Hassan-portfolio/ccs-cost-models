"""Formation database loader with SI-unit Pydantic models.

Loads geological formation data from regional JSON files, validates via
Pydantic, and provides lookup/search functionality.

Data sources:
    - us-goa: 117 Gulf of America formations from NETL CO2_S_COM Offshore v1.1
    - norway-ncs: Norwegian Continental Shelf (future)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, computed_field

# Package data root: src/ccs_costs/geo/formations.py -> data/regions/
_DATA_ROOT = Path(__file__).parent.parent.parent.parent / "data" / "regions"

# Module-level cache: region -> dict[str, FormationProperties]
_CACHE: dict[str, dict[str, FormationProperties]] = {}


class FormationProperties(BaseModel):
    """Geological formation properties for CO2 storage assessment.

    All values in SI units:
        - Depths/thicknesses in metres
        - Temperature in Celsius
        - Pressure in MPa
        - Permeability in millidarcies
        - Salinity in mg/L (ppm)
        - Distances in km
    """

    id: str
    name: str
    depth_m: float = Field(gt=0)
    thickness_m: float = Field(gt=0)
    net_to_gross: float = Field(gt=0, le=1, default=1.0)
    porosity: float = Field(gt=0, lt=1)
    permeability_md: float = Field(gt=0)
    temperature_c: float
    pressure_mpa: float = Field(gt=0)
    salinity_ppm: float = Field(ge=0, default=35000)
    water_depth_m: float = Field(ge=0, default=0)
    distance_from_shore_km: float = Field(ge=0, default=0)
    lithology: str = "clastic"
    depositional_environment: str = "deltaic"
    structure_type: str = "regional_dip"
    fracture_pressure_mpa: Optional[float] = None
    area_km2: Optional[float] = None
    capacity_mt: Optional[float] = None  # Total CO2 storage capacity in megatonnes
    seal_formation: Optional[str] = None

    # Area-dependent monitoring parameters (from NETL Res_Bas1)
    seismic_3d_mi2: Optional[float] = None  # Maximum 3D seismic survey area (mi²)
    seismic_2d_mi: Optional[float] = None   # Maximum 2D seismic line length (mi)
    corrective_action_wells: Optional[int] = None  # Number of corrective action wells

    # US-GOA metadata fields
    formation_number: Optional[int] = None
    protraction: Optional[str] = None
    basin: Optional[str] = None
    state: Optional[str] = None
    planning_area: Optional[str] = None
    geologic_age: Optional[str] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_thickness_m(self) -> float:
        """Net thickness = gross thickness * net-to-gross ratio."""
        return self.thickness_m * self.net_to_gross


def load_formations(region: str) -> dict[str, FormationProperties]:
    """Load all formations for a region.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").

    Returns:
        Dict mapping formation ID to FormationProperties.

    Raises:
        FileNotFoundError: If region data file doesn't exist.
        ValidationError: If any formation fails Pydantic validation.
    """
    if region in _CACHE:
        return _CACHE[region]

    data_path = _DATA_ROOT / region / "formations.json"
    if not data_path.exists():
        raise FileNotFoundError(
            f"No formation data for region '{region}'. "
            f"Expected file: {data_path}"
        )

    with open(data_path) as f:
        data = json.load(f)

    formations: dict[str, FormationProperties] = {}
    for entry in data["formations"]:
        fp = FormationProperties(**entry)
        formations[fp.id] = fp

    _CACHE[region] = formations
    return formations


def get_formation(region: str, formation_id: str) -> FormationProperties:
    """Look up a single formation by ID.

    Args:
        region: Region identifier.
        formation_id: Formation ID (e.g., "1241_1").

    Returns:
        FormationProperties for the requested formation.

    Raises:
        ValueError: If formation_id not found, with list of available IDs.
    """
    formations = load_formations(region)
    if formation_id not in formations:
        available = sorted(formations.keys())
        # Show first 10 IDs to keep error message manageable
        preview = available[:10]
        suffix = f" ... ({len(available)} total)" if len(available) > 10 else ""
        raise ValueError(
            f"Formation '{formation_id}' not found in region '{region}'. "
            f"Available IDs: {preview}{suffix}"
        )
    return formations[formation_id]


def search_formations(region: str, **filters: object) -> list[FormationProperties]:
    """Filter formations by property ranges.

    Supported filters:
        min_depth_m, max_depth_m: Depth range (metres)
        min_porosity, max_porosity: Porosity range (fraction)
        min_permeability_md, max_permeability_md: Permeability range
        lithology: Exact match (case-insensitive)
        depositional_environment: Exact match (case-insensitive)

    Returns:
        List of matching FormationProperties, sorted by ID.
    """
    formations = load_formations(region)
    results: list[FormationProperties] = []

    min_depth = filters.get("min_depth_m")
    max_depth = filters.get("max_depth_m")
    min_porosity = filters.get("min_porosity")
    max_porosity = filters.get("max_porosity")
    min_perm = filters.get("min_permeability_md")
    max_perm = filters.get("max_permeability_md")
    lithology_filter = filters.get("lithology")
    dep_env_filter = filters.get("depositional_environment")

    for f in formations.values():
        if min_depth is not None and f.depth_m < min_depth:
            continue
        if max_depth is not None and f.depth_m > max_depth:
            continue
        if min_porosity is not None and f.porosity < min_porosity:
            continue
        if max_porosity is not None and f.porosity > max_porosity:
            continue
        if min_perm is not None and f.permeability_md < min_perm:
            continue
        if max_perm is not None and f.permeability_md > max_perm:
            continue
        if lithology_filter is not None and f.lithology.lower() != str(lithology_filter).lower():
            continue
        if dep_env_filter is not None and f.depositional_environment.lower() != str(dep_env_filter).lower():
            continue
        results.append(f)

    return sorted(results, key=lambda x: x.id)

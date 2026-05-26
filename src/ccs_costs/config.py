"""Region configuration loader -- unifies all YAML/JSON into a single model.

Loads formations.json, costs.yaml, finance.yaml, monitoring.yaml, and
regulatory.yaml from data/regions/{region}/ and assembles a RegionConfig
Pydantic model. This is the integration point between data files and
the scenario orchestrator.

Key design decisions:
    - Uses existing loader functions (load_formations, load_finance_config,
      load_monitoring_config, load_regulatory_config) rather than
      reimplementing YAML parsing.
    - Module-level cache for lazy loading (no TTL needed for static data).
    - Missing formations.json is OK (empty dict) -- norway-ncs may not
      have it until Plan 02.
    - No default region -- caller must always specify.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ccs_costs.costs.monitoring import MonitoringUnitCosts, load_monitoring_config
from ccs_costs.costs.platform import InfrastructureModel
from ccs_costs.costs.regulatory import RegulatoryConfig, load_regulatory_config
from ccs_costs.finance.escalation import EscalationConfig, load_escalation_indices
from ccs_costs.finance.tax import TaxRegime, load_finance_config
from ccs_costs.geo.formations import FormationProperties, load_formations
from ccs_costs.geo.schedule import ProjectTimeline


# ============================================================================
# Data directory
# ============================================================================

_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data"
_REGIONS_DIR = _DATA_ROOT / "regions"

# Module-level cache: region name -> RegionConfig
_REGION_CACHE: dict[str, RegionConfig] = {}


# ============================================================================
# RegionConfig model
# ============================================================================


class RegionConfig(BaseModel):
    """Complete region configuration aggregated from all data files.

    Attributes:
        name: Region identifier (e.g. "us-goa", "norway-ncs").
        currency: Currency code (USD, NOK, EUR).
        base_year: Base cost year (e.g. 2008 for NETL, 2024 for NCS).
        formations: Dict mapping formation ID to FormationProperties.
        costs_config: Raw costs.yaml data.
        finance_config: Structured finance config from load_finance_config()
            (includes tax_regime as TaxRegime, capital_structure, escalation, etc.).
        monitoring_config: MonitoringUnitCosts from monitoring.yaml.
        regulatory_config: RegulatoryConfig from regulatory.yaml.
        timeline: ProjectTimeline from costs.yaml timeline section.
        infrastructure_model: InfrastructureModel enum from costs.yaml.
        drilling_config: Raw drilling section from costs.yaml.
        escalation: EscalationConfig for cost escalation.
    """

    name: str
    currency: str
    base_year: int
    formations: dict[str, FormationProperties]
    costs_config: dict[str, Any]
    finance_config: dict[str, Any]
    monitoring_config: MonitoringUnitCosts
    regulatory_config: RegulatoryConfig
    timeline: ProjectTimeline
    infrastructure_model: InfrastructureModel
    drilling_config: dict[str, Any]
    escalation: EscalationConfig

    model_config = {"arbitrary_types_allowed": True}


# ============================================================================
# Public API
# ============================================================================


def load_region(region: str) -> RegionConfig:
    """Load all configuration for a region from data/regions/{region}/.

    Reads and validates:
    - formations.json via load_formations() (empty dict if missing)
    - costs.yaml (raw dict + parsed timeline + infrastructure_model)
    - finance.yaml via load_finance_config() (includes TaxRegime)
    - monitoring.yaml via load_monitoring_config()
    - regulatory.yaml via load_regulatory_config()
    - escalation indices (us-goa from JSON, others from finance.yaml)

    The result is cached in a module-level dict.

    Args:
        region: Region identifier (e.g. "us-goa", "norway-ncs").

    Returns:
        RegionConfig with all configuration loaded and validated.

    Raises:
        FileNotFoundError: If the region directory or required files
            (costs.yaml, finance.yaml) don't exist.
    """
    if region in _REGION_CACHE:
        return _REGION_CACHE[region]

    region_dir = _REGIONS_DIR / region
    if not region_dir.exists():
        raise FileNotFoundError(
            f"Region directory not found: {region_dir}. "
            f"Available regions: {[d.name for d in _REGIONS_DIR.iterdir() if d.is_dir()]}"
        )

    # --- Formations (optional -- may not exist for norway-ncs yet) ---
    try:
        formations = load_formations(region)
    except FileNotFoundError:
        formations = {}

    # --- Costs config (required) ---
    costs_yaml_path = region_dir / "costs.yaml"
    if not costs_yaml_path.exists():
        raise FileNotFoundError(
            f"Costs config not found: {costs_yaml_path}"
        )
    with open(costs_yaml_path) as f:
        costs_config: dict[str, Any] = yaml.safe_load(f)

    # --- Finance config (required) ---
    finance_yaml_path = region_dir / "finance.yaml"
    if not finance_yaml_path.exists():
        raise FileNotFoundError(
            f"Finance config not found: {finance_yaml_path}"
        )
    finance_config = load_finance_config(finance_yaml_path)

    # --- Monitoring config ---
    monitoring_config = load_monitoring_config(region)

    # --- Regulatory config ---
    regulatory_config = load_regulatory_config(region)

    # --- Parse timeline from costs.yaml ---
    tl_data = costs_config.get("timeline", {})
    timeline = ProjectTimeline(
        screening_years=tl_data.get("screening_years", 1),
        characterization_years=tl_data.get("characterization_years", 2),
        permitting_years=tl_data.get("permitting_years", 2),
        construction_years=tl_data.get("construction_years", 3),
        operations_years=tl_data.get("operations_years", None),
        pisc_years=tl_data.get("pisc_years", 50),
        start_year=finance_config.get("escalation", {}).get(
            "project_start_year", 2024
        ),
    )

    # --- Parse infrastructure model from costs.yaml ---
    infra_data = costs_config.get("infrastructure", {})
    model_str = infra_data.get("model", "platform_jacket")
    # Map string to InfrastructureModel enum
    infra_model_map = {
        "platform_jacket": InfrastructureModel.PLATFORM_JACKET,
        "jacket": InfrastructureModel.PLATFORM_JACKET,
        "subsea_tieback": InfrastructureModel.SUBSEA_TIEBACK,
    }
    infrastructure_model = infra_model_map.get(
        model_str, InfrastructureModel.PLATFORM_JACKET
    )

    # --- Drilling config from costs.yaml ---
    drilling_config = costs_config.get("drilling", {})

    # --- Escalation config ---
    escalation = _build_escalation_config(region, finance_config)

    # --- Region metadata ---
    currency = costs_config.get("currency", "USD")
    base_year = costs_config.get("base_year", 2008)

    config = RegionConfig(
        name=region,
        currency=currency,
        base_year=base_year,
        formations=formations,
        costs_config=costs_config,
        finance_config=finance_config,
        monitoring_config=monitoring_config,
        regulatory_config=regulatory_config,
        timeline=timeline,
        infrastructure_model=infrastructure_model,
        drilling_config=drilling_config,
        escalation=escalation,
    )

    _REGION_CACHE[region] = config
    return config


def list_available_regions() -> list[str]:
    """List available regions that have at least a costs.yaml file.

    Returns:
        Sorted list of region names (e.g. ["norway-ncs", "us-goa"]).
    """
    if not _REGIONS_DIR.exists():
        return []

    regions = []
    for d in sorted(_REGIONS_DIR.iterdir()):
        if d.is_dir() and (d / "costs.yaml").exists():
            regions.append(d.name)
    return regions


# ============================================================================
# Internal helpers
# ============================================================================


def _build_escalation_config(
    region: str,
    finance_config: dict[str, Any],
) -> EscalationConfig:
    """Build EscalationConfig from region data.

    For us-goa: loads from data/netl-extracted/escalation_indices.json
    (has pre-computed 2.849x factor).
    For other regions: constructs from finance.yaml escalation section.

    Args:
        region: Region identifier.
        finance_config: Parsed finance config dict.

    Returns:
        EscalationConfig ready for use.
    """
    esc_data = finance_config.get("escalation", {})

    if region == "us-goa":
        # Load from pre-computed NETL escalation indices
        indices_path = _DATA_ROOT / "netl-extracted" / "escalation_indices.json"
        if indices_path.exists():
            return load_escalation_indices(indices_path)

    # For non-US regions (or if indices file missing): construct from finance.yaml
    base_cost_year = esc_data.get("base_cost_year", 2024)
    project_start_year = esc_data.get("project_start_year", 2028)
    pre_project_rate = esc_data.get("pre_project_rate", 0.0)
    during_project_rate = esc_data.get("during_project_rate", 0.02)

    # Compute base_to_start_factor from pre_project_rate
    years_gap = project_start_year - base_cost_year
    if pre_project_rate > 0 and years_gap > 0:
        base_to_start_factor = (1.0 + pre_project_rate) ** years_gap
    else:
        base_to_start_factor = 1.0

    return EscalationConfig(
        base_cost_year=base_cost_year,
        project_start_year=project_start_year,
        pre_project_rate=pre_project_rate,
        during_project_rate=during_project_rate,
        base_to_start_factor=base_to_start_factor,
    )

"""Region-specific regulatory permit and fee calculations.

Loads regulatory cost items from region-specific YAML files with no
hardcoded US assumptions. Each region has its own set of permits,
fees, and compliance costs.

Key US vs Norway differences:
    - US: EPA Class VI permit, pore space fees ($0.25/t), ERR fees ($0.75/t),
      stewardship fees ($0.07/t), Subpart RR reporting
    - Norway: EU CCS Directive storage permit, PDO, EIA, EU MRV reporting.
      NO pore space fees, NO stewardship fees, NO ERR fees (production
      license model, not acreage-based)

References:
    NETL CO2_S_COM_Offshore v1.1: Back-End_Cost Items sheet
    EU CCS Directive: Storage permit requirements
    Norwegian Petroleum Safety Authority: PDO/EIA requirements
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)
from ccs_costs.geo.schedule import ProjectSchedule


# ============================================================================
# Data models
# ============================================================================


class RegulatoryItem(BaseModel):
    """Single regulatory cost item from region config."""

    id: str
    name: str
    amount: float  # Total lifetime amount
    classification: str = "expense"
    stage: str = "operations"
    recurrence: str = "one-time"
    annual_amount: float | None = None  # Per-year amount for recurring items
    per_well_cost: float | None = None  # Per-well cost for corrective action scaling
    depreciation: str = "none"
    notes: str = ""


class RegulatoryConfig(BaseModel):
    """Regulatory configuration loaded from YAML."""

    base_year: int
    currency: str
    items: list[RegulatoryItem]


class RegulatoryCosts(BaseModel):
    """Complete regulatory cost output."""

    total: float
    items: list[CostItem]


# ============================================================================
# Configuration loading
# ============================================================================


def _find_regions_dir() -> Path:
    """Find the data/regions directory."""
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "regions"


def load_regulatory_config(region: str) -> RegulatoryConfig:
    """Load regulatory configuration from region-specific YAML.

    Args:
        region: Region identifier (e.g., "us-goa", "norway-ncs").

    Returns:
        RegulatoryConfig with regulatory cost items.

    Raises:
        FileNotFoundError: If regulatory.yaml doesn't exist for the region.
    """
    yaml_path = _find_regions_dir() / region / "regulatory.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Regulatory config not found: {yaml_path}"
        )

    with open(yaml_path) as f:
        config = yaml.safe_load(f)

    items = []
    for item_data in config.get("regulatory_items", []):
        items.append(RegulatoryItem(
            id=item_data["id"],
            name=item_data["name"],
            amount=item_data["amount"],
            classification=item_data.get("classification", "expense"),
            stage=item_data.get("stage", "operations"),
            recurrence=item_data.get("recurrence", "one-time"),
            annual_amount=item_data.get("annual_amount"),
            per_well_cost=item_data.get("per_well_cost"),
            depreciation=item_data.get("depreciation", "none"),
            notes=item_data.get("notes", ""),
        ))

    return RegulatoryConfig(
        base_year=config.get("base_year", 2008),
        currency=config.get("currency", "USD"),
        items=items,
    )


# ============================================================================
# Cost calculation
# ============================================================================


def _classification(value: str) -> CostClassification:
    """Convert string to CostClassification."""
    return CostClassification(value)


def _depreciation(value: str) -> DepreciationCategory:
    """Convert string to DepreciationCategory."""
    return DepreciationCategory(value)


def _count_stage_years(schedule: ProjectSchedule, stage: str) -> int:
    """Count number of years with a given stage in the schedule."""
    return len([y for y in schedule.timeline if y.stage == stage])


def _first_year_of_stage(schedule: ProjectSchedule, stage: str) -> int:
    """Get the first project year of a given stage."""
    for y in schedule.timeline:
        if y.stage == stage:
            return y.project_year
    return 1


def _last_year_of_stage(schedule: ProjectSchedule, stage: str) -> int:
    """Get the last project year of a given stage."""
    last = 1
    for y in schedule.timeline:
        if y.stage == stage:
            last = y.project_year
    return last


def calculate_regulatory_costs(
    schedule: ProjectSchedule,
    config: RegulatoryConfig,
    corrective_action_wells: int | None = None,
) -> RegulatoryCosts:
    """Calculate regulatory costs from region-specific configuration.

    Converts RegulatoryItems from the YAML config to properly timed
    CostItems based on the project schedule.

    Args:
        schedule: ProjectSchedule with year-by-year timeline.
        config: RegulatoryConfig loaded from region YAML.
        corrective_action_wells: Number of corrective action wells for
            the formation. When provided, items with per_well_cost are
            scaled as per_well_cost * n_wells instead of using the fixed
            YAML amount. None = use YAML amount as-is.

    Returns:
        RegulatoryCosts with total and itemized list.
    """
    cost_items: list[CostItem] = []
    total = 0.0

    for reg_item in config.items:
        # Determine timing based on stage
        stage = reg_item.stage

        if stage == "characterization":
            begin = _first_year_of_stage(schedule, "characterization")
            end = begin  # One-time items in first year of stage
        elif stage == "operations":
            begin = _first_year_of_stage(schedule, "operations")
            end = _last_year_of_stage(schedule, "operations")
        elif stage == "pisc":
            begin = _first_year_of_stage(schedule, "pisc")
            end = _last_year_of_stage(schedule, "pisc")
        else:
            begin = _first_year_of_stage(schedule, stage)
            end = begin

        # Create CostItem
        if reg_item.recurrence == "one-time":
            # Scale per-well items (e.g. corrective action) when well count provided
            item_amount = reg_item.amount
            if (reg_item.per_well_cost is not None
                    and corrective_action_wells is not None):
                item_amount = reg_item.per_well_cost * corrective_action_wells

            cost_items.append(CostItem(
                id=f"REG-{reg_item.id.upper()}",
                name=reg_item.name,
                category="regulatory",
                subcategory=reg_item.id,
                stage=stage,
                classification=_classification(reg_item.classification),
                depreciation_category=_depreciation(reg_item.depreciation),
                amount_base_year=item_amount,
                base_year=config.base_year,
                currency=config.currency,
                begin_year=begin,
                end_year=begin,
                recurrence="one-time",
                notes=reg_item.notes,
            ))
            total += item_amount

        elif reg_item.recurrence == "annual":
            # Use annual_amount if provided, otherwise compute from total
            n_years = _count_stage_years(schedule, stage)
            if reg_item.annual_amount is not None:
                annual = reg_item.annual_amount
            elif n_years > 0:
                annual = reg_item.amount / n_years
            else:
                annual = reg_item.amount

            cost_items.append(CostItem(
                id=f"REG-{reg_item.id.upper()}",
                name=reg_item.name,
                category="regulatory",
                subcategory=reg_item.id,
                stage=stage,
                classification=_classification(reg_item.classification),
                depreciation_category=_depreciation(reg_item.depreciation),
                amount_base_year=annual,
                base_year=config.base_year,
                currency=config.currency,
                begin_year=begin,
                end_year=end,
                recurrence="annual",
                notes=reg_item.notes,
            ))
            # Total is the lifetime amount from the config
            total += reg_item.amount

    return RegulatoryCosts(total=total, items=cost_items)

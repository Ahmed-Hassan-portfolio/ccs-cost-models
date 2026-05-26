"""Cost item management and catalog assembly.

Provides the shared data models used by all cost modules:
- CostClassification: CAPITAL or EXPENSE
- DepreciationCategory: Depreciation schedule mapping
- CostItem: Single cost line item with timing and classification
- CostCatalog: Collection of CostItems with aggregation methods
- assemble_cost_catalog: Wire all cost modules into a unified catalog

These models map to the NETL Back-End_Cost Items sheet (~200 line items).
"""

from __future__ import annotations

from enum import Enum

import pandas as pd
from pydantic import BaseModel


class CostClassification(str, Enum):
    """Whether a cost is capitalized or expensed."""

    CAPITAL = "capital"
    EXPENSE = "expense"


class DepreciationCategory(str, Enum):
    """Depreciation schedule category for capital items.

    US NETL uses MACRS with varying recovery periods.
    Norway uses linear 6-year depreciation for most categories.
    """

    SITE_CHARACTERIZATION = "site_characterization"  # DB150, 15yr (US) / Linear 6yr (NO)
    SEISMIC = "seismic"  # SL, 5yr
    WELLS = "wells"  # DB200, 5yr (US) / Linear 6yr (NO)
    PLUG_ABANDON = "plug_abandon"  # DB200, 5yr
    PIPELINE = "pipeline"  # Offshore-specific
    PLATFORM = "platform"  # Offshore-specific
    NONE = "none"  # Expense items (not depreciated)


class CostItem(BaseModel):
    """Single cost line item in the project.

    Maps to one row in the NETL Back-End_Cost Items sheet.
    All amounts are in base_year currency before escalation.
    """

    id: str
    name: str
    category: str  # e.g. "drilling", "pipeline", "monitoring"
    subcategory: str  # e.g. "injection_well", "seismic_3d"
    stage: str  # screening, characterization, permitting_construction, operations, pisc
    classification: CostClassification
    depreciation_category: DepreciationCategory = DepreciationCategory.NONE
    amount_base_year: float  # Cost in base year currency
    base_year: int  # Year the cost is expressed in (2008 for NETL)
    currency: str = "USD"  # USD, NOK, EUR
    begin_year: int  # Project year when cost starts
    end_year: int  # Project year when cost ends
    recurrence: str = "one-time"  # "one-time", "annual", "every-5-years", etc.
    recurrence_years: int | None = None  # For periodic: interval in years
    quantity: float = 1.0  # Multiplier (e.g., number of wells)
    notes: str = ""

    def lifetime_cost(self) -> float:
        """Calculate the total lifetime cost of this item.

        For one-time items: amount * quantity.
        For annual items: amount * quantity * number_of_years.
        For periodic items: amount * quantity * number_of_occurrences.

        Returns:
            Total undiscounted lifetime cost.
        """
        amount = self.amount_base_year * self.quantity
        if self.recurrence == "one-time":
            return amount
        elif self.recurrence == "annual":
            n_years = max(0, self.end_year - self.begin_year + 1)
            return amount * n_years
        elif self.recurrence_years and self.recurrence_years > 0:
            # Periodic: count occurrences (at begin_year, begin_year+N, ...)
            n_years = max(0, self.end_year - self.begin_year + 1)
            n_occurrences = 0
            for yr in range(n_years):
                if yr % self.recurrence_years == 0:
                    n_occurrences += 1
            return amount * n_occurrences
        else:
            return amount


class CostCatalog(BaseModel):
    """Complete cost catalog for a project scenario.

    Aggregates all CostItems and provides summary methods.
    The 'total' methods compute LIFETIME totals (matching NETL Cost Breakdown 1).
    """

    items: list[CostItem]
    base_year: int
    currency: str = "USD"

    def total_capital(self) -> float:
        """Sum of all capital-classified item lifetime costs (base year, undiscounted).

        For one-time items: amount * quantity.
        For recurring capital items: amount * quantity * occurrences over lifetime.
        This matches the NETL 'Total Capital' row in Cost Breakdown 1.
        """
        total = 0.0
        for item in self.items:
            if item.classification == CostClassification.CAPITAL:
                total += item.lifetime_cost()
        return total

    def total_expense(self) -> float:
        """Sum of all expense-classified item lifetime costs (base year, undiscounted).

        For one-time expenses: amount * quantity.
        For annual expenses: amount * quantity * number_of_years.
        This matches the NETL 'Total O&M' row in Cost Breakdown 1.
        """
        total = 0.0
        for item in self.items:
            if item.classification == CostClassification.EXPENSE:
                total += item.lifetime_cost()
        return total

    def total_cost(self) -> float:
        """Total lifetime cost (capital + expense).

        Matches NETL 'Total Cost' in Cost Breakdown 1.
        """
        return self.total_capital() + self.total_expense()

    def by_category(self) -> dict[str, float]:
        """Group lifetime costs by category (e.g., pipeline, drilling, monitoring)."""
        result: dict[str, float] = {}
        for item in self.items:
            cat = item.category
            if cat not in result:
                result[cat] = 0.0
            result[cat] += item.lifetime_cost()
        return result

    def by_stage(self) -> dict[str, float]:
        """Group lifetime costs by project stage."""
        result: dict[str, float] = {}
        for item in self.items:
            stage = item.stage
            if stage not in result:
                result[stage] = 0.0
            result[stage] += item.lifetime_cost()
        return result

    def by_stage_and_classification(self) -> dict[str, dict[str, float]]:
        """Group lifetime costs by stage and classification (capital/expense).

        Returns:
            Dict mapping stage -> {"capital": amount, "expense": amount, "total": amount}
        """
        result: dict[str, dict[str, float]] = {}
        for item in self.items:
            stage = item.stage
            if stage not in result:
                result[stage] = {"capital": 0.0, "expense": 0.0, "total": 0.0}
            lc = item.lifetime_cost()
            cls_key = item.classification.value
            result[stage][cls_key] += lc
            result[stage]["total"] += lc
        return result

    def annual_schedule(self, n_years: int = 85) -> pd.DataFrame:
        """Generate annual cost schedule DataFrame.

        Args:
            n_years: Number of project years (default 85 per NETL).

        Returns:
            DataFrame with columns: year, capital, expense, total,
            plus one column per depreciation_category showing that year's
            capital cost for that category. One row per project year.
        """
        years = list(range(1, n_years + 1))
        capital = [0.0] * n_years
        expense = [0.0] * n_years

        # Track depreciation categories
        dep_cats = [dc.value for dc in DepreciationCategory if dc != DepreciationCategory.NONE]
        dep_data: dict[str, list[float]] = {dc: [0.0] * n_years for dc in dep_cats}

        for item in self.items:
            amount = item.amount_base_year * item.quantity

            for yr_idx in range(n_years):
                yr = yr_idx + 1  # 1-based project year
                if yr < item.begin_year or yr > item.end_year:
                    continue

                should_apply = False
                if item.recurrence == "one-time":
                    # One-time: only in begin_year
                    if yr == item.begin_year:
                        should_apply = True
                elif item.recurrence == "annual":
                    should_apply = True
                elif item.recurrence_years and item.recurrence_years > 0:
                    # Periodic (every N years)
                    years_since_start = yr - item.begin_year
                    if years_since_start % item.recurrence_years == 0:
                        should_apply = True

                if should_apply:
                    if item.classification == CostClassification.CAPITAL:
                        capital[yr_idx] += amount
                        # Track by depreciation category
                        dc = item.depreciation_category.value
                        if dc in dep_data:
                            dep_data[dc][yr_idx] += amount
                    else:
                        expense[yr_idx] += amount

        total = [c + e for c, e in zip(capital, expense)]
        df_data: dict[str, list] = {
            "year": years,
            "capital": capital,
            "expense": expense,
            "total": total,
        }
        # Add depreciation category columns
        for dc in dep_cats:
            df_data[f"cap_{dc}"] = dep_data[dc]

        return pd.DataFrame(df_data)


# ============================================================================
# Catalog assembly
# ============================================================================


def assemble_cost_catalog(
    pipeline: object,  # PipelineCosts
    drilling: object,  # DrillingCosts
    platform: object,  # PlatformCosts (primary)
    monitoring: object,  # MonitoringCosts
    decommissioning: object,  # DecommissioningCosts
    regulatory: object,  # RegulatoryCosts
    base_year: int = 2008,
    currency: str = "USD",
    satellite_platform: object | None = None,  # PlatformCosts (satellite)
    additional_items: list[CostItem] | None = None,
) -> CostCatalog:
    """Assemble all cost items from individual modules into a unified catalog.

    Collects CostItems from each module's .items list, validates for
    duplicate IDs and consistent base_year/currency, and returns a
    complete CostCatalog ready for the financial model.

    Args:
        pipeline: PipelineCosts from pipeline module.
        drilling: DrillingCosts from drilling module.
        platform: PlatformCosts (primary) from platform module.
        monitoring: MonitoringCosts from monitoring module.
        decommissioning: DecommissioningCosts from decommissioning module.
        regulatory: RegulatoryCosts from regulatory module.
        base_year: Cost base year (default 2008 for NETL).
        currency: Currency code (default USD).
        satellite_platform: Optional PlatformCosts for satellite platform.
        additional_items: Optional list of additional CostItems (e.g., transport
            vessels, surface equipment, data acquisition costs).

    Returns:
        CostCatalog with all items assembled.

    Raises:
        ValueError: If duplicate item IDs are found.
    """
    all_items: list[CostItem] = []

    # Collect items from each module
    modules = [
        ("pipeline", pipeline),
        ("drilling", drilling),
        ("platform", platform),
        ("monitoring", monitoring),
        ("decommissioning", decommissioning),
        ("regulatory", regulatory),
    ]

    if satellite_platform is not None:
        modules.append(("satellite_platform", satellite_platform))

    for module_name, module in modules:
        items = getattr(module, "items", [])
        all_items.extend(items)

    # Add any additional items
    if additional_items:
        all_items.extend(additional_items)

    # Validate no duplicate IDs
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for item in all_items:
        if item.id in seen_ids:
            duplicates.append(item.id)
        seen_ids.add(item.id)

    if duplicates:
        raise ValueError(
            f"Duplicate CostItem IDs found: {duplicates}. "
            f"Each cost item must have a unique identifier."
        )

    return CostCatalog(
        items=all_items,
        base_year=base_year,
        currency=currency,
    )

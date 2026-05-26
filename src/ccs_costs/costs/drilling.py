"""Drilling cost framework with pluggable regressions.

Provides well cost estimation for CO2 storage projects with two
regression models:
    - NETLDrillingRegression: NETL/QUE$TOR per-formation costs (US-GOA)
    - IEAGHGDrillingRegression: IEAGHG 2005/2 European depth-based equations

The pluggable architecture allows different regions to use different cost
models. The key interface is DrillingRegression (Protocol) which any
regression must satisfy.

NETL reference values (2008$, Formation 1 Chandeleur Area):
    Injection wells (5): $56,659,314.09 total ($11,331,862.82/well)
    Stratigraphic test (1): $19,734,283.39
    In-reservoir monitoring: $18,288,514.96 (2 wells, ~$9,144,257.48/well)
    Well data costs are separate line items per well type.

Per-formation drilling costs are computed from the QUE$TOR regression
(linear depth model: cost_2022 = slope*depth_ft + intercept) and stored
in data/netl-extracted/netl_formation_results.json. When a formation_id
is provided, NETLDrillingRegression loads formation-specific per-well costs
that replace the Formation 1 defaults.

References:
    NETL CO2_S_COM_Offshore v1.1: Drilling Costs sheet
    IEAGHG 2005/2: European CO2 storage cost equations (TNO)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml
from pydantic import BaseModel

from ccs_costs.costs.catalog import (
    CostClassification,
    CostItem,
    DepreciationCategory,
)
from ccs_costs.geo.schedule import WellPlan


# ============================================================================
# Drilling regression protocol
# ============================================================================


@runtime_checkable
class DrillingRegression(Protocol):
    """Protocol for pluggable drilling cost regressions.

    Any regression model must provide:
        - cost(): returns per-well cost for a given well type
        - name, base_year, currency, region: metadata
    """

    name: str
    base_year: int
    currency: str
    region: str

    def cost(
        self,
        depth_m: float,
        water_depth_m: float = 0.0,
        well_type: str = "injection",
    ) -> float:
        """Return per-well drilling + completion cost.

        Args:
            depth_m: Well depth in metres.
            water_depth_m: Water depth in metres (offshore).
            well_type: Well type identifier.

        Returns:
            Per-well cost in base_year currency.
        """
        ...


# ============================================================================
# NETL/QUE$TOR regression (extracted reference costs)
# ============================================================================

# NETL reference per-well costs (2008$) for Formation 1 default.
# These are the fallback values when no formation_id is provided.
# When formation_id is specified, per-formation costs are loaded from
# netl_formation_results.json (computed via QUE$TOR regression on depth).
#
# All values are PER-WELL. NETL row80/86/95 report totals for the standard
# well plan (2 strat + 5 inject + 2 in-res), so we divide each by its count.

_NETL_DEFAULT_COSTS: dict[str, float] = {
    # Well Drl & Cmp costs (per-well, 2008$)
    "injection": 56_659_314.088731416 / 5,  # row86: $11,331,862.82/well (5 wells)
    "stratigraphic_test": 19_734_283.3856482 / 2,  # row80: $9,867,141.69/well (2 wells)
    "monitoring_in_reservoir": 18_288_514.957657427 / 2,  # row95: $9,144,257.48/well (2 wells)
    "monitoring_above_seal": 18_288_514.957657427 / 2,  # approximate same cost
}

# Well data costs (total for all wells of that type)
_NETL_WELL_DATA_COSTS: dict[str, float] = {
    "stratigraphic_test": 6_961_142.23204438,
    "injection": 4_623_645.260161485,
    "monitoring_in_reservoir": 5_310_954.31410524,
    "monitoring_above_seal": 0.0,  # NETL has no above-seal well drilling/data category
}


class NETLDrillingRegression:
    """NETL/QUE$TOR drilling cost regression for US-GOA cross-verification.

    Uses per-formation drilling costs computed from the QUE$TOR linear
    regression (depth-dependent). When formation_id is provided, loads
    formation-specific per-well Drl & Cmp costs from the reference JSON.
    Falls back to Formation 1 defaults when formation_id is None or not found.

    The per-formation costs are computed from:
        cost_2022 = slope * drilled_feet + intercept  (QUE$TOR regression)
        cost_2008 = cost_2022 / (1 + deescalation_factor)
        drl_cmp = cost_2008 * (1 + project_contingency)

    Optionally loads costs from a region costs.yaml file if available.
    """

    def __init__(
        self,
        costs_yaml_path: str | Path | None = None,
        formation_id: str | None = None,
    ):
        self.name = "netl_questor"
        self.base_year = 2008
        self.currency = "USD"
        self.region = "us-goa"

        self._per_well_costs = dict(_NETL_DEFAULT_COSTS)
        self._well_data_costs = dict(_NETL_WELL_DATA_COSTS)
        self._formation_id = formation_id

        if costs_yaml_path is not None:
            self._load_from_yaml(Path(costs_yaml_path))

        if formation_id is not None:
            self._load_per_formation_costs(formation_id)

    def _load_from_yaml(self, path: Path) -> None:
        """Load per-well costs from region costs.yaml if available."""
        if not path.exists():
            return
        with open(path) as f:
            config = yaml.safe_load(f)
        drilling = config.get("drilling", {})
        well_costs = drilling.get("well_costs", {})
        for wtype, cost in well_costs.items():
            self._per_well_costs[wtype] = float(cost)
        data_costs = drilling.get("well_data_costs", {})
        for wtype, cost in data_costs.items():
            self._well_data_costs[wtype] = float(cost)

    def _load_per_formation_costs(self, formation_id: str) -> None:
        """Load per-formation drilling costs from NETL reference data.

        Overrides the default Formation 1 per-well costs with
        formation-specific values computed from the QUE$TOR regression.
        Well data costs remain at Formation 1 defaults (depth-independent
        in the NETL model).

        Args:
            formation_id: Formation identifier (e.g., "1241_1").
        """
        ref_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "data"
            / "netl-extracted"
            / "netl_formation_results.json"
        )
        if not ref_path.exists():
            return  # Fall back to default costs

        data = json.loads(ref_path.read_text(encoding="utf-8"))
        fdata = data.get("formations", {}).get(formation_id, {})
        dc = fdata.get("drilling_costs", {})
        if not dc:
            return  # Formation not found or no drilling costs

        # Override per-well Drl & Cmp costs from per-formation data
        if dc.get("injection_per_well"):
            self._per_well_costs["injection"] = dc["injection_per_well"]
        if dc.get("strat_test_per_well"):
            self._per_well_costs["stratigraphic_test"] = dc["strat_test_per_well"]
        if dc.get("monitoring_in_res_per_well"):
            self._per_well_costs["monitoring_in_reservoir"] = dc["monitoring_in_res_per_well"]
            self._per_well_costs["monitoring_above_seal"] = dc["monitoring_in_res_per_well"]

        # Override well data costs if present
        if dc.get("well_data_strat"):
            self._well_data_costs["stratigraphic_test"] = dc["well_data_strat"]
        if dc.get("well_data_inject"):
            self._well_data_costs["injection"] = dc["well_data_inject"]
        if dc.get("well_data_in_res"):
            self._well_data_costs["monitoring_in_reservoir"] = dc["well_data_in_res"]

    def cost(
        self,
        depth_m: float,
        water_depth_m: float = 0.0,
        well_type: str = "injection",
    ) -> float:
        """Return per-well drilling + completion cost (2008$).

        Returns the per-well cost for the given well type. When a
        formation_id was provided at construction, returns formation-
        specific costs from the QUE$TOR regression. Otherwise returns
        Formation 1 defaults.

        Args:
            depth_m: Well depth in metres (used by IEAGHG, available here).
            water_depth_m: Water depth in metres (available for future use).
            well_type: One of 'injection', 'stratigraphic_test',
                'monitoring_in_reservoir', 'monitoring_above_seal'.

        Returns:
            Per-well cost in 2008 USD.
        """
        if well_type in self._per_well_costs:
            return self._per_well_costs[well_type]

        # Fallback: use injection well cost as default
        return self._per_well_costs.get("injection", 0.0)

    def well_data_cost(self, well_type: str = "injection") -> float:
        """Return well data/logging cost for a well type.

        Well data costs are separate from drilling + completion in the NETL
        model. They cover logging, casing evaluation, core analysis etc.

        Args:
            well_type: Well type identifier.

        Returns:
            Total well data cost in 2008 USD for all wells of that type.
        """
        return self._well_data_costs.get(well_type, 0.0)


# ============================================================================
# IEAGHG 2005/2 European regression
# ============================================================================


class IEAGHGDrillingRegression:
    """IEAGHG 2005/2 European well cost regression (TNO equations).

    Depth-based cost equations from the IEAGHG 2005/2 report which
    provides European offshore well cost estimates in year-2000 EUR.

    The equations are quadratic in depth:
        cost = a + b * depth + c * depth^2

    where depth is in metres and cost is in EUR (year-2000).

    These coefficients approximate the TNO equations from IEAGHG 2005/2
    for offshore injection wells. The exact form varies by well type
    and onshore/offshore, but the quadratic depth dependence is the
    core relationship.

    For NCS projects, an escalation_factor should be applied to bring
    year-2000 EUR costs to current NCS cost levels. The factor combines:
        - Inflation escalation (~2.3x from SSB PPI 2000-2024)
        - Norwegian offshore premium (~1.7x over European average)
        - Combined: ~4.0x for NCS projects
    """

    def __init__(self, escalation_factor: float = 1.0):
        self.name = "ieaghg_2005"
        self.base_year = 2000
        self.currency = "EUR"
        self.region = "europe"
        self._escalation_factor = escalation_factor

        # Quadratic coefficients: cost_EUR = a + b*depth_m + c*depth_m^2
        # Derived from IEAGHG 2005/2 offshore injection well curves.
        # Base EUR year-2000 values.
        self._coeffs: dict[str, tuple[float, float, float]] = {
            "injection": (500_000.0, 1_200.0, 0.60),
            "stratigraphic_test": (400_000.0, 1_000.0, 0.50),
            "monitoring_in_reservoir": (350_000.0, 900.0, 0.45),
            "monitoring_above_seal": (300_000.0, 800.0, 0.40),
        }

    def cost(
        self,
        depth_m: float,
        water_depth_m: float = 0.0,
        well_type: str = "injection",
    ) -> float:
        """Return per-well cost in escalated EUR.

        Applies the escalation_factor to bring year-2000 base costs to
        current cost levels. For NCS, factor ~4.0 brings costs to
        realistic 2024 NCS levels (EUR 15-25M/well at Johansen depth).

        Args:
            depth_m: Well depth in metres.
            water_depth_m: Water depth in metres (minor cost impact).
            well_type: Well type identifier.

        Returns:
            Per-well cost in EUR (escalated from year-2000 base).
        """
        coeffs = self._coeffs.get(
            well_type, self._coeffs["injection"]
        )
        a, b, c = coeffs

        # Base cost from depth regression
        base_cost = a + b * depth_m + c * depth_m**2

        # Water depth adder: offshore premium scales with water depth
        # ~EUR 500/m for mobilization, positioning, and vessel costs
        if water_depth_m > 0:
            base_cost += 500.0 * water_depth_m

        return max(0.0, base_cost * self._escalation_factor)

    def well_data_cost(self, well_type: str = "injection") -> float:
        """Well data costs are included in the IEAGHG total; returns 0."""
        return 0.0


# ============================================================================
# DrillingCosts output model
# ============================================================================


class DrillingCosts(BaseModel):
    """Complete drilling cost output for a project.

    Aggregates per-well costs by type, includes well data costs,
    and produces CostItem list with timing information.
    """

    cost_per_well: dict[str, float]
    total_injection: float
    total_strat_test: float
    total_monitoring_in_res: float
    total_monitoring_above_seal: float
    total_well_data: float
    total_drilling: float
    regression_name: str
    base_year: int
    currency: str
    items: list[CostItem] = []


# ============================================================================
# Main calculation function
# ============================================================================


def calculate_drilling_costs(
    well_plan: WellPlan,
    depth_m: float,
    water_depth_m: float = 0.0,
    regression: NETLDrillingRegression | IEAGHGDrillingRegression | None = None,
    base_year: int = 2008,
    currency: str = "USD",
    characterization_year: int = 2,
    construction_begin: int = 6,
    operations_begin: int = 9,
    operations_end: int = 38,
    pisc_end: int = 88,
    n_monitoring_in_reservoir: int | None = None,
    n_monitoring_above_seal: int | None = None,
) -> DrillingCosts:
    """Calculate all well drilling and completion costs.

    Produces costs for all well types in the well plan, including
    drilling + completion and well data costs. Creates CostItems
    with proper timing based on project schedule.

    Args:
        well_plan: WellPlan with well counts by type.
        depth_m: Formation depth in metres.
        water_depth_m: Water depth in metres (offshore).
        regression: Drilling cost regression to use. Defaults to NETL.
        base_year: Cost base year.
        currency: Currency code.
        characterization_year: Project year for strat test well.
        construction_begin: First year of construction (injection + monitoring wells).
        operations_begin: First year of operations.
        operations_end: Last year of injection operations.
        pisc_end: Last year of PISC.
        n_monitoring_in_reservoir: Number of in-reservoir monitoring wells.
            If None, defaults to half of well_plan.n_monitoring.
        n_monitoring_above_seal: Number of above-seal monitoring wells.
            If None, defaults to well_plan.n_monitoring - n_in_reservoir.

    Returns:
        DrillingCosts with per-well costs, totals, and CostItem list.
    """
    if regression is None:
        regression = NETLDrillingRegression()

    # Use regression metadata for base_year and currency if not overridden
    base_year = regression.base_year
    currency = regression.currency

    # Split monitoring wells into in-reservoir and above-seal
    if n_monitoring_in_reservoir is None:
        n_in_res = well_plan.n_monitoring // 2
    else:
        n_in_res = n_monitoring_in_reservoir

    if n_monitoring_above_seal is None:
        n_above_seal = well_plan.n_monitoring - n_in_res
    else:
        n_above_seal = n_monitoring_above_seal

    # Calculate per-well costs
    cost_injection = regression.cost(depth_m, water_depth_m, "injection")
    cost_strat = regression.cost(depth_m, water_depth_m, "stratigraphic_test")
    cost_mon_in_res = regression.cost(depth_m, water_depth_m, "monitoring_in_reservoir")
    cost_mon_above = regression.cost(depth_m, water_depth_m, "monitoring_above_seal")

    # Well data costs — only include for well types that have non-zero counts
    data_strat = regression.well_data_cost("stratigraphic_test") if well_plan.n_stratigraphic_test > 0 else 0.0
    data_inject = regression.well_data_cost("injection") if well_plan.n_injection > 0 else 0.0
    data_in_res = regression.well_data_cost("monitoring_in_reservoir") if n_in_res > 0 else 0.0
    data_above = regression.well_data_cost("monitoring_above_seal") if n_above_seal > 0 else 0.0

    # Totals
    total_injection = cost_injection * well_plan.n_injection
    total_strat = cost_strat * well_plan.n_stratigraphic_test
    total_in_res = cost_mon_in_res * n_in_res
    total_above_seal = cost_mon_above * n_above_seal
    total_well_data = data_strat + data_inject + data_in_res + data_above
    total_drilling = total_injection + total_strat + total_in_res + total_above_seal + total_well_data

    cost_per_well = {
        "injection": cost_injection,
        "stratigraphic_test": cost_strat,
        "monitoring_in_reservoir": cost_mon_in_res,
        "monitoring_above_seal": cost_mon_above,
    }

    # Build CostItems
    items: list[CostItem] = []

    # Stratigraphic test well - drilled during characterization
    if well_plan.n_stratigraphic_test > 0:
        items.append(
            CostItem(
                id="DRILL-STRAT",
                name="Stratigraphic test well drilling & completion",
                category="drilling",
                subcategory="stratigraphic_test",
                stage="characterization",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.WELLS,
                amount_base_year=cost_strat,
                base_year=base_year,
                currency=currency,
                begin_year=characterization_year,
                end_year=characterization_year,
                recurrence="one-time",
                quantity=float(well_plan.n_stratigraphic_test),
                notes=f"NETL row80: ${total_strat:,.2f} total",
            )
        )
        if data_strat > 0:
            items.append(
                CostItem(
                    id="DRILL-STRAT-DATA",
                    name="Stratigraphic test well data/logging",
                    category="drilling",
                    subcategory="well_data_stratigraphic_test",
                    stage="characterization",
                    classification=CostClassification.CAPITAL,
                    depreciation_category=DepreciationCategory.SITE_CHARACTERIZATION,
                    amount_base_year=data_strat,
                    base_year=base_year,
                    currency=currency,
                    begin_year=characterization_year,
                    end_year=characterization_year,
                    recurrence="one-time",
                    quantity=1.0,
                    notes=f"NETL row82: ${data_strat:,.2f}",
                )
            )

    # Injection wells - drilled during construction
    if well_plan.n_injection > 0:
        items.append(
            CostItem(
                id="DRILL-INJECT",
                name="Injection well drilling & completion",
                category="drilling",
                subcategory="injection_well",
                stage="permitting_construction",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.WELLS,
                amount_base_year=cost_injection,
                base_year=base_year,
                currency=currency,
                begin_year=construction_begin,
                end_year=construction_begin,
                recurrence="one-time",
                quantity=float(well_plan.n_injection),
                notes=f"NETL row86: ${total_injection:,.2f} total for {well_plan.n_injection} wells",
            )
        )
        if data_inject > 0:
            items.append(
                CostItem(
                    id="DRILL-INJECT-DATA",
                    name="Injection well data/logging",
                    category="drilling",
                    subcategory="well_data_injection",
                    stage="permitting_construction",
                    classification=CostClassification.CAPITAL,
                    depreciation_category=DepreciationCategory.WELLS,
                    amount_base_year=data_inject,
                    base_year=base_year,
                    currency=currency,
                    begin_year=construction_begin,
                    end_year=construction_begin,
                    recurrence="one-time",
                    quantity=1.0,
                    notes=f"NETL row89: ${data_inject:,.2f}",
                )
            )

    # In-reservoir monitoring wells - drilled during construction
    if n_in_res > 0:
        items.append(
            CostItem(
                id="DRILL-MON-INRES",
                name="In-reservoir monitoring well drilling & completion",
                category="drilling",
                subcategory="monitoring_in_reservoir",
                stage="permitting_construction",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.WELLS,
                amount_base_year=cost_mon_in_res,
                base_year=base_year,
                currency=currency,
                begin_year=construction_begin,
                end_year=construction_begin,
                recurrence="one-time",
                quantity=float(n_in_res),
                notes=f"NETL row95: ${total_in_res:,.2f} total for {n_in_res} wells",
            )
        )
        if data_in_res > 0:
            items.append(
                CostItem(
                    id="DRILL-MON-INRES-DATA",
                    name="In-reservoir monitoring well data/logging",
                    category="drilling",
                    subcategory="well_data_monitoring_in_reservoir",
                    stage="permitting_construction",
                    classification=CostClassification.CAPITAL,
                    depreciation_category=DepreciationCategory.WELLS,
                    amount_base_year=data_in_res,
                    base_year=base_year,
                    currency=currency,
                    begin_year=construction_begin,
                    end_year=construction_begin,
                    recurrence="one-time",
                    quantity=1.0,
                    notes=f"NETL row98: ${data_in_res:,.2f}",
                )
            )

    # Above-seal monitoring wells - drilled during construction
    if n_above_seal > 0:
        items.append(
            CostItem(
                id="DRILL-MON-ABSEAL",
                name="Above-seal monitoring well drilling & completion",
                category="drilling",
                subcategory="monitoring_above_seal",
                stage="permitting_construction",
                classification=CostClassification.CAPITAL,
                depreciation_category=DepreciationCategory.WELLS,
                amount_base_year=cost_mon_above,
                base_year=base_year,
                currency=currency,
                begin_year=construction_begin,
                end_year=construction_begin,
                recurrence="one-time",
                quantity=float(n_above_seal),
                notes=f"${total_above_seal:,.2f} total for {n_above_seal} wells",
            )
        )
        if data_above > 0:
            items.append(
                CostItem(
                    id="DRILL-MON-ABSEAL-DATA",
                    name="Above-seal monitoring well data/logging",
                    category="drilling",
                    subcategory="well_data_monitoring_above_seal",
                    stage="permitting_construction",
                    classification=CostClassification.CAPITAL,
                    depreciation_category=DepreciationCategory.WELLS,
                    amount_base_year=data_above,
                    base_year=base_year,
                    currency=currency,
                    begin_year=construction_begin,
                    end_year=construction_begin,
                    recurrence="one-time",
                    quantity=1.0,
                    notes=f"${data_above:,.2f}",
                )
            )

    return DrillingCosts(
        cost_per_well=cost_per_well,
        total_injection=total_injection,
        total_strat_test=total_strat,
        total_monitoring_in_res=total_in_res,
        total_monitoring_above_seal=total_above_seal,
        total_well_data=total_well_data,
        total_drilling=total_drilling,
        regression_name=regression.name,
        base_year=base_year,
        currency=currency,
        items=items,
    )

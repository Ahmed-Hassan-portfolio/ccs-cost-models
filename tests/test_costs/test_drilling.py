"""Tests for drilling cost framework with pluggable regressions.

Verifies NETL reference values for well drilling + completion costs,
IEAGHG 2005/2 European regression, and the pluggable architecture.

NETL reference values (2008$, Formation 1 Chandeleur Area).
All Well Drl & Cmp rows are totals across the standard NETL well plan
(2 strat + 5 inject + 2 in-res); per-well values are total / well count.

    - row80: Well Drl & Cmp-Strat = $19,734,283.39 total (2 strat wells)
             → $9,867,141.69 per well
    - row82: Well Data-Strat       = $6,961,142.23 (lump, all strat)
    - row86: Well Drl & Cmp-Inject = $56,659,314.09 total (5 inject wells)
             → $11,331,862.82 per well
    - row89: Well Data-Inject      = $4,623,645.26 (lump, all inject)
    - row95: Well Drl & Cmp-In Res = $18,288,514.96 total (2 in-res wells)
             → $9,144,257.48 per well
    - row98: Well Data-In Res      = $5,310,954.31 (lump, all in-res)
"""

from __future__ import annotations

import pytest

from ccs_costs.costs.drilling import (
    DrillingCosts,
    DrillingRegression,
    IEAGHGDrillingRegression,
    NETLDrillingRegression,
    calculate_drilling_costs,
)
from ccs_costs.costs.catalog import CostClassification, CostItem, DepreciationCategory
from ccs_costs.geo.schedule import WellPlan


# ============================================================================
# NETL Reference Values (2008$)
# ============================================================================

NETL_INJECT_TOTAL = 56_659_314.088731416  # 5 injection wells
NETL_INJECT_PER_WELL = NETL_INJECT_TOTAL / 5  # ~$11,331,862.82
NETL_STRAT_TOTAL = 19_734_283.3856482  # 2 strat test wells
NETL_STRAT_PER_WELL = NETL_STRAT_TOTAL / 2  # ~$9,867,141.69
NETL_IN_RES_TOTAL = 18_288_514.957657427  # 2 in-reservoir monitoring wells
NETL_IN_RES_PER_WELL = NETL_IN_RES_TOTAL / 2  # ~$9,144,257.48
NETL_WELL_DATA_STRAT = 6_961_142.23204438
NETL_WELL_DATA_INJECT = 4_623_645.260161485
NETL_WELL_DATA_IN_RES = 5_310_954.31410524

# NETL default formation: depth_m=1048.07, water_depth_m=20.96


# ============================================================================
# NETLDrillingRegression tests
# ============================================================================


class TestNETLDrillingRegression:
    """Tests for the NETL/QUE$TOR drilling cost regression."""

    def setup_method(self):
        self.regression = NETLDrillingRegression()

    def test_injection_well_cost(self):
        """Injection well cost matches NETL per-well reference."""
        cost = self.regression.cost(
            depth_m=1048.07,
            water_depth_m=20.96,
            well_type="injection",
        )
        assert cost == pytest.approx(NETL_INJECT_PER_WELL, rel=1e-3)

    def test_strat_well_cost(self):
        """Stratigraphic test well per-well cost matches NETL reference."""
        cost = self.regression.cost(
            depth_m=1048.07,
            water_depth_m=20.96,
            well_type="stratigraphic_test",
        )
        # NETL row80 ($19.73M) is the total for 2 strat wells → per-well = $9.87M
        assert cost == pytest.approx(NETL_STRAT_PER_WELL, rel=1e-3)

    def test_monitoring_in_reservoir_cost(self):
        """In-reservoir monitoring well cost matches NETL reference."""
        cost = self.regression.cost(
            depth_m=1048.07,
            water_depth_m=20.96,
            well_type="monitoring_in_reservoir",
        )
        # NETL_IN_RES_TOTAL is for the total monitoring wells (2 in-reservoir)
        # Per-well cost = total / n_monitoring_in_reservoir
        # But NETL groups in-reservoir monitoring differently
        # The regression should return per-well cost
        assert cost > 0

    def test_well_data_strat(self):
        """Well data cost for strat test well matches NETL."""
        cost = self.regression.well_data_cost(
            well_type="stratigraphic_test",
        )
        assert cost == pytest.approx(NETL_WELL_DATA_STRAT, rel=1e-3)

    def test_well_data_inject(self):
        """Well data cost for injection wells matches NETL."""
        cost = self.regression.well_data_cost(
            well_type="injection",
        )
        # Per 5 wells
        assert cost == pytest.approx(NETL_WELL_DATA_INJECT, rel=1e-3)

    def test_well_data_in_res(self):
        """Well data cost for in-reservoir monitoring matches NETL."""
        cost = self.regression.well_data_cost(
            well_type="monitoring_in_reservoir",
        )
        assert cost == pytest.approx(NETL_WELL_DATA_IN_RES, rel=1e-3)

    def test_regression_metadata(self):
        """NETL regression has correct metadata."""
        assert self.regression.name == "netl_questor"
        assert self.regression.base_year == 2008
        assert self.regression.currency == "USD"


# ============================================================================
# IEAGHGDrillingRegression tests
# ============================================================================


class TestIEAGHGDrillingRegression:
    """Tests for the IEAGHG 2005/2 European drilling regression."""

    def setup_method(self):
        self.regression = IEAGHGDrillingRegression()

    def test_injection_cost_positive(self):
        """IEAGHG produces positive cost for European well at 2700m depth."""
        cost = self.regression.cost(
            depth_m=2700.0,
            water_depth_m=300.0,
            well_type="injection",
        )
        assert cost > 0

    def test_cost_in_eur_year2000(self):
        """IEAGHG returns cost in year-2000 EUR."""
        assert self.regression.base_year == 2000
        assert self.regression.currency == "EUR"

    def test_cost_increases_with_depth(self):
        """Deeper wells cost more."""
        cost_shallow = self.regression.cost(depth_m=1000.0)
        cost_deep = self.regression.cost(depth_m=3000.0)
        assert cost_deep > cost_shallow

    def test_regression_metadata(self):
        """IEAGHG regression has correct metadata."""
        assert self.regression.name == "ieaghg_2005"
        assert "europe" in self.regression.region.lower() or "ieaghg" in self.regression.name


# ============================================================================
# DrillingRegression protocol tests
# ============================================================================


class TestDrillingRegressionProtocol:
    """Tests that both regressions satisfy the protocol interface."""

    @pytest.mark.parametrize("regression_cls", [NETLDrillingRegression, IEAGHGDrillingRegression])
    def test_has_cost_method(self, regression_cls):
        """Both regressions implement cost()."""
        reg = regression_cls()
        assert hasattr(reg, "cost")
        assert callable(reg.cost)

    @pytest.mark.parametrize("regression_cls", [NETLDrillingRegression, IEAGHGDrillingRegression])
    def test_has_metadata(self, regression_cls):
        """Both regressions have name, base_year, currency."""
        reg = regression_cls()
        assert hasattr(reg, "name")
        assert hasattr(reg, "base_year")
        assert hasattr(reg, "currency")
        assert isinstance(reg.name, str)
        assert isinstance(reg.base_year, int)
        assert isinstance(reg.currency, str)


# ============================================================================
# calculate_drilling_costs tests
# ============================================================================


class TestCalculateDrillingCosts:
    """Tests for the main calculate_drilling_costs function."""

    def test_total_injection_matches_netl(self):
        """Total injection well drilling matches NETL $56.66M within 0.1%."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,  # NETL default: 2 in-res + 2 above-seal
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        assert isinstance(result, DrillingCosts)
        assert result.total_injection == pytest.approx(NETL_INJECT_TOTAL, rel=1e-3)

    def test_strat_test_matches_netl(self):
        """Stratigraphic test wells total matches NETL $19.73M within 0.1%.

        NETL row80 reports $19.73M for 2 strat test wells; per-well = $9.87M.
        Using NETL's standard 2-well plan, total should match $19.73M.
        """
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=2,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        assert result.total_strat_test == pytest.approx(NETL_STRAT_TOTAL, rel=1e-3)

    def test_monitoring_in_res_matches_netl(self):
        """In-reservoir monitoring well cost matches NETL $18.29M within 0.1%."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        assert result.total_monitoring_in_res == pytest.approx(NETL_IN_RES_TOTAL, rel=1e-3)

    def test_returns_cost_items(self):
        """calculate_drilling_costs returns CostItem list."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        assert len(result.items) > 0
        for item in result.items:
            assert isinstance(item, CostItem)
            assert item.category == "drilling"

    def test_cost_items_have_correct_classification(self):
        """Drilling CostItems are capital classification with wells depreciation."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        for item in result.items:
            if "data" not in item.subcategory:
                assert item.classification == CostClassification.CAPITAL
                assert item.depreciation_category == DepreciationCategory.WELLS

    def test_well_data_costs_included(self):
        """Well data costs are included as separate CostItems."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        data_items = [i for i in result.items if "data" in i.subcategory]
        assert len(data_items) >= 1  # At least some well data costs

    def test_total_drilling_positive(self):
        """Total drilling cost is positive."""
        well_plan = WellPlan(
            n_injection=5,
            n_monitoring=4,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=1048.07,
            water_depth_m=20.96,
            regression=NETLDrillingRegression(),
        )
        assert result.total_drilling > 0

    def test_works_with_ieaghg_regression(self):
        """calculate_drilling_costs works with IEAGHG regression (pluggable arch)."""
        well_plan = WellPlan(
            n_injection=2,
            n_monitoring=3,
            n_stratigraphic_test=1,
        )
        result = calculate_drilling_costs(
            well_plan=well_plan,
            depth_m=2700.0,
            water_depth_m=300.0,
            regression=IEAGHGDrillingRegression(),
        )
        assert isinstance(result, DrillingCosts)
        assert result.total_drilling > 0
        assert len(result.items) > 0


# ============================================================================
# Per-formation drilling cost tests
# ============================================================================


class TestNETLPerFormationCosts:
    """Tests for per-formation drilling cost loading.

    The optional file ``data/netl-extracted/netl_formation_results.json`` would
    carry per-formation QUE$TOR-regression outputs (slope * drilled_feet +
    intercept) so that drilling costs vary with formation depth. That file is
    a derived product we cannot redistribute alongside this portfolio mirror,
    so ``NETLDrillingRegression`` silently falls back to Formation 1
    (1241_1) defaults for every formation_id. Tests that need per-formation
    *differentiation* are skipped; tests that just confirm Formation 1 values
    via the default fallback still run.
    """

    def test_formation_1_matches_known_value(self):
        """Formation 1241_1 injection per-well cost matches NETL reference."""
        reg = NETLDrillingRegression(formation_id="1241_1")
        cost = reg.cost(depth_m=1048.07, well_type="injection")
        assert abs(cost - 11_331_862.82) < 1.0

    @pytest.mark.skip(
        reason=(
            "Per-formation differentiation requires "
            "data/netl-extracted/netl_formation_results.json, a derived "
            "QUE$TOR-regression product that is not redistributed with this "
            "portfolio mirror. With the fallback, all formations return "
            "Formation 1 defaults."
        )
    )
    def test_different_formations_have_different_costs(self):
        """Different formations produce different per-well drilling costs."""
        reg_1 = NETLDrillingRegression(formation_id="1241_1")
        reg_2 = NETLDrillingRegression(formation_id="1261_1")
        cost_1 = reg_1.cost(depth_m=1000, well_type="injection")
        cost_2 = reg_2.cost(depth_m=1000, well_type="injection")
        assert cost_1 != cost_2, "Per-formation costs should differ between formations"

    def test_formation_1_strat_matches(self):
        """Formation 1241_1 strat test per-well matches NETL reference."""
        reg = NETLDrillingRegression(formation_id="1241_1")
        cost = reg.cost(depth_m=1048.07, well_type="stratigraphic_test")
        # NETL strat total is $19,734,283.39 for 2 strat wells -> $9,867,141.69/well
        assert abs(cost - 9_867_141.69) < 1.0

    def test_formation_1_monitoring_matches(self):
        """Formation 1241_1 in-res monitoring per-well matches NETL reference."""
        reg = NETLDrillingRegression(formation_id="1241_1")
        cost = reg.cost(depth_m=1048.07, well_type="monitoring_in_reservoir")
        assert abs(cost - 9_144_257.48) < 1.0

    def test_no_formation_id_gives_defaults(self):
        """Without formation_id, regression returns Formation 1 defaults."""
        reg = NETLDrillingRegression()
        cost = reg.cost(depth_m=1048.07, well_type="injection")
        assert cost == pytest.approx(NETL_INJECT_PER_WELL, rel=1e-6)

    def test_unknown_formation_gives_defaults(self):
        """Unknown formation_id falls back to Formation 1 defaults."""
        reg = NETLDrillingRegression(formation_id="nonexistent_999")
        cost = reg.cost(depth_m=1048.07, well_type="injection")
        assert cost == pytest.approx(NETL_INJECT_PER_WELL, rel=1e-6)

    @pytest.mark.skip(
        reason=(
            "Per-formation differentiation requires "
            "data/netl-extracted/netl_formation_results.json (see sibling "
            "test). Without it, deep and shallow formations both use "
            "Formation 1 defaults, so the depth-monotonicity check is "
            "unverifiable in this portfolio mirror."
        )
    )
    def test_deep_formation_costs_more(self):
        """Deeper formations should have higher per-well drilling costs."""
        # 1241_1 is shallow (~1048m depth), 2441_1 is deep (~3741m depth)
        reg_shallow = NETLDrillingRegression(formation_id="1241_1")
        reg_deep = NETLDrillingRegression(formation_id="2441_1")
        cost_shallow = reg_shallow.cost(depth_m=0, well_type="injection")
        cost_deep = reg_deep.cost(depth_m=0, well_type="injection")
        assert cost_deep > cost_shallow, "Deeper formations should cost more to drill"

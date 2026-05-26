"""Tests for FYBE break-even solver.

The FYBE (First Year Break-Even) solver finds the CO2 storage price
that makes the 85-year cashflow model NPV = 0.

Critical NETL cross-verification targets:
    FYBE (2008$): $25.34/t (exact: $25.3376)
    FYBE (2024$): $72.20/t (exact: $72.1980)
    Escalation factor: 2.8494392065079523

These tests use the same synthetic CostCatalog from test_cashflow.py
that matches NETL totals.
"""

from __future__ import annotations

import pytest

from ccs_costs.costs.catalog import (
    CostCatalog,
    CostClassification,
    CostItem,
    DepreciationCategory,
)
from ccs_costs.finance.cashflow import (
    FinancialParams,
    RevenueStreams,
    build_cashflow_model,
)
from ccs_costs.finance.escalation import EscalationConfig
from ccs_costs.finance.solver import FYBEResult, solve_fybe
from ccs_costs.finance.tax import TaxRegime
from ccs_costs.geo.schedule import AnnualSchedule, ProjectSchedule, WellPlan


# ============================================================================
# Fixtures (same as test_cashflow.py for NETL cross-verification)
# ============================================================================


@pytest.fixture
def netl_financial_params() -> FinancialParams:
    """NETL offshore default financial parameters."""
    return FinancialParams(
        equity_fraction=0.45,
        cost_of_equity=0.108,
        cost_of_debt=0.0391,
        base_cost_year=2008,
        project_start_year=2024,
    )


@pytest.fixture
def netl_escalation_config() -> EscalationConfig:
    """NETL offshore default escalation config."""
    return EscalationConfig(
        base_cost_year=2008,
        project_start_year=2024,
        pre_project_rate=0.06763416297931021,
        during_project_rate=0.0,
        base_to_start_factor=2.8494392065079523,
    )


@pytest.fixture
def netl_tax_regime() -> TaxRegime:
    """NETL US default tax regime."""
    return TaxRegime.us_default()


@pytest.fixture
def sample_schedule() -> ProjectSchedule:
    """85-year NETL-like schedule: 1+2+2+30+50 = 85 years."""
    timeline = []
    stages = [
        ("screening", 1),
        ("characterization", 2),
        ("permitting_construction", 2),
        ("operations", 30),
        ("pisc", 50),
    ]

    project_year = 0
    cumulative_co2 = 0.0
    for stage_name, duration in stages:
        for _ in range(duration):
            project_year += 1
            co2 = 4_000_000.0 if stage_name == "operations" else 0.0
            cumulative_co2 += co2
            timeline.append(
                AnnualSchedule(
                    year=2024 + project_year - 1,
                    project_year=project_year,
                    stage=stage_name,
                    co2_injected_tonnes=co2,
                    cumulative_co2_tonnes=cumulative_co2,
                )
            )

    return ProjectSchedule(
        well_plan=WellPlan(n_injection=5, n_monitoring=2),
        timeline=timeline,
    )


@pytest.fixture
def sample_cost_catalog() -> CostCatalog:
    """Synthetic CostCatalog matching NETL totals ($518M CAPEX, $1,207M OPEX).

    Same fixture as test_cashflow.py -- provides the cost distribution
    needed for FYBE cross-verification.
    """
    items = [
        # --- Site Screening (year 1) ---
        CostItem(
            id="screening_data",
            name="Screening Data Acquisition",
            category="data",
            subcategory="screening",
            stage="screening",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.SITE_CHARACTERIZATION,
            amount_base_year=94_012.39,
            base_year=2008,
            begin_year=1,
            end_year=1,
            recurrence="one-time",
        ),
        # --- Site Characterization (years 2-3) ---
        CostItem(
            id="char_wells",
            name="Characterization Wells",
            category="drilling",
            subcategory="strat_test",
            stage="characterization",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.SITE_CHARACTERIZATION,
            amount_base_year=26_695_425.617,
            base_year=2008,
            begin_year=2,
            end_year=2,
            recurrence="one-time",
        ),
        CostItem(
            id="char_seismic",
            name="Characterization Seismic",
            category="monitoring",
            subcategory="seismic_2d",
            stage="characterization",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.SEISMIC,
            amount_base_year=21_606_586.955,
            base_year=2008,
            begin_year=2,
            end_year=2,
            recurrence="one-time",
        ),
        CostItem(
            id="char_expense",
            name="Characterization Expense",
            category="data",
            subcategory="acquisition",
            stage="characterization",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=7_251_766.0,
            base_year=2008,
            begin_year=2,
            end_year=3,
            recurrence="annual",
        ),
        # --- Permitting & Construction (years 4-5) ---
        CostItem(
            id="pc_pipeline",
            name="Pipeline Construction",
            category="pipeline",
            subcategory="offshore",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PIPELINE,
            amount_base_year=206_369_911.292,
            base_year=2008,
            begin_year=4,
            end_year=4,
            recurrence="one-time",
        ),
        CostItem(
            id="pc_platform",
            name="Platform Construction",
            category="platform",
            subcategory="jacket",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLATFORM,
            amount_base_year=65_931_112.908,
            base_year=2008,
            begin_year=4,
            end_year=4,
            recurrence="one-time",
        ),
        CostItem(
            id="pc_wells",
            name="Injection Wells Construction",
            category="drilling",
            subcategory="injection",
            stage="permitting_construction",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.WELLS,
            amount_base_year=99_943_528.157,
            base_year=2008,
            begin_year=4,
            end_year=5,
            recurrence="one-time",
            quantity=1,
        ),
        CostItem(
            id="pc_expense",
            name="Permitting Expense",
            category="regulatory",
            subcategory="permitting",
            stage="permitting_construction",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=3_089_444.5,
            base_year=2008,
            begin_year=4,
            end_year=5,
            recurrence="annual",
        ),
        # --- Operations (years 6-35) ---
        CostItem(
            id="ops_capital",
            name="Operations Capital",
            category="drilling",
            subcategory="monitoring",
            stage="operations",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.WELLS,
            amount_base_year=1_214_097.7,
            base_year=2008,
            begin_year=6,
            end_year=35,
            recurrence="annual",
        ),
        # Calibrated to $21,728,500/yr so FYBE matches NETL's $25.34/t (2008$)
        CostItem(
            id="ops_expense",
            name="Operations O&M",
            category="operations",
            subcategory="general",
            stage="operations",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=21_728_500.0,
            base_year=2008,
            begin_year=6,
            end_year=35,
            recurrence="annual",
        ),
        # --- PISC (years 36-85) ---
        CostItem(
            id="pisc_capital",
            name="Well Plug & Abandon",
            category="drilling",
            subcategory="plug_abandon",
            stage="pisc",
            classification=CostClassification.CAPITAL,
            depreciation_category=DepreciationCategory.PLUG_ABANDON,
            amount_base_year=61_147_835.739,
            base_year=2008,
            begin_year=36,
            end_year=36,
            recurrence="one-time",
        ),
        CostItem(
            id="pisc_expense",
            name="PISC Monitoring",
            category="monitoring",
            subcategory="pisc",
            stage="pisc",
            classification=CostClassification.EXPENSE,
            depreciation_category=DepreciationCategory.NONE,
            amount_base_year=10_851_810.7,
            base_year=2008,
            begin_year=36,
            end_year=85,
            recurrence="annual",
        ),
    ]

    return CostCatalog(items=items, base_year=2008, currency="USD")


# ============================================================================
# Tests
# ============================================================================


class TestFYBESolver:
    """Test FYBE break-even solver."""

    def test_fybe_solver_converges(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """solve_fybe returns a positive FYBEResult for valid inputs."""
        result = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )
        assert isinstance(result, FYBEResult)
        assert result.fybe_base_year > 0

    def test_fybe_2008_netl_default(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """FYBE for NETL offshore default produces $25.34/t (2008$) within $0.01."""
        result = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )
        assert result.fybe_base_year == pytest.approx(25.34, abs=0.01)

    def test_fybe_2024_netl_default(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """FYBE * escalation_factor within $0.01 of $72.20/t (2024$)."""
        result = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )
        assert result.fybe_current_year == pytest.approx(72.20, abs=0.01)

    def test_npv_at_fybe_approximately_zero(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """build_cashflow_model at FYBE price has NPV within $1000 of zero."""
        result = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )
        # Build model at the solved FYBE price
        model = build_cashflow_model(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
            co2_price=result.fybe_base_year,
        )
        assert abs(model.npv()) < 1000.0

    def test_norwegian_revenue_reduces_fybe(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """solve_fybe with Norwegian revenue streams produces lower FYBE."""
        result_base = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )

        revenue_streams = RevenueStreams(
            ets_price_eur_per_tonne=70.0,
            co2_tax_per_tonne=70.0,
        )

        result_norway = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
            revenue_streams=revenue_streams,
        )

        assert result_norway.fybe_base_year < result_base.fybe_base_year

    def test_fybe_result_fields(
        self,
        sample_cost_catalog,
        sample_schedule,
        netl_financial_params,
        netl_tax_regime,
        netl_escalation_config,
    ):
        """FYBEResult has all expected fields."""
        result = solve_fybe(
            cost_catalog=sample_cost_catalog,
            schedule=sample_schedule,
            financial_params=netl_financial_params,
            tax_regime=netl_tax_regime,
            escalation=netl_escalation_config,
        )
        assert hasattr(result, "fybe_base_year")
        assert hasattr(result, "fybe_current_year")
        assert hasattr(result, "base_year")
        assert hasattr(result, "current_year")
        assert hasattr(result, "npv")
        assert hasattr(result, "total_capex")
        assert hasattr(result, "total_opex")
        assert result.base_year == 2008
        assert result.current_year == 2024

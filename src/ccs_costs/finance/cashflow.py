"""85-year annual cashflow model for CCS cost estimation.

Builds year-by-year cashflows from CostCatalog + ProjectSchedule + financial
parameters, applying escalation, depreciation, tax, and discounting.

Maps directly to NETL FinMod_Main sheet columns:
    Col C: project_year (1-85)
    Col D: calendar year (2024-2108)
    Col E-F: escalation factors
    Col G: revenue (CO2_price * tonnes * escalation)
    Col H-J: CAPEX by depreciation category (nominal)
    Col K-L: OPEX (nominal)
    Col M-P: depreciation (4 categories)
    Col Q: interest on debt
    Col R: taxable income
    Col S: tax
    Col T-U: debt principal
    Col V: net cashflow
    Col W: discounted cashflow (PV at cost of equity)

NETL reference values (offshore default):
    FYBE (2008$): $25.34/t
    FYBE (2024$): $72.20/t
    Total CAPEX: $518,211,344 (real 2008$)
    Total O&M: $1,207,208,500 (real 2008$)
    Escalation factor 2008->2024: 2.8494392065079523
    Cost of equity: 10.8%
    Tax rate: 25.74%
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel

from ccs_costs.costs.catalog import CostCatalog, DepreciationCategory
from ccs_costs.finance.depreciation import DepreciationMethod, depreciation_amount
from ccs_costs.finance.escalation import EscalationConfig
from ccs_costs.finance.metrics import irr as compute_irr
from ccs_costs.finance.metrics import wacc as compute_wacc
from ccs_costs.finance.tax import TaxRegime, calculate_tax
from ccs_costs.geo.schedule import ProjectSchedule


# ============================================================================
# Data Models
# ============================================================================


class FinancialParams(BaseModel):
    """Financial model configuration.

    Attributes:
        equity_fraction: Fraction financed by equity (US: 0.45).
        cost_of_equity: Required return on equity (US: 10.8%).
        cost_of_debt: Interest rate on debt (US: 3.91%).
        base_cost_year: Year costs are expressed in (2008).
        project_start_year: Calendar year project starts (2024).
        tax_rate: Corporate tax rate for WACC calculation (default US 25.74%).
    """

    equity_fraction: float = 0.45
    cost_of_equity: float = 0.108
    cost_of_debt: float = 0.0391
    base_cost_year: int = 2008
    project_start_year: int = 2024
    tax_rate: float = 0.2574

    @property
    def wacc(self) -> float:
        """Weighted Average Cost of Capital."""
        return compute_wacc(
            self.equity_fraction,
            self.cost_of_equity,
            self.cost_of_debt,
            self.tax_rate,
        )

    @classmethod
    def from_region_config(cls, config: dict[str, Any]) -> FinancialParams:
        """Build FinancialParams from region config dict."""
        cap = config.get("capital_structure", {})
        esc = config.get("escalation", {})
        tax = config.get("tax_regime")
        tax_rate = tax.corporate_rate if tax else 0.2574
        return cls(
            equity_fraction=cap.get("equity_fraction", 0.45),
            cost_of_equity=cap.get("cost_of_equity", 0.108),
            cost_of_debt=cap.get("cost_of_debt", 0.0391),
            base_cost_year=esc.get("base_cost_year", 2008),
            project_start_year=esc.get("project_start_year", 2024),
            tax_rate=tax_rate,
        )


class RevenueStreams(BaseModel):
    """Additional revenue streams beyond CO2 storage fee (Norwegian model).

    Attributes:
        ets_price_eur_per_tonne: EU ETS price (EUR/t).
        co2_tax_per_tonne: Norwegian CO2 tax (per tonne).
        government_grant_fraction: Fraction of CAPEX covered by state.
        ets_escalation_rate: Annual ETS price increase rate.
        co2_tax_escalation_rate: Annual CO2 tax escalation rate.
    """

    ets_price_eur_per_tonne: float = 0.0
    co2_tax_per_tonne: float = 0.0
    government_grant_fraction: float = 0.0
    ets_escalation_rate: float = 0.02
    co2_tax_escalation_rate: float = 0.0

    def revenue_per_tonne(self, year_offset: int = 0) -> float:
        """Total additional revenue per tonne for a given year offset.

        Args:
            year_offset: Years from start (0 = first operations year).

        Returns:
            Total additional revenue per tonne.
        """
        ets = self.ets_price_eur_per_tonne * (
            (1.0 + self.ets_escalation_rate) ** year_offset
        )
        tax = self.co2_tax_per_tonne * (
            (1.0 + self.co2_tax_escalation_rate) ** year_offset
        )
        return ets + tax


class AnnualCashflow(BaseModel):
    """Single year in the cashflow model.

    All monetary values are in the year's respective currency basis:
    - *_real: base year dollars (2008$)
    - *_nominal: escalated to project year dollars
    - revenue, tax, etc: nominal dollars
    """

    year: int  # Calendar year
    project_year: int  # 1-based project year
    stage: str  # screening, characterization, etc.

    # Costs (base year dollars)
    capex_real: float = 0.0
    opex_real: float = 0.0

    # Escalated costs
    capex_nominal: float = 0.0
    opex_nominal: float = 0.0

    # Revenue
    co2_stored_tonnes: float = 0.0
    co2_price_per_tonne: float = 0.0
    revenue: float = 0.0

    # Additional revenue streams (Norwegian model)
    ets_revenue: float = 0.0
    co2_tax_revenue: float = 0.0
    government_grant: float = 0.0

    # Depreciation
    depreciation: float = 0.0

    # Tax
    taxable_income: float = 0.0
    tax: float = 0.0

    # Debt service
    debt_principal: float = 0.0
    interest_payment: float = 0.0

    # Cash flow
    net_cashflow: float = 0.0
    discounted_cashflow: float = 0.0


class CashflowModel(BaseModel):
    """Complete 85-year cashflow model."""

    years: list[AnnualCashflow]
    base_year: int
    currency: str
    discount_rate: float

    def npv(self) -> float:
        """Net present value = sum of discounted cashflows."""
        return sum(y.discounted_cashflow for y in self.years)

    def total_capex_real(self) -> float:
        """Total capital expenditure in base-year dollars."""
        return sum(y.capex_real for y in self.years)

    def total_opex_real(self) -> float:
        """Total operating expenditure in base-year dollars."""
        return sum(y.opex_real for y in self.years)

    def total_cost_real(self) -> float:
        """Total cost in base-year dollars."""
        return self.total_capex_real() + self.total_opex_real()

    def irr(self) -> float | None:
        """Internal rate of return."""
        cashflows = [y.net_cashflow for y in self.years]
        return compute_irr(cashflows)

    def to_dataframe(self) -> pd.DataFrame:
        """Export cashflow model as a pandas DataFrame.

        Returns:
            DataFrame with one row per year and all AnnualCashflow fields as columns.
        """
        records = [y.model_dump() for y in self.years]
        return pd.DataFrame(records)

    def to_csv(self, path: str | Path) -> None:
        """Export cashflow model to CSV file.

        Args:
            path: Output file path.
        """
        df = self.to_dataframe()
        df.to_csv(path, index=False)


# ============================================================================
# NETL Depreciation Map
# ============================================================================

# Maps DepreciationCategory -> (DepreciationMethod, recovery_period)
# Source: us-goa/finance.yaml depreciation_map
_US_DEPRECIATION_MAP: dict[str, tuple[DepreciationMethod, int]] = {
    DepreciationCategory.SITE_CHARACTERIZATION.value: (DepreciationMethod.DB150, 15),
    DepreciationCategory.SEISMIC.value: (DepreciationMethod.SL, 5),
    DepreciationCategory.WELLS.value: (DepreciationMethod.DB200, 5),
    DepreciationCategory.PLUG_ABANDON.value: (DepreciationMethod.DB200, 5),
    DepreciationCategory.PIPELINE.value: (DepreciationMethod.DB150, 20),
    DepreciationCategory.PLATFORM.value: (DepreciationMethod.DB150, 20),
}


# ============================================================================
# Build Function
# ============================================================================


def build_cashflow_model(
    cost_catalog: CostCatalog,
    schedule: ProjectSchedule,
    financial_params: FinancialParams,
    tax_regime: TaxRegime,
    escalation: EscalationConfig,
    revenue_streams: RevenueStreams | None = None,
    co2_price: float = 0.0,
    depreciation_map: dict[str, tuple[DepreciationMethod, int]] | None = None,
) -> CashflowModel:
    """Build complete 85-year cashflow model.

    Steps:
    1. Distribute cost items across years per catalog timing
    2. Escalate from base year to each project year
    3. Calculate depreciation by category
    4. Calculate debt service (interest + principal)
    5. Calculate taxable income and tax
    6. Calculate net cashflow per year
    7. Discount to present value

    Args:
        cost_catalog: CostCatalog with all cost items.
        schedule: ProjectSchedule with year-by-year timeline.
        financial_params: Financial parameters (equity, CoE, CoD, etc.).
        tax_regime: Tax regime configuration.
        escalation: Escalation configuration.
        revenue_streams: Optional Norwegian revenue streams.
        co2_price: CO2 storage price in base-year $/tonne (solved by FYBE).
        depreciation_map: Optional override for depreciation method/period mapping.

    Returns:
        CashflowModel with complete year-by-year cashflows.
    """
    n_years = len(schedule.timeline)
    dep_map = depreciation_map or _US_DEPRECIATION_MAP

    # Step 1: Get annual cost schedule from CostCatalog
    cost_df = cost_catalog.annual_schedule(n_years=n_years)

    # Extract capital costs per depreciation category for depreciation calculation
    dep_cats = [
        dc.value
        for dc in DepreciationCategory
        if dc != DepreciationCategory.NONE
    ]

    # Find first operations year (1-based project year)
    beg_yr = None
    end_yr = None
    for entry in schedule.timeline:
        if entry.stage == "operations":
            if beg_yr is None:
                beg_yr = entry.project_year
            end_yr = entry.project_year

    if beg_yr is None:
        beg_yr = 6  # Fallback to NETL default
        end_yr = 35

    # -----------------------------------------------------------------------
    # Step 2: Calculate escalation factors and nominal costs for each year
    # -----------------------------------------------------------------------
    capex_real_arr = [0.0] * n_years
    opex_real_arr = [0.0] * n_years
    capex_nom_arr = [0.0] * n_years
    opex_nom_arr = [0.0] * n_years
    esc_factors = [0.0] * n_years

    for i in range(n_years):
        entry = schedule.timeline[i]
        cal_year = entry.year

        # Cost schedule is 0-indexed
        capex_real_arr[i] = cost_df.iloc[i]["capital"]
        opex_real_arr[i] = cost_df.iloc[i]["expense"]

        # Escalation factor for this calendar year
        esc_factor = escalation.factor_for_year(cal_year)
        esc_factors[i] = esc_factor

        capex_nom_arr[i] = capex_real_arr[i] * esc_factor
        opex_nom_arr[i] = opex_real_arr[i] * esc_factor

    # -----------------------------------------------------------------------
    # Step 3: Depreciation -- per category, using depreciation_amount()
    # -----------------------------------------------------------------------
    depreciation_arr = [0.0] * n_years

    for dc_name in dep_cats:
        col_name = f"cap_{dc_name}"
        if col_name not in cost_df.columns:
            continue

        dep_config = dep_map.get(dc_name)
        if dep_config is None:
            continue

        method, recovery_period = dep_config

        # Get capital cost array for this depreciation category (real dollars)
        # Then escalate to nominal for depreciation basis
        cap_costs_nominal = []
        for i in range(n_years):
            real_val = cost_df.iloc[i][col_name]
            cap_costs_nominal.append(real_val * esc_factors[i])

        # Calculate depreciation for each year
        for yr in range(1, n_years + 1):  # 1-based
            dep_amt = depreciation_amount(
                capital_costs=cap_costs_nominal,
                beg_yr=beg_yr,
                end_yr=end_yr + recovery_period,  # Allow depreciation to continue after ops
                method=method,
                recovery_period=recovery_period,
                yr=yr,
            )
            depreciation_arr[yr - 1] += dep_amt

    # -----------------------------------------------------------------------
    # Step 4: Debt service
    # -----------------------------------------------------------------------
    debt_fraction = 1.0 - financial_params.equity_fraction
    total_capex_nominal = sum(capex_nom_arr)
    total_debt = total_capex_nominal * debt_fraction

    # Amortize over operations period using standard constant payment schedule
    ops_duration = end_yr - beg_yr + 1 if end_yr and beg_yr else 30
    r_debt = financial_params.cost_of_debt

    # Standard annuity payment: PMT = PV * r / (1 - (1+r)^-n)
    if r_debt > 0 and ops_duration > 0:
        annual_debt_payment = total_debt * r_debt / (
            1.0 - (1.0 + r_debt) ** (-ops_duration)
        )
    elif ops_duration > 0:
        annual_debt_payment = total_debt / ops_duration
    else:
        annual_debt_payment = 0.0

    # Build amortization schedule
    interest_arr = [0.0] * n_years
    principal_arr = [0.0] * n_years
    outstanding_debt = total_debt

    ops_year_count = 0
    for i in range(n_years):
        entry = schedule.timeline[i]
        if entry.stage == "operations":
            ops_year_count += 1
            if outstanding_debt > 0:
                interest = outstanding_debt * r_debt
                principal = annual_debt_payment - interest
                # Ensure we don't overpay
                principal = min(principal, outstanding_debt)
                interest_arr[i] = interest
                principal_arr[i] = principal
                outstanding_debt -= principal

    # -----------------------------------------------------------------------
    # Step 5 & 6 & 7: Tax, net cashflow, discounting -- per year
    # -----------------------------------------------------------------------
    annual_cashflows: list[AnnualCashflow] = []

    # Track first operations year index for revenue stream year offset
    first_ops_idx = None
    for i, entry in enumerate(schedule.timeline):
        if entry.stage == "operations":
            first_ops_idx = i
            break

    for i in range(n_years):
        entry = schedule.timeline[i]
        esc_factor = esc_factors[i]

        # Revenue: CO2 price * tonnes * escalation factor
        # CO2 price is in base-year dollars, escalate to nominal
        co2_tonnes = entry.co2_injected_tonnes
        revenue = co2_price * co2_tonnes * esc_factor

        # Norwegian revenue streams
        ets_rev = 0.0
        co2_tax_rev = 0.0
        govt_grant = 0.0

        if revenue_streams is not None and co2_tonnes > 0:
            # Year offset from first operations year
            year_offset = i - first_ops_idx if first_ops_idx is not None else 0
            ets_rev = (
                revenue_streams.ets_price_eur_per_tonne
                * ((1.0 + revenue_streams.ets_escalation_rate) ** year_offset)
                * co2_tonnes
            )
            co2_tax_rev = (
                revenue_streams.co2_tax_per_tonne
                * ((1.0 + revenue_streams.co2_tax_escalation_rate) ** year_offset)
                * co2_tonnes
            )

        if revenue_streams is not None and revenue_streams.government_grant_fraction > 0:
            # Government grant on CAPEX (only during construction)
            if entry.stage in ("permitting_construction", "construction"):
                govt_grant = revenue_streams.government_grant_fraction * capex_nom_arr[i]

        total_revenue = revenue + ets_rev + co2_tax_rev + govt_grant

        # Tax calculation
        tax_result = calculate_tax(
            revenue=total_revenue,
            opex=opex_nom_arr[i],
            depreciation=depreciation_arr[i],
            interest=interest_arr[i],
            regime=tax_regime,
        )

        # Net cashflow (NETL FinMod_Main Col V formulation)
        # Net CF = Revenue - OPEX_nominal - CAPEX_nominal - Tax - Interest
        #
        # NETL uses a hybrid approach: full CAPEX in cashflow (project
        # perspective) but also subtracts actual interest payments. The
        # interest deduction appears in BOTH the tax calculation (reducing
        # taxable income) AND in the net cashflow (as a cash outflow).
        # This is consistent with NETL's FinMod_Main Column V which
        # includes interest as a separate cash outflow alongside CAPEX.
        # Discounted at CoE (10.8%), not WACC.
        net_cf = (
            total_revenue
            - opex_nom_arr[i]
            - capex_nom_arr[i]
            - tax_result.tax
            - interest_arr[i]
        )

        # Discount factor: (1 + CoE)^(project_year - 1)
        # Year 1 is undiscounted (factor = 1.0)
        discount_factor = (1.0 + financial_params.cost_of_equity) ** (
            entry.project_year - 1
        )
        discounted_cf = net_cf / discount_factor

        annual_cashflows.append(
            AnnualCashflow(
                year=entry.year,
                project_year=entry.project_year,
                stage=entry.stage,
                capex_real=capex_real_arr[i],
                opex_real=opex_real_arr[i],
                capex_nominal=capex_nom_arr[i],
                opex_nominal=opex_nom_arr[i],
                co2_stored_tonnes=co2_tonnes,
                co2_price_per_tonne=co2_price * esc_factor,
                revenue=revenue,
                ets_revenue=ets_rev,
                co2_tax_revenue=co2_tax_rev,
                government_grant=govt_grant,
                depreciation=depreciation_arr[i],
                taxable_income=tax_result.taxable_income,
                tax=tax_result.tax,
                debt_principal=principal_arr[i],
                interest_payment=interest_arr[i],
                net_cashflow=net_cf,
                discounted_cashflow=discounted_cf,
            )
        )

    return CashflowModel(
        years=annual_cashflows,
        base_year=financial_params.base_cost_year,
        currency=cost_catalog.currency,
        discount_rate=financial_params.cost_of_equity,
    )

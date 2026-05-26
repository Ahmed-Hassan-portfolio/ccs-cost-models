"""FYBE break-even solver -- find CO2 price where NPV = 0.

The First Year Break-Even (FYBE) solver is the core output of the CCS
cost estimation engine. It finds the CO2 storage price (in base-year
dollars) that makes the 85-year cashflow model NPV equal zero.

Uses scipy.optimize.brentq for root-finding (guaranteed convergence
within bracket, replacing VBA Excel GoalSeek binary search).

NETL reference (offshore default):
    FYBE (2008$): $25.3376/t (report as $25.34/t)
    FYBE (2024$): $72.1980/t (report as $72.20/t)
"""

from __future__ import annotations

from pydantic import BaseModel
from scipy.optimize import brentq

from ccs_costs.costs.catalog import CostCatalog
from ccs_costs.finance.cashflow import (
    CashflowModel,
    FinancialParams,
    RevenueStreams,
    build_cashflow_model,
)
from ccs_costs.finance.escalation import EscalationConfig
from ccs_costs.finance.metrics import lcoe_storage
from ccs_costs.finance.tax import TaxRegime
from ccs_costs.geo.schedule import ProjectSchedule


class FYBEResult(BaseModel):
    """Result of FYBE solver.

    Attributes:
        fybe_base_year: Break-even CO2 price in base-year $/t.
        fybe_current_year: Break-even CO2 price escalated to current year $/t.
        base_year: Base cost year (e.g. 2008).
        current_year: Project start year (e.g. 2024).
        npv: NPV at the solved FYBE price (should be ~0).
        total_capex: Total capital expenditure (real, base-year $).
        total_opex: Total operating expenditure (real, base-year $).
        lcoe: Levelized cost of CO2 storage ($/t, approximate).
    """

    fybe_base_year: float
    fybe_current_year: float
    base_year: int
    current_year: int
    npv: float
    total_capex: float
    total_opex: float
    lcoe: float = 0.0


def solve_fybe(
    cost_catalog: CostCatalog,
    schedule: ProjectSchedule,
    financial_params: FinancialParams,
    tax_regime: TaxRegime,
    escalation: EscalationConfig,
    revenue_streams: RevenueStreams | None = None,
    price_range: tuple[float, float] = (0.0, 500.0),
    tolerance: float = 0.0001,
) -> FYBEResult:
    """Find the first-year break-even CO2 storage price.

    Uses brentq root-finding to find co2_price where NPV(cashflow model) = 0.

    Args:
        cost_catalog: CostCatalog with all cost items.
        schedule: ProjectSchedule with timeline.
        financial_params: Financial parameters.
        tax_regime: Tax regime configuration.
        escalation: Escalation configuration.
        revenue_streams: Optional Norwegian revenue streams.
        price_range: Search bracket for CO2 price (default 0 to 500 $/t).
        tolerance: Solver tolerance in $/t.

    Returns:
        FYBEResult with solved break-even price and summary metrics.

    Raises:
        ValueError: If solver cannot converge (no root in bracket).
    """

    def npv_at_price(co2_price: float) -> float:
        """Build a cashflow model at a candidate CO2 price and return its NPV.

        Used by brentq to find the CO2 price where NPV equals zero
        (the first-year break-even price).

        Args:
            co2_price: Candidate CO2 storage price in base-year $/t.

        Returns:
            NPV of the project at the given CO2 price.
        """
        model = build_cashflow_model(
            cost_catalog=cost_catalog,
            schedule=schedule,
            financial_params=financial_params,
            tax_regime=tax_regime,
            escalation=escalation,
            revenue_streams=revenue_streams,
            co2_price=co2_price,
        )
        return model.npv()

    # Solve for NPV = 0
    # Check if bracket signs differ; if not, widen to negative prices
    # (Norwegian revenue streams can make NPV > 0 at co2_price = 0,
    #  meaning the project is profitable even without a storage fee --
    #  the FYBE is negative, representing a subsidy/surplus.)
    lo, hi = price_range
    npv_lo = npv_at_price(lo)
    npv_hi = npv_at_price(hi)
    if npv_lo * npv_hi > 0:
        # Both same sign -- try expanding lower bracket to negative
        lo = -hi  # e.g. -500
        npv_lo = npv_at_price(lo)
        if npv_lo * npv_hi > 0:
            raise ValueError(
                f"FYBE solver: NPV has same sign at both bracket ends "
                f"[{lo}, {hi}]: [{npv_lo:.2f}, {npv_hi:.2f}]. "
                f"Cannot find break-even price."
            )
    fybe = brentq(npv_at_price, lo, hi, xtol=tolerance)

    # Build final model at solved price for metrics
    final_model = build_cashflow_model(
        cost_catalog=cost_catalog,
        schedule=schedule,
        financial_params=financial_params,
        tax_regime=tax_regime,
        escalation=escalation,
        revenue_streams=revenue_streams,
        co2_price=fybe,
    )

    # Escalate FYBE to current year
    fybe_current = fybe * escalation.base_to_start_factor

    # Compute approximate LCOE
    total_co2 = schedule.total_co2_tonnes
    total_cost_real = final_model.total_cost_real()
    lcoe_val = total_cost_real / total_co2 if total_co2 > 0 else 0.0

    return FYBEResult(
        fybe_base_year=fybe,
        fybe_current_year=fybe_current,
        base_year=financial_params.base_cost_year,
        current_year=financial_params.project_start_year,
        npv=final_model.npv(),
        total_capex=final_model.total_capex_real(),
        total_opex=final_model.total_opex_real(),
        lcoe=lcoe_val,
    )

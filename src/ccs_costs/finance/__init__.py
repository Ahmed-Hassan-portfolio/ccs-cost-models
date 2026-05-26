"""Finance package -- escalation, depreciation, metrics, tax, cashflow, solver.

Re-exports all public names from submodules for convenient access:
    from ccs_costs.finance import solve_fybe, build_cashflow_model, escalate_cost
"""

from __future__ import annotations

from ccs_costs.finance.cashflow import (  # noqa: F401
    AnnualCashflow,
    CashflowModel,
    FinancialParams,
    RevenueStreams,
    build_cashflow_model,
)
from ccs_costs.finance.depreciation import (  # noqa: F401
    MACRS_TABLES,
    DepreciationMethod,
    depreciation_amount,
    norwegian_linear_depreciation,
)
from ccs_costs.finance.escalation import (  # noqa: F401
    EscalationConfig,
    escalate_cost,
    load_escalation_indices,
)
from ccs_costs.finance.fr_instruments import (  # noqa: F401
    FRConfig,
    FRInstrument,
    calculate_fr_costs,
    norwegian_financial_security,
)
from ccs_costs.finance.metrics import (  # noqa: F401
    irr,
    lcoe_storage,
    npv,
    wacc,
)
from ccs_costs.finance.solver import (  # noqa: F401
    FYBEResult,
    solve_fybe,
)
from ccs_costs.finance.tax import (  # noqa: F401
    TaxRegime,
    TaxResult,
    calculate_tax,
    load_finance_config,
)

__all__ = [
    # Cashflow
    "AnnualCashflow",
    "CashflowModel",
    "FinancialParams",
    "RevenueStreams",
    "build_cashflow_model",
    # Solver
    "FYBEResult",
    "solve_fybe",
    # Escalation
    "EscalationConfig",
    "escalate_cost",
    "load_escalation_indices",
    # Depreciation
    "DepreciationMethod",
    "depreciation_amount",
    "norwegian_linear_depreciation",
    "MACRS_TABLES",
    # Metrics
    "npv",
    "irr",
    "wacc",
    "lcoe_storage",
    # Tax
    "TaxRegime",
    "TaxResult",
    "calculate_tax",
    "load_finance_config",
    # FR Instruments
    "FRInstrument",
    "FRConfig",
    "calculate_fr_costs",
    "norwegian_financial_security",
]

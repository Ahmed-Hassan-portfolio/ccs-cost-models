"""Financial metrics -- NPV, IRR, WACC, LCOE-storage.

NPV uses NETL convention: year 1 (index 0) is undiscounted (factor = 1.0).
This means discount factor = 1/(1+r)^n where n=0 for year 1, n=1 for year 2, etc.

IRR uses scipy.optimize.brentq for root-finding (guaranteed convergence
within bracket, unlike Newton-Raphson).

WACC and LCOE-storage are straightforward arithmetic.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike
from scipy.optimize import brentq


def npv(cashflows: ArrayLike, discount_rate: float) -> float:
    """Net Present Value with NETL convention (year 1 undiscounted).

    Discount factors: (1+r)^0=1.0, (1+r)^1, (1+r)^2, ...
    NPV = sum(cf[i] / (1+r)^i) for i = 0, 1, 2, ...

    This matches NETL FinMod_Main where year 1 has discount factor 1.0
    and year 2 has discount factor (1 + cost_of_equity).

    Args:
        cashflows: Array of annual cashflows. Index 0 = year 1.
        discount_rate: Annual discount rate (e.g. 0.108 for 10.8%).

    Returns:
        Net present value.
    """
    cf = np.asarray(cashflows, dtype=np.float64)
    if len(cf) == 0:
        return 0.0
    n = np.arange(len(cf))
    factors = (1.0 + discount_rate) ** n
    return float(np.sum(cf / factors))


def irr(cashflows: ArrayLike) -> float | None:
    """Internal Rate of Return -- discount rate where NPV = 0.

    Uses scipy.optimize.brentq with bracket [-0.5, 10.0].
    Returns None if no root exists (e.g. all positive cashflows).

    Args:
        cashflows: Array of annual cashflows. Must have at least one
            sign change for a root to exist.

    Returns:
        IRR as a decimal fraction (e.g. 0.10 for 10%), or None.
    """
    cf = np.asarray(cashflows, dtype=np.float64)

    # Quick check: need at least one sign change
    signs = np.sign(cf[cf != 0])
    if len(signs) < 2 or np.all(signs == signs[0]):
        return None

    def npv_at_rate(r: float) -> float:
        """Evaluate NPV at a candidate discount rate for root-finding.

        Args:
            r: Candidate discount rate to test.

        Returns:
            NPV of the cashflows at rate r.
        """
        return npv(cf, r)

    try:
        result = brentq(npv_at_rate, -0.5, 10.0, xtol=1e-8)
        return float(result)
    except ValueError:
        # No root in bracket
        return None


def wacc(
    equity_fraction: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
) -> float:
    """Weighted Average Cost of Capital.

    WACC = E/V * Re + D/V * Rd * (1 - Tc)

    Where:
        E/V = equity fraction
        D/V = debt fraction = 1 - equity_fraction
        Re = cost of equity
        Rd = cost of debt
        Tc = corporate tax rate

    Args:
        equity_fraction: Fraction of financing from equity (0-1).
        cost_of_equity: Required return on equity.
        cost_of_debt: Interest rate on debt.
        tax_rate: Corporate tax rate.

    Returns:
        WACC as a decimal fraction.
    """
    debt_fraction = 1.0 - equity_fraction
    return equity_fraction * cost_of_equity + debt_fraction * cost_of_debt * (
        1.0 - tax_rate
    )


def lcoe_storage(
    total_cost_pv: float,
    total_co2_stored_pv: float,
) -> float:
    """Levelized Cost of CO2 Storage.

    LCOE = PV(total costs) / PV(total CO2 stored)

    A simpler alternative to the FYBE solver. Less accurate because
    it doesn't account for the iterative relationship between revenue,
    tax, and NPV.

    Args:
        total_cost_pv: Present value of all costs.
        total_co2_stored_pv: Present value of total CO2 stored (tonnes).

    Returns:
        LCOE in $/tonne (or whatever currency the costs are in).
    """
    return total_cost_pv / total_co2_stored_pv

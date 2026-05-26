"""Depreciation schedules -- MACRS and Norwegian linear.

Translated from VBA modDepFunc.bas (David Morgan, NETL).

MACRS tables are IRS Publication 946, Table A-1 (DB methods) and Table A-8
(SL methods). Values are the EXACT percentages from the VBA source, stored
as decimal fractions. All 6 supported method/period combinations are included.

The depreciation_amount() function is a direct translation of VBA DepAmt(),
preserving its 1-based year indexing and pre-operations capital accumulation
logic.
"""

from __future__ import annotations

from enum import Enum


class DepreciationMethod(str, Enum):
    """Depreciation method identifiers."""

    SL = "SL"  # Straight line (MACRS GDS)
    DB150 = "DB150"  # 150% declining balance (MACRS GDS)
    DB200 = "DB200"  # 200% declining balance (MACRS GDS)
    NO_LIN = "NO_LIN"  # Norwegian linear (equal annual, no half-year)


# ---------------------------------------------------------------------------
# MACRS factor tables -- EXACT values from VBA modDepFunc.bas
# Keys: "{method}_{recovery_period}" e.g. "DB200_5", "SL_15"
# Values: tuple of annual depreciation fractions (sum to 1.0)
# ---------------------------------------------------------------------------

MACRS_TABLES: dict[str, tuple[float, ...]] = {
    "DB200_5": (0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576),
    "SL_5": (0.10, 0.20, 0.20, 0.20, 0.20, 0.10),
    "DB150_15": (
        0.05,
        0.095,
        0.0855,
        0.077,
        0.0693,
        0.0623,
        0.059,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.059,
        0.0591,
        0.0295,
    ),
    "SL_15": (
        0.0333,
        0.0667,
        0.0667,
        0.0667,
        0.0667,
        0.0667,
        0.0667,
        0.0666,
        0.0667,
        0.0666,
        0.0667,
        0.0666,
        0.0667,
        0.0666,
        0.0667,
        0.0333,
    ),
    "DB150_20": (
        0.0375,
        0.07219,
        0.06677,
        0.06177,
        0.05713,
        0.05285,
        0.04888,
        0.04522,
        0.04462,
        0.04461,
        0.04462,
        0.04461,
        0.04462,
        0.04461,
        0.04462,
        0.04461,
        0.04462,
        0.04461,
        0.04462,
        0.04461,
        0.02231,
    ),
    "SL_20": (
        0.025,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.05,
        0.025,
    ),
}

# Valid method/period combinations (from VBA DepAmt)
_VALID_COMBOS: set[str] = {
    "SL_5",
    "SL_15",
    "SL_20",
    "DB150_15",
    "DB150_20",
    "DB200_5",
}


def _get_macrs_factor(table_key: str, start_yr: int, cur_yr: int) -> float:
    """Return MACRS depreciation factor for a single asset.

    Translated from VBA MACRS_GDS_*() functions.

    Args:
        table_key: Key into MACRS_TABLES (e.g. "DB200_5").
        start_yr: Year when equipment was placed into service (1-based).
        cur_yr: Year when depreciation factor is desired (1-based).

    Returns:
        Depreciation factor (0.0 if outside valid range).
    """
    factors = MACRS_TABLES[table_key]
    yr = cur_yr - start_yr + 1
    if yr < 1 or yr > len(factors):
        return 0.0
    return factors[yr - 1]  # Convert 1-based VBA index to 0-based Python


def depreciation_amount(
    capital_costs: list[float],
    beg_yr: int,
    end_yr: int,
    method: DepreciationMethod,
    recovery_period: int,
    yr: int,
) -> float:
    """Calculate depreciation amount for a given year.

    Direct translation of VBA DepAmt() from modDepFunc.bas.

    Pre-operations capital accumulation: all capital costs before beg_yr are
    summed and added to the beg_yr position. This models the fact that
    equipment placed before operations begins starts depreciating in the
    first operations year.

    Uses 1-based year indexing consistent with VBA source:
    - Year 1 is the first project year
    - beg_yr is the first year of operations

    Args:
        capital_costs: Annual capital costs for each project year (0-indexed
            Python list, but representing 1-based project years).
        beg_yr: First year of operations (1-based).
        end_yr: Last year for depreciation (1-based).
        method: Depreciation method (SL, DB150, DB200).
        recovery_period: Recovery period in years (5, 15, or 20).
        yr: Project year to compute depreciation for (1-based).

    Returns:
        Depreciation amount for the given year.

    Raises:
        ValueError: If method/recovery_period combination is not valid.
    """
    # Validate method/period combination
    if method == DepreciationMethod.NO_LIN:
        raise ValueError(
            "Use norwegian_linear_depreciation() for Norwegian linear method"
        )

    table_key = f"{method.value}_{recovery_period}"
    if table_key not in _VALID_COMBOS:
        raise ValueError(
            f"Invalid depreciation method/period combination: {method.value}/{recovery_period}. "
            f"Valid combinations: {sorted(_VALID_COMBOS)}"
        )

    # Validate inputs
    if beg_yr < 1 or end_yr < 1:
        raise ValueError("beg_yr and end_yr must be > 0")
    if beg_yr > end_yr:
        raise ValueError("beg_yr must be <= end_yr")

    # Return 0 outside depreciation window
    if yr < beg_yr or yr > end_yr:
        return 0.0

    # Create modified capital cost array with pre-ops accumulation
    # VBA uses 1-based arrays; we use 0-based Python lists
    # capital_costs[0] = year 1, capital_costs[1] = year 2, etc.
    modified = list(capital_costs)

    # Ensure array is long enough
    while len(modified) < yr:
        modified.append(0.0)

    # Accumulate pre-operations capital into beg_yr
    if beg_yr > 1:
        pre_ops_sum = 0.0
        for i in range(beg_yr - 1):  # Python 0-based: indices 0..beg_yr-2
            pre_ops_sum += modified[i]
            modified[i] = 0.0
        modified[beg_yr - 1] += pre_ops_sum  # Add to beg_yr position

    # Calculate depreciation
    # YrOp = yr - beg_yr + 1 (year of operations, 1-based)
    yr_op = yr - beg_yr + 1

    total = 0.0
    for i in range(1, yr_op + 1):  # VBA: For i = 1 To YrOp
        # VBA: MACRS_GDS_*(Start_yr=i, Cur_yr=YrOp) -> Yr = YrOp - i + 1
        dep_factor = _get_macrs_factor(table_key, start_yr=i, cur_yr=yr_op)
        # VBA: CapCostsModArr(1, i + BegYr - 1)
        cost_idx = i + beg_yr - 2  # Convert to 0-based Python index
        if cost_idx < len(modified):
            total += modified[cost_idx] * dep_factor

    return total


def norwegian_linear_depreciation(
    asset_value: float,
    recovery_years: int,
) -> list[float]:
    """Norwegian linear depreciation -- equal annual amounts.

    No half-year convention. Simply divides asset value equally across
    the recovery period.

    Args:
        asset_value: Total asset value to depreciate.
        recovery_years: Number of years over which to depreciate.

    Returns:
        List of annual depreciation amounts (length = recovery_years).
    """
    annual_amount = asset_value / recovery_years
    return [annual_amount] * recovery_years

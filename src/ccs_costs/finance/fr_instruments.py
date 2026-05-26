"""Financial responsibility (FR) instrument cost calculations.

Implements US EPA financial assurance instruments required for CO2 storage:
- Trust Fund: sinking fund accumulating to cover future liabilities
- Escrow: equal annual payments
- Surety Bond: annual premium as fraction of liability
- Insurance: annual premium as fraction of liability
- Letter of Credit: annual fee as fraction of liability

Norwegian equivalent: simple parent company or bank guarantee modeled
as an annual cost fraction of outstanding liability.

VBA source: TrFndCalcsCol function in aaMain.bas (lines 451-648).
The Python implementation uses the standard sinking fund formula
rather than the year-by-year withdrawal-based VBA approach, producing
equivalent results for the constant-deposit case.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ccs_costs.costs.catalog import CostClassification, CostItem, DepreciationCategory


class FRInstrument(str, Enum):
    """Financial responsibility instrument types (US EPA)."""

    TRUST_FUND = "trust_fund"
    ESCROW = "escrow"
    SURETY_BOND = "surety_bond"
    INSURANCE = "insurance"
    LETTER_OF_CREDIT = "letter_of_credit"


class FRConfig(BaseModel):
    """Configuration for a financial responsibility instrument.

    Attributes:
        instrument: Which FR instrument to use.
        interest_rate: Annual interest rate for trust fund accumulation.
        premium_rate: Annual premium rate for surety bond or insurance.
        fee_rate: Annual fee rate for letter of credit.
        n_years: Number of years for deposit period (trust fund/escrow).
    """

    instrument: FRInstrument = FRInstrument.TRUST_FUND
    interest_rate: float = 0.015  # Trust fund default: 1.5%
    premium_rate: float = 0.02  # Surety/insurance default: 2%
    fee_rate: float = 0.015  # Letter of credit default: 1.5%
    n_years: int = 30  # Default deposit period

    @classmethod
    def us_default(cls) -> FRConfig:
        """US default: trust fund for all categories.

        Source: NETL CO2_S_COM_Offshore FR Details sheet.
        """
        return cls(
            instrument=FRInstrument.TRUST_FUND,
            interest_rate=0.015,
            premium_rate=0.02,
            fee_rate=0.015,
            n_years=30,
        )


# ============================================================================
# Instrument calculation functions
# ============================================================================


def trust_fund_schedule(
    liability: float,
    n_years: int,
    interest_rate: float,
) -> list[float]:
    """Calculate annual trust fund deposit schedule.

    Uses the sinking fund formula to compute equal annual deposits
    that accumulate with compound interest to equal the target liability.

    Deposits are made at the start of each year; interest compounds
    annually. This is an annuity-due sinking fund.

    Formula: deposit = liability * r / ((1+r)^n - 1) / (1+r)
    where the extra (1+r) accounts for deposits at start of year.

    For zero interest: deposit = liability / n_years.

    Translated from VBA TrFndCalcsCol in aaMain.bas. The VBA function
    handles withdrawal-specific deposits; this simplified version
    produces equal annual deposits for a single target liability.

    Args:
        liability: Total target amount to accumulate.
        n_years: Number of years of deposits.
        interest_rate: Annual interest rate earned by the fund.

    Returns:
        List of n_years equal annual deposit amounts.
    """
    if n_years <= 0:
        return []

    if interest_rate == 0.0:
        deposit = liability / n_years
    else:
        r = interest_rate
        # Annuity-due sinking fund: deposit at start of year, interest at end
        # Balance after n years = deposit * sum_{k=1}^{n} (1+r)^k
        # = deposit * (1+r) * ((1+r)^n - 1) / r
        # Set equal to liability and solve for deposit:
        factor = (1 + r) * ((1 + r) ** n_years - 1) / r
        deposit = liability / factor

    return [deposit] * n_years


def escrow_schedule(
    liability: float,
    n_years: int,
) -> list[float]:
    """Calculate escrow equal annual payment schedule.

    Simple: liability / n_years per year, no interest accumulation.

    Args:
        liability: Total amount to be escrowed.
        n_years: Number of years of payments.

    Returns:
        List of n_years equal annual payment amounts.
    """
    if n_years <= 0:
        return []
    payment = liability / n_years
    return [payment] * n_years


def surety_bond_annual(
    liability: float,
    premium_rate: float,
) -> float:
    """Calculate annual surety bond premium.

    Annual premium = liability * premium_rate. Typically 1-3%.

    Args:
        liability: Total liability amount covered by the bond.
        premium_rate: Annual premium as fraction of liability.

    Returns:
        Annual surety bond premium.
    """
    return liability * premium_rate


def insurance_annual(
    liability: float,
    premium_rate: float,
) -> float:
    """Calculate annual insurance premium.

    Annual premium = liability * premium_rate. Typically 1-3%.

    Args:
        liability: Total liability amount covered by insurance.
        premium_rate: Annual premium as fraction of liability.

    Returns:
        Annual insurance premium.
    """
    return liability * premium_rate


def letter_of_credit_annual(
    liability: float,
    fee_rate: float,
) -> float:
    """Calculate annual letter of credit fee.

    Annual fee = liability * fee_rate. Typically 1-2%.

    Args:
        liability: Total liability amount covered by LOC.
        fee_rate: Annual fee as fraction of liability.

    Returns:
        Annual letter of credit fee.
    """
    return liability * fee_rate


# ============================================================================
# Cost item generation
# ============================================================================


def calculate_fr_costs(
    fr_config: FRConfig,
    total_liability: float,
    operations_start_year: int,
    operations_end_year: int,
) -> list[CostItem]:
    """Calculate FR instrument costs as CostItems.

    Generates one or more CostItem objects representing the annual
    cost of maintaining the selected financial responsibility instrument
    during the operations period.

    For trust fund/escrow: generates an annual cost item covering the
    deposit period. For surety/insurance/LOC: generates an annual cost
    item for the premium/fee.

    All FR costs are classified as EXPENSE with DepreciationCategory.NONE
    (they are operating costs, not capital).

    Args:
        fr_config: FR instrument configuration.
        total_liability: Total liability to be covered ($).
        operations_start_year: Project year when operations begin.
        operations_end_year: Project year when operations end.

    Returns:
        List of CostItem objects with FR instrument costs.
    """
    items: list[CostItem] = []
    n_ops_years = operations_end_year - operations_start_year + 1

    if fr_config.instrument == FRInstrument.TRUST_FUND:
        schedule = trust_fund_schedule(
            total_liability, n_ops_years, fr_config.interest_rate
        )
        if schedule:
            annual_deposit = schedule[0]
            items.append(
                CostItem(
                    id="fr_trust_fund_deposit",
                    name="Trust Fund Annual Deposit",
                    category="financial_responsibility",
                    subcategory="trust_fund",
                    stage="operations",
                    classification=CostClassification.EXPENSE,
                    depreciation_category=DepreciationCategory.NONE,
                    amount_base_year=annual_deposit,
                    base_year=2008,
                    currency="USD",
                    begin_year=operations_start_year,
                    end_year=operations_end_year,
                    recurrence="annual",
                    notes=f"Sinking fund deposit at {fr_config.interest_rate:.1%} interest",
                )
            )

    elif fr_config.instrument == FRInstrument.ESCROW:
        schedule = escrow_schedule(total_liability, n_ops_years)
        if schedule:
            annual_payment = schedule[0]
            items.append(
                CostItem(
                    id="fr_escrow_payment",
                    name="Escrow Annual Payment",
                    category="financial_responsibility",
                    subcategory="escrow",
                    stage="operations",
                    classification=CostClassification.EXPENSE,
                    depreciation_category=DepreciationCategory.NONE,
                    amount_base_year=annual_payment,
                    base_year=2008,
                    currency="USD",
                    begin_year=operations_start_year,
                    end_year=operations_end_year,
                    recurrence="annual",
                    notes="Equal annual escrow payment",
                )
            )

    elif fr_config.instrument == FRInstrument.SURETY_BOND:
        annual = surety_bond_annual(total_liability, fr_config.premium_rate)
        items.append(
            CostItem(
                id="fr_surety_bond_premium",
                name="Surety Bond Annual Premium",
                category="financial_responsibility",
                subcategory="surety_bond",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual,
                base_year=2008,
                currency="USD",
                begin_year=operations_start_year,
                end_year=operations_end_year,
                recurrence="annual",
                notes=f"Premium at {fr_config.premium_rate:.1%} of liability",
            )
        )

    elif fr_config.instrument == FRInstrument.INSURANCE:
        annual = insurance_annual(total_liability, fr_config.premium_rate)
        items.append(
            CostItem(
                id="fr_insurance_premium",
                name="Insurance Annual Premium",
                category="financial_responsibility",
                subcategory="insurance",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual,
                base_year=2008,
                currency="USD",
                begin_year=operations_start_year,
                end_year=operations_end_year,
                recurrence="annual",
                notes=f"Premium at {fr_config.premium_rate:.1%} of liability",
            )
        )

    elif fr_config.instrument == FRInstrument.LETTER_OF_CREDIT:
        annual = letter_of_credit_annual(total_liability, fr_config.fee_rate)
        items.append(
            CostItem(
                id="fr_letter_of_credit_fee",
                name="Letter of Credit Annual Fee",
                category="financial_responsibility",
                subcategory="letter_of_credit",
                stage="operations",
                classification=CostClassification.EXPENSE,
                depreciation_category=DepreciationCategory.NONE,
                amount_base_year=annual,
                base_year=2008,
                currency="USD",
                begin_year=operations_start_year,
                end_year=operations_end_year,
                recurrence="annual",
                notes=f"Fee at {fr_config.fee_rate:.1%} of liability",
            )
        )

    return items


# ============================================================================
# Norwegian financial security
# ============================================================================


def norwegian_financial_security(
    outstanding_liability: float,
    annual_fraction: float = 0.005,
) -> float:
    """Calculate Norwegian financial security annual cost.

    Norwegian CCS projects use parent company guarantee or bank
    guarantee instead of the complex US FR instrument framework.
    Cost is a simple fraction of outstanding liability per year.

    Args:
        outstanding_liability: Current outstanding project liability.
        annual_fraction: Annual cost as fraction of liability (default 0.5%).

    Returns:
        Annual financial security cost.
    """
    return outstanding_liability * annual_fraction

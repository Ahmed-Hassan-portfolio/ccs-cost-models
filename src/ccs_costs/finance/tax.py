"""Tax regime calculations for CCS cost estimation.

Supports US (25.74% MACRS-based) and Norwegian (22% linear) tax regimes.
Norwegian CCS projects are excluded from the petroleum special tax.

Key types:
    TaxRegime: Pydantic model with rate, petroleum tax, loss carry-forward.
    TaxResult: Calculation result with taxable_income and tax.
    calculate_tax: Core tax calculation (revenue - opex - depreciation - interest).
    load_finance_config: Parse region finance.yaml into structured config.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel


class TaxRegime(BaseModel):
    """Tax configuration for a region.

    US: corporate_rate=25.74%, petroleum_tax_rate=0%, use_petroleum_tax=False
    Norway: corporate_rate=22%, petroleum_tax_rate=56%, use_petroleum_tax=False (CCS exempt)
    """

    corporate_rate: float
    petroleum_tax_rate: float = 0.0
    use_petroleum_tax: bool = False
    loss_carryforward: bool = True

    @classmethod
    def us_default(cls) -> TaxRegime:
        """US federal + state blended tax rate (25.74%).

        Source: NETL CO2_S_COM_Offshore reference_values.json.
        """
        return cls(
            corporate_rate=0.2574,
            petroleum_tax_rate=0.0,
            use_petroleum_tax=False,
            loss_carryforward=True,
        )

    @classmethod
    def norwegian_default(cls) -> TaxRegime:
        """Norwegian corporate tax (22%), petroleum tax excluded for CCS.

        Petroleum special tax rate of 56% exists but is NOT applied
        to CCS storage projects (only upstream petroleum production).
        """
        return cls(
            corporate_rate=0.22,
            petroleum_tax_rate=0.56,
            use_petroleum_tax=False,
            loss_carryforward=True,
        )


class TaxResult(BaseModel):
    """Result of a single-year tax calculation.

    Attributes:
        taxable_income: Revenue minus opex, depreciation, and interest.
            Can be negative (loss year).
        tax: Tax payable. Always >= 0 (no refund on negative income).
    """

    taxable_income: float
    tax: float


def calculate_tax(
    revenue: float,
    opex: float,
    depreciation: float,
    interest: float,
    regime: TaxRegime,
) -> TaxResult:
    """Calculate tax for a single year.

    Taxable income = revenue - opex - depreciation - interest.
    Tax = corporate_rate * max(0, taxable_income).

    CRITICAL: Always clamps to zero for negative taxable income --
    no tax refund. Loss carry-forward is tracked externally by the
    cashflow model.

    If use_petroleum_tax is True, petroleum tax is added on top of
    corporate tax (Norway upstream only, NOT CCS).

    Args:
        revenue: Total revenue for the year.
        opex: Operating expenditure for the year.
        depreciation: Total depreciation deductions for the year.
        interest: Interest payments on debt for the year.
        regime: TaxRegime configuration.

    Returns:
        TaxResult with taxable_income and tax.
    """
    taxable_income = revenue - opex - depreciation - interest

    effective_rate = regime.corporate_rate
    if regime.use_petroleum_tax:
        effective_rate += regime.petroleum_tax_rate

    tax = effective_rate * max(0.0, taxable_income)

    return TaxResult(taxable_income=taxable_income, tax=tax)


def load_finance_config(yaml_path: str | pathlib.Path) -> dict[str, Any]:
    """Load a region finance.yaml configuration file.

    Parses the YAML and constructs typed objects where applicable:
    - tax_regime: TaxRegime model
    - capital_structure: dict with equity/debt parameters
    - escalation: dict with escalation parameters
    - depreciation_map: dict mapping category -> {method, recovery_period}
    - fr_instruments: dict (US) or financial_security: dict (Norway)
    - revenue_streams: dict (Norway only)

    Args:
        yaml_path: Path to the finance.yaml file.

    Returns:
        Dict with structured financial configuration.

    Raises:
        FileNotFoundError: If the YAML file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    path = pathlib.Path(yaml_path)
    with path.open("r") as f:
        raw = yaml.safe_load(f)

    # Build TaxRegime from tax section
    tax_data = raw.get("tax", {})
    tax_regime = TaxRegime(
        corporate_rate=tax_data.get("corporate_rate", 0.0),
        petroleum_tax_rate=tax_data.get("petroleum_tax_rate", 0.0),
        use_petroleum_tax=tax_data.get("use_petroleum_tax", False),
        loss_carryforward=tax_data.get("loss_carryforward", True),
    )

    config: dict[str, Any] = {
        "tax_regime": tax_regime,
        "capital_structure": raw.get("capital_structure", {}),
        "escalation": raw.get("escalation", {}),
        "depreciation_map": raw.get("depreciation_map", {}),
    }

    # Region-specific sections
    if "fr_instruments" in raw:
        config["fr_instruments"] = raw["fr_instruments"]
    if "revenue_streams" in raw:
        config["revenue_streams"] = raw["revenue_streams"]
    if "financial_security" in raw:
        config["financial_security"] = raw["financial_security"]

    return config

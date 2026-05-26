"""Cost escalation module -- two-stage Handy-Whitman escalation.

Implements NETL's two-stage escalation formula:
  C_nominal = C_base * (1+r1)^(start - base) * (1+r2)^(target - start)

Where:
  r1 = pre-project escalation rate (Handy-Whitman index, 2008-2024)
  r2 = during-project escalation rate (default 0% in NETL)

The exact 2008->2024 factor (2.8494392065079523) is loaded from the extracted
NETL data rather than recomputed, avoiding floating-point drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class EscalationConfig(BaseModel):
    """Escalation parameters for cost adjustment.

    Attributes:
        base_cost_year: Year costs are expressed in (e.g. 2008).
        project_start_year: Calendar year project starts (e.g. 2024).
        pre_project_rate: Annual escalation rate from base to start year.
        during_project_rate: Annual escalation rate during project.
        base_to_start_factor: Pre-computed factor for base->start escalation.
            Loaded from NETL JSON to avoid floating-point drift.
    """

    base_cost_year: int
    project_start_year: int
    pre_project_rate: float
    during_project_rate: float
    base_to_start_factor: float

    def factor_for_year(self, calendar_year: int) -> float:
        """Return the escalation factor for a given calendar year.

        Uses the pre-computed base_to_start_factor for the base-to-start
        portion and compounds during_project_rate for years beyond start.

        Args:
            calendar_year: The target calendar year.

        Returns:
            The multiplicative escalation factor from base_cost_year to
            calendar_year.
        """
        years_after_start = max(0, calendar_year - self.project_start_year)
        return self.base_to_start_factor * (
            (1.0 + self.during_project_rate) ** years_after_start
        )


def load_escalation_indices(path: str | Path) -> EscalationConfig:
    """Load escalation configuration from NETL-extracted JSON.

    Args:
        path: Path to escalation_indices.json.

    Returns:
        EscalationConfig with parameters from the JSON file.
    """
    path = Path(path)
    with open(path) as f:
        data: dict[str, Any] = json.load(f)

    params = data["parameters"]
    return EscalationConfig(
        base_cost_year=params["base_year_for_costs"],
        project_start_year=params["starting_calendar_year"],
        pre_project_rate=params["escalation_rate_base_to_start"],
        during_project_rate=params["escalation_rate_from_start"],
        base_to_start_factor=params["escalation_factor_2008_to_2024"],
    )


def escalate_cost(
    cost_base: float,
    base_year: int,
    target_year: int,
    start_year: int,
    r1: float,
    r2: float,
) -> float:
    """Apply two-stage escalation to a base-year cost.

    Formula:
        C_nominal = C_base * (1+r1)^(start - base) * (1+r2)^(target - start)

    Stage 1: Historical escalation from base_year to start_year at rate r1.
    Stage 2: Project-period escalation from start_year to target_year at rate r2.

    Args:
        cost_base: Cost in base-year dollars.
        base_year: Year the cost is expressed in (e.g. 2008).
        target_year: Year to escalate to.
        start_year: Project start year (boundary between r1 and r2).
        r1: Pre-project annual escalation rate.
        r2: During-project annual escalation rate.

    Returns:
        Escalated cost in target_year dollars.
    """
    stage1 = (1.0 + r1) ** (start_year - base_year)
    stage2 = (1.0 + r2) ** max(0, target_year - start_year)
    return cost_base * stage1 * stage2

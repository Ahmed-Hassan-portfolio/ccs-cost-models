"""Learning curve cost projections using Wright's law.

Projects CCS transport and storage costs into the future as cumulative
deployment increases, using experience rates from published CCS literature.

Wright's law: C(n) = C(1) * (n/n_0)^(-b), where b = -log2(1 - LR)

Primary rates are from Gassnova 2020 (via Mitterrutzner & Roussanaly 2026):
    - Transport: 2% per doubling of cumulative capacity
    - Storage:   3% per doubling of cumulative capacity
    - Aggregate CCS: 10% per doubling (Gassnova 2020)

Sievert 2024 provides technology-general experience rates by component
complexity (22%/13%/5%/2.5%) — these are NOT CCS-calibrated and should
only be used for component-level decomposition, not as primary rates.

Sources:
    Gassnova (2020): Mulighetsstudier av fullskala CO2-handtering i Norge
    Mitterrutzner & Roussanaly (2026): Scaling CCS to climate relevance
    Sievert (2024): Experience curves for CCS technologies
    IEA NZE (2023): Net Zero by 2050 — CCS deployment trajectory
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Gassnova 2020 CCS learning rates (primary)
# ---------------------------------------------------------------------------

GASSNOVA_TRANSPORT_LR: float = 0.02   # 2% cost reduction per capacity doubling
GASSNOVA_STORAGE_LR: float = 0.03     # 3% cost reduction per capacity doubling
GASSNOVA_AGGREGATE_LR: float = 0.10   # 10% aggregate CCS learning rate

# ---------------------------------------------------------------------------
# Sievert 2024 component-level experience rates (technology-general)
# ---------------------------------------------------------------------------

SIEVERT_SIMPLE_ER: float = 0.22       # Simple, standardized components
SIEVERT_INTERMEDIATE_ER: float = 0.13  # Intermediate complexity
SIEVERT_COMPLEX_ER: float = 0.05      # Complex, site-specific systems
SIEVERT_OFF_SHELF_ER: float = 0.025   # Off-the-shelf equipment

# ---------------------------------------------------------------------------
# Deployment trajectory (IEA NZE 2023)
# ---------------------------------------------------------------------------

# Global CCS capacity (Mtpa) — approximate IEA NZE deployment scenario
_IEA_NZE_CAPACITY: dict[int, float] = {
    2024: 50.0,     # Current global CCS capacity
    2025: 60.0,
    2030: 200.0,    # ~4x increase by 2030
    2035: 600.0,    # ~12x increase by 2035
    2040: 1200.0,   # ~24x increase by 2040
    2050: 5600.0,   # IEA NZE target
}


class LearningCurveParams(BaseModel):
    """Learning curve parameters for CCS cost projection.

    Attributes:
        transport_learning_rate: Fractional cost reduction per doubling
            of cumulative capacity for transport. Default 0.02 (Gassnova 2020).
        storage_learning_rate: Same for storage. Default 0.03 (Gassnova 2020).
        base_year: Year of the base cost estimate.
        base_cumulative_capacity_mtpa: Global CCS capacity at base_year.
    """

    transport_learning_rate: float = Field(
        default=GASSNOVA_TRANSPORT_LR,
        ge=0.0,
        le=0.5,
        description="Transport learning rate per capacity doubling (Gassnova 2020: 0.02)",
    )
    storage_learning_rate: float = Field(
        default=GASSNOVA_STORAGE_LR,
        ge=0.0,
        le=0.5,
        description="Storage learning rate per capacity doubling (Gassnova 2020: 0.03)",
    )
    base_year: int = Field(default=2025, description="Base cost year")
    base_cumulative_capacity_mtpa: float = Field(
        default=60.0,
        gt=0.0,
        description="Global CCS capacity at base year (Mtpa)",
    )


class CostProjection(BaseModel):
    """Single cost projection at a future cumulative capacity."""

    year: int
    cumulative_capacity_mtpa: float
    cost_reduction_fraction: float  # e.g. 0.05 = 5% cheaper than base
    projected_cost: float           # absolute cost after reduction


class LearningCurveResult(BaseModel):
    """Complete learning curve projection result."""

    component: str                       # "transport" or "storage"
    learning_rate: float                 # applied LR
    base_cost: float                     # cost at base year
    base_year: int
    projections: list[CostProjection]


def learning_exponent(learning_rate: float) -> float:
    """Convert learning rate to Wright's law exponent.

    b = -log2(1 - LR)

    A learning rate of 10% means costs fall by 10% each time cumulative
    capacity doubles, giving b = -log2(0.9) ≈ 0.152.

    Args:
        learning_rate: Fractional reduction per doubling (0-1).

    Returns:
        Wright's law exponent b (positive).
    """
    if learning_rate <= 0.0:
        return 0.0
    if learning_rate >= 1.0:
        raise ValueError(f"Learning rate must be < 1.0, got {learning_rate}")
    return -math.log2(1.0 - learning_rate)


def project_cost_with_learning(
    base_cost: float,
    learning_rate: float,
    base_cumulative: float,
    target_cumulative: float,
) -> float:
    """Project cost using Wright's law.

    C(n) = C(n_0) * (n / n_0)^(-b), where b = -log2(1 - LR).

    Gassnova 2020 rates are primary (conservative for CCS).
    Sievert 2024 rates (22%/13%/5%) are technology-general, not CCS-calibrated.

    Args:
        base_cost: Cost at base cumulative capacity.
        learning_rate: Fractional cost reduction per capacity doubling.
        base_cumulative: Cumulative capacity at base (Mtpa).
        target_cumulative: Cumulative capacity at target (Mtpa).

    Returns:
        Projected cost at target cumulative capacity.
    """
    if target_cumulative <= base_cumulative:
        return base_cost
    if learning_rate <= 0.0:
        return base_cost

    b = learning_exponent(learning_rate)
    ratio = (target_cumulative / base_cumulative) ** (-b)
    return base_cost * ratio


def _interpolate_capacity(year: int) -> float:
    """Interpolate global CCS capacity for a given year from IEA NZE trajectory."""
    years = sorted(_IEA_NZE_CAPACITY.keys())
    if year <= years[0]:
        return _IEA_NZE_CAPACITY[years[0]]
    if year >= years[-1]:
        return _IEA_NZE_CAPACITY[years[-1]]

    for i in range(len(years) - 1):
        y0, y1 = years[i], years[i + 1]
        if y0 <= year <= y1:
            frac = (year - y0) / (y1 - y0)
            c0 = _IEA_NZE_CAPACITY[y0]
            c1 = _IEA_NZE_CAPACITY[y1]
            # Log-linear interpolation (exponential growth assumption)
            return c0 * (c1 / c0) ** frac
    return _IEA_NZE_CAPACITY[years[-1]]  # pragma: no cover


def cost_projections(
    base_cost_eur_per_t: float,
    component: str = "storage",
    years: list[int] | None = None,
    params: LearningCurveParams | None = None,
) -> LearningCurveResult:
    """Project costs at future years using Gassnova learning rates.

    Assumes global CCS capacity follows the IEA NZE trajectory
    (approximate doublings every ~5 years through 2050).

    Args:
        base_cost_eur_per_t: Base cost in EUR/tCO2 at params.base_year.
        component: "transport" or "storage" (selects learning rate).
        years: Target years for projection. Default [2025, 2030, 2035].
        params: Learning curve parameters. Uses defaults if None.

    Returns:
        LearningCurveResult with projections for each year.
    """
    if params is None:
        params = LearningCurveParams()
    if years is None:
        years = [2025, 2030, 2035]

    lr = (
        params.transport_learning_rate
        if component == "transport"
        else params.storage_learning_rate
    )

    base_capacity = params.base_cumulative_capacity_mtpa
    projections: list[CostProjection] = []

    for year in sorted(years):
        target_capacity = _interpolate_capacity(year)
        projected = project_cost_with_learning(
            base_cost_eur_per_t, lr, base_capacity, target_capacity
        )
        reduction = 1.0 - (projected / base_cost_eur_per_t) if base_cost_eur_per_t > 0 else 0.0
        projections.append(
            CostProjection(
                year=year,
                cumulative_capacity_mtpa=round(target_capacity, 1),
                cost_reduction_fraction=round(reduction, 6),
                projected_cost=round(projected, 4),
            )
        )

    return LearningCurveResult(
        component=component,
        learning_rate=lr,
        base_cost=base_cost_eur_per_t,
        base_year=params.base_year,
        projections=projections,
    )

"""Drilling time prediction intervals from Sodir NCS well data.

Loads NCS injection well durations from Sodir FactPages and provides:
    - Log-linear regression: log(days) = a + b * TVD
    - 95% prediction interval for a SINGLE well at given TVD
    - 95% confidence interval for PORTFOLIO AVERAGE at given TVD and n_wells
    - Percentile bands by TVD range (non-parametric)
    - CO2 well calibration check

The regression R² is low (~0.06 for injection wells in log-space) because
individual well duration is dominated by operational factors, not depth alone.
However, the prediction interval correctly captures this uncertainty, and
the portfolio-average interval narrows with 1/sqrt(n).

Data source:
    Sodir FactPages 2025 — 920 NCS injection wells with TVD and drilling days.

References:
    Sodir FactPages (factpages.sodir.no)
    Duration statistics: data/sodir/well-durations/duration_statistics.json
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from pydantic import BaseModel
from scipy import stats


# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "sodir" / "well-durations"
_INJECTION_CSV = _DATA_DIR / "injection_wells_duration.csv"
_STATS_JSON = _DATA_DIR / "duration_statistics.json"


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class PredictionInterval(BaseModel):
    """Prediction/confidence interval for drilling duration."""

    point_estimate_days: float
    lower_days: float
    upper_days: float
    confidence_level: float
    interval_type: str  # "prediction" (single well) or "confidence" (portfolio mean)
    n_wells: int
    tvd_m: float


class PercentileBand(BaseModel):
    """Percentile-based drilling duration band for a TVD range."""

    tvd_range: str
    n_wells_in_band: int
    p10_days: float
    p25_days: float
    p50_days: float
    p75_days: float
    p90_days: float
    mean_days: float
    std_days: float


class DrillingUncertainty(BaseModel):
    """Complete uncertainty assessment for a drilling estimate."""

    single_well_pi: PredictionInterval
    portfolio_ci: PredictionInterval
    percentile_band: PercentileBand
    regression_r2: float
    n_data_points: int
    co2_well_check: str  # narrative: are CO2 actuals within the interval?


# ---------------------------------------------------------------------------
# Regression fitting
# ---------------------------------------------------------------------------


class NCSWellDurationRegression:
    """Log-linear regression on NCS injection well durations.

    Fits log(days) = intercept + slope * tvd on Sodir injection wells,
    then provides prediction intervals via the t-distribution.

    The log-transform handles the right-skew of duration data and gives
    multiplicative prediction intervals (e.g., point_estimate * [0.3, 3.5]).
    """

    def __init__(self, data_path: Path | None = None):
        """Load data and fit regression.

        Args:
            data_path: Path to injection_wells_duration.csv.
                       Defaults to the project data directory.
        """
        path = data_path if data_path is not None else _INJECTION_CSV
        self._tvd: np.ndarray
        self._days: np.ndarray
        self._log_days: np.ndarray
        self._load_data(path)
        self._fit()

        # Pre-load percentile bands from duration_statistics.json
        self._percentile_bands: list[dict] = []
        self._load_percentile_bands()

    def _load_data(self, path: Path) -> None:
        """Load and filter injection well data."""
        tvd_list: list[float] = []
        days_list: list[float] = []

        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    t = float(row["tvd"])
                    d = float(row["duration_days"])
                except (ValueError, TypeError):
                    continue
                if t > 0 and d > 0:
                    tvd_list.append(t)
                    days_list.append(d)

        self._tvd = np.array(tvd_list)
        self._days = np.array(days_list)
        self._log_days = np.log(self._days)

    def _fit(self) -> None:
        """Fit log-linear regression: log(days) = intercept + slope * tvd."""
        n = len(self._tvd)
        x = self._tvd
        y = self._log_days

        x_mean = np.mean(x)
        y_mean = np.mean(y)

        # OLS
        ss_xx = np.sum((x - x_mean) ** 2)
        ss_xy = np.sum((x - x_mean) * (y - y_mean))

        self._slope = ss_xy / ss_xx
        self._intercept = y_mean - self._slope * x_mean

        # Residual standard error
        y_hat = self._intercept + self._slope * x
        residuals = y - y_hat
        self._s_e = np.sqrt(np.sum(residuals ** 2) / (n - 2))

        # R-squared
        ss_res = np.sum(residuals ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        self._r2 = 1.0 - ss_res / ss_tot

        # Store for interval calculations
        self._n = n
        self._x_mean = x_mean
        self._ss_xx = ss_xx

    def _load_percentile_bands(self) -> None:
        """Load pre-computed percentile bands from statistics JSON."""
        if _STATS_JSON.exists():
            data = json.loads(_STATS_JSON.read_text(encoding="utf-8"))
            self._percentile_bands = data.get("inj_by_tvd", [])

    @property
    def n_data_points(self) -> int:
        return self._n

    @property
    def r_squared(self) -> float:
        return self._r2

    @property
    def slope(self) -> float:
        return self._slope

    @property
    def intercept(self) -> float:
        return self._intercept

    @property
    def residual_se(self) -> float:
        return self._s_e

    def predict_log(self, tvd_m: float) -> float:
        """Predict log(days) for a given TVD."""
        return self._intercept + self._slope * tvd_m

    def predict_days(self, tvd_m: float) -> float:
        """Predict median drilling days for a given TVD.

        Uses exp(predicted_log) which gives the geometric mean / median
        of the log-normal distribution (NOT the arithmetic mean).
        """
        return math.exp(self.predict_log(tvd_m))

    def prediction_interval(
        self,
        tvd_m: float,
        confidence: float = 0.95,
    ) -> PredictionInterval:
        """95% prediction interval for a SINGLE new well.

        This is the interval that captures the next individual observation
        with the given probability. It's wide because individual well
        duration is highly variable.

        Args:
            tvd_m: Target TVD in metres.
            confidence: Confidence level (default 0.95).

        Returns:
            PredictionInterval with point estimate and bounds in days.
        """
        alpha = 1.0 - confidence
        t_crit = stats.t.ppf(1.0 - alpha / 2.0, df=self._n - 2)

        y_hat = self.predict_log(tvd_m)

        # Standard error for prediction of a NEW observation
        # SE_pred = s_e * sqrt(1 + 1/n + (x0 - x_mean)^2 / SS_xx)
        se_pred = self._s_e * math.sqrt(
            1.0 + 1.0 / self._n + (tvd_m - self._x_mean) ** 2 / self._ss_xx
        )

        margin = t_crit * se_pred

        return PredictionInterval(
            point_estimate_days=math.exp(y_hat),
            lower_days=math.exp(y_hat - margin),
            upper_days=math.exp(y_hat + margin),
            confidence_level=confidence,
            interval_type="prediction",
            n_wells=1,
            tvd_m=tvd_m,
        )

    def portfolio_confidence_interval(
        self,
        tvd_m: float,
        n_wells: int,
        confidence: float = 0.95,
    ) -> PredictionInterval:
        """95% confidence interval for PORTFOLIO AVERAGE of n_wells.

        The portfolio mean is much more predictable than any single well.
        The interval narrows as 1/sqrt(n) for the mean of log-durations.

        This gives the interval for the geometric mean of n_wells' durations
        (since we work in log-space). For project cost estimation, the
        geometric mean is a reasonable central estimate.

        Args:
            tvd_m: Target TVD in metres.
            n_wells: Number of wells in the portfolio.
            confidence: Confidence level (default 0.95).

        Returns:
            PredictionInterval for the portfolio average duration.
        """
        alpha = 1.0 - confidence
        t_crit = stats.t.ppf(1.0 - alpha / 2.0, df=self._n - 2)

        y_hat = self.predict_log(tvd_m)

        # SE for mean of n new observations
        # SE_mean = s_e * sqrt(1/n_wells + 1/n + (x0 - x_mean)^2 / SS_xx)
        se_mean = self._s_e * math.sqrt(
            1.0 / n_wells + 1.0 / self._n + (tvd_m - self._x_mean) ** 2 / self._ss_xx
        )

        margin = t_crit * se_mean

        return PredictionInterval(
            point_estimate_days=math.exp(y_hat),
            lower_days=math.exp(y_hat - margin),
            upper_days=math.exp(y_hat + margin),
            confidence_level=confidence,
            interval_type="confidence",
            n_wells=n_wells,
            tvd_m=tvd_m,
        )

    def percentile_band(self, tvd_m: float) -> PercentileBand:
        """Non-parametric percentile band from Sodir statistics.

        Uses pre-computed TVD-binned statistics from the injection well
        population. Falls back to computing from raw data if the JSON
        statistics are not available.

        Args:
            tvd_m: Target TVD in metres.

        Returns:
            PercentileBand for the matching TVD range.
        """
        # Try pre-computed bands first
        if self._percentile_bands:
            for band in self._percentile_bands:
                rng = band["depth_range_tvd"]
                if rng.endswith("+"):
                    lo = float(rng.replace("+", ""))
                    hi = float("inf")
                else:
                    parts = rng.split("-")
                    lo, hi = float(parts[0]), float(parts[1])
                if lo <= tvd_m < hi:
                    return PercentileBand(
                        tvd_range=rng,
                        n_wells_in_band=band["count"],
                        p10_days=band["P10"],
                        p25_days=band["P25"],
                        p50_days=band["P50"],
                        p75_days=band["P75"],
                        p90_days=band["P90"],
                        mean_days=band["mean"],
                        std_days=band["std"],
                    )

        # Fallback: compute from raw data with +/- 500m window
        mask = (self._tvd >= tvd_m - 500) & (self._tvd <= tvd_m + 500)
        if mask.sum() < 10:
            mask = (self._tvd >= tvd_m - 1000) & (self._tvd <= tvd_m + 1000)

        subset = self._days[mask]
        if len(subset) == 0:
            subset = self._days  # ultimate fallback

        return PercentileBand(
            tvd_range=f"{tvd_m - 500:.0f}-{tvd_m + 500:.0f}",
            n_wells_in_band=len(subset),
            p10_days=float(np.percentile(subset, 10)),
            p25_days=float(np.percentile(subset, 25)),
            p50_days=float(np.percentile(subset, 50)),
            p75_days=float(np.percentile(subset, 75)),
            p90_days=float(np.percentile(subset, 90)),
            mean_days=float(np.mean(subset)),
            std_days=float(np.std(subset)),
        )

    def assess_uncertainty(
        self,
        tvd_m: float,
        n_wells: int = 3,
        confidence: float = 0.95,
    ) -> DrillingUncertainty:
        """Full uncertainty assessment for drilling duration estimate.

        Combines parametric (regression-based) and non-parametric (percentile)
        approaches. Also validates against known CO2 well durations.

        Args:
            tvd_m: Target TVD in metres.
            n_wells: Number of wells in portfolio.
            confidence: Confidence level.

        Returns:
            DrillingUncertainty with all interval types and CO2 validation.
        """
        single_pi = self.prediction_interval(tvd_m, confidence)
        portfolio_ci = self.portfolio_confidence_interval(tvd_m, n_wells, confidence)
        pband = self.percentile_band(tvd_m)

        # CO2 well validation
        co2_actuals = [
            ("Sleipner", 1012, 22),
            ("Snohvit F-1H", 2600, 40),
            ("Snohvit F-2H", 2600, 45),
            ("NL A-2", 2818, 23),
            ("NL A-3", 2935, 33),
        ]

        within = 0
        total = 0
        for name, co2_tvd, co2_days in co2_actuals:
            pi = self.prediction_interval(co2_tvd, confidence)
            if pi.lower_days <= co2_days <= pi.upper_days:
                within += 1
            total += 1

        co2_check = (
            f"{within}/{total} CO2 well actuals fall within "
            f"{confidence:.0%} prediction interval"
        )

        return DrillingUncertainty(
            single_well_pi=single_pi,
            portfolio_ci=portfolio_ci,
            percentile_band=pband,
            regression_r2=self._r2,
            n_data_points=self._n,
            co2_well_check=co2_check,
        )

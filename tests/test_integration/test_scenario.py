"""Tests for scenario orchestrator (scenario.py).

End-to-end integration tests that verify the full calculation chain
from formation properties to FYBE result. The NETL cross-verification
test (FYBE ≈ $25.34/t) is the ultimate correctness gate.

NETL reference values (Formation 1241_1, Chandeleur Area, GOA offshore):
    FYBE (2008$): ~$25.34/t  (NETL plan: 2 strat test wells)
    FYBE (2024$): ~$72.20/t
    Injection wells: 5
    Pipeline diameter: 12 inches
    Total CAPEX (NETL): ~$518M (2008$); model target ~$521M
    Total OPEX (NETL):  ~$1,207M (2008$); model target ~$1,214M

Tolerance notes:
    Per-well costs are derived by dividing NETL row80/86/95 totals by their
    well counts (2 strat / 5 inject / 2 in-res). The optional per-formation
    QUE$TOR-regression file is not bundled with this portfolio mirror, so
    every formation falls back to Formation 1 (1241_1) defaults — which
    happens to be the calibration formation, so the FYBE reference still
    holds.

    FYBE tolerance is $0.50/t (~2%) reflecting:
    - Rounding across 20+ cost items
    - Minor differences in area-scaled monitoring and corrective wells

    CAPEX tolerance is 1%. OPEX is within 0.1%.
"""

from __future__ import annotations

import time

import pytest

from ccs_costs.scenario import (
    ScenarioConfig,
    ScenarioResults,
    evaluate_batch,
    evaluate_scenario,
)


class TestEvaluateScenarioNETLDefault:
    """Cross-verification against NETL offshore default (Formation 1241_1)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Create the NETL default scenario config."""
        self.config = ScenarioConfig(
            formation_id="1241_1",
            region="us-goa",
        )

    def test_returns_scenario_results(self):
        """evaluate_scenario returns a ScenarioResults."""
        result = evaluate_scenario(self.config)
        assert isinstance(result, ScenarioResults)

    def test_fybe_base_year(self):
        """FYBE (2008$) within $0.50 of $25.34/t (NETL Formation 1241_1)."""
        result = evaluate_scenario(self.config)
        assert result.fybe == pytest.approx(25.34, abs=0.50)

    def test_fybe_current_year(self):
        """FYBE (2024$) within $1.50 of $72.20/t (NETL Formation 1241_1)."""
        result = evaluate_scenario(self.config)
        assert result.fybe_current_year == pytest.approx(72.20, abs=1.50)

    def test_n_injection_wells(self):
        """5 injection wells for NETL default."""
        result = evaluate_scenario(self.config)
        assert result.n_injection_wells == 5

    def test_pipeline_diameter(self):
        """12-inch pipeline for NETL default."""
        result = evaluate_scenario(self.config)
        assert result.pipeline_diameter_inches == 12.0

    def test_total_capex(self):
        """Total CAPEX approximately $521M (2008$), within 1%.

        Includes area-dependent monitoring capital (seismic area scaling)
        and per-formation corrective action wells (109 * $43,092 for 1241_1).
        """
        result = evaluate_scenario(self.config)
        assert result.total_capex == pytest.approx(520_663_417, rel=0.01)

    def test_total_opex(self):
        """Total OPEX approximately $1,214M (2008$), within 1%.

        QUE$TOR platform O&M (depth-dependent) + area-scaled monitoring.
        Platform PISC = decommissioning one-time (not annual O&M).
        """
        result = evaluate_scenario(self.config)
        assert result.total_opex == pytest.approx(1_214_197_945, rel=0.01)


class TestScenarioResults:
    """Test ScenarioResults model methods."""

    def test_to_compact_dict(self):
        """to_compact_dict() returns a dict with ~15 keys."""
        config = ScenarioConfig(formation_id="1241_1", region="us-goa")
        result = evaluate_scenario(config)
        d = result.to_compact_dict()
        assert isinstance(d, dict)
        assert len(d) >= 12


class TestEvaluateBatch:
    """Test batch evaluation of multiple formations."""

    def test_batch_two_formations(self):
        """evaluate_batch processes two formations and returns list of 2."""
        configs = [
            ScenarioConfig(formation_id="1241_1", region="us-goa"),
            ScenarioConfig(formation_id="1241_2", region="us-goa"),
        ]
        results = evaluate_batch(configs)
        assert len(results) == 2
        assert all(isinstance(r, ScenarioResults) for r in results)


class TestScenarioErrors:
    """Test error handling in scenario evaluation."""

    def test_invalid_formation_raises(self):
        """evaluate_scenario with invalid formation_id raises ValueError."""
        config = ScenarioConfig(
            formation_id="INVALID_FORMATION",
            region="us-goa",
        )
        with pytest.raises(ValueError):
            evaluate_scenario(config)


class TestScenarioPerformance:
    """Test performance requirements."""

    def test_single_scenario_under_1_second(self):
        """Single scenario evaluation completes in under 1 second (SRV-12)."""
        config = ScenarioConfig(formation_id="1241_1", region="us-goa")
        start = time.perf_counter()
        evaluate_scenario(config)
        duration = time.perf_counter() - start
        assert duration < 1.0, f"Scenario took {duration:.2f}s, expected <1s"

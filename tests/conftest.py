"""Shared pytest fixtures for CCS cost model tests.

Provides:
    - NETL reference values from extracted data
    - NETL formation database
    - NIST CO2 density reference data for validation
"""

import json
from pathlib import Path

import pytest

# Path to extracted NETL data
_DATA_DIR = Path(__file__).parent.parent / "data" / "netl-extracted"


@pytest.fixture
def netl_reference() -> dict:
    """Load NETL default scenario reference values.

    Returns dict with keys: default_scenario (geology, key_inputs, cost_breakdown,
    financial_params, pipeline, injection_schedule).
    """
    path = _DATA_DIR / "reference_values.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def netl_formations() -> dict:
    """Load NETL GOA formation database (117 formations, 39 attributes each)."""
    path = _DATA_DIR / "formations.json"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def nist_co2_density() -> list[tuple[float, float, float]]:
    """NIST Chemistry WebBook reference data for pure CO2 density.

    Returns list of (pressure_mpa, temperature_c, density_kgm3) tuples.

    Source: NIST Chemistry WebBook, Thermophysical Properties of Fluid Systems
    https://webbook.nist.gov/chemistry/fluid/

    These values span the range 5-40 MPa, 4-150 C covering:
    - Supercritical conditions (typical reservoir)
    - Near-critical region (reduced accuracy expected)
    - NCS cold conditions (4 C pipeline/seabed)
    - High pressure (deep formations)

    Values verified against NIST webbook for pure CO2 (Span-Wagner EOS).
    """
    return [
        # (P_MPa, T_C, rho_kg/m3)
        # --- Standard supercritical conditions ---
        (10.0, 35.0, 713.82),
        (10.0, 50.0, 384.45),
        (10.0, 75.0, 269.58),
        (10.0, 100.0, 225.39),
        (10.0, 150.0, 170.86),
        # --- 15 MPa ---
        (15.0, 35.0, 780.27),
        (15.0, 50.0, 700.94),
        (15.0, 75.0, 481.36),
        (15.0, 100.0, 377.27),
        (15.0, 150.0, 277.49),
        # --- 20 MPa ---
        (20.0, 35.0, 819.68),
        (20.0, 50.0, 764.46),
        (20.0, 80.0, 615.83),
        (20.0, 100.0, 530.46),
        (20.0, 150.0, 378.19),
        # --- 30 MPa ---
        (30.0, 35.0, 873.39),
        (30.0, 50.0, 829.97),
        (30.0, 100.0, 663.53),
        (30.0, 150.0, 515.16),
        # --- 40 MPa ---
        (40.0, 50.0, 876.12),
        (40.0, 100.0, 747.78),
        (40.0, 150.0, 614.81),
        # --- Near critical point (lower accuracy expected) ---
        (5.0, 30.0, 161.17),
        (7.5, 32.0, 364.48),
        # --- NCS cold condition ---
        (20.0, 4.0, 1018.40),
    ]


@pytest.fixture
def nist_co2_density_near_critical() -> list[tuple[float, float, float]]:
    """NIST CO2 density reference points near the critical region.

    Near Tc=31.1C, Pc=7.38 MPa -- all cubic EOS have reduced accuracy here.
    Tolerance should be relaxed to 2-5% for these points.
    """
    return [
        (5.0, 30.0, 161.17),
        (7.5, 32.0, 364.48),
        (8.0, 32.0, 505.66),
        (7.5, 35.0, 218.89),
    ]

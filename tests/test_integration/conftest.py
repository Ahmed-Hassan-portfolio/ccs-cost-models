"""Shared fixtures for integration tests.

NETL reference values for cross-verification:
    FYBE (2008$): $25.34/t (exact: $25.3376)
    FYBE (2024$): $72.20/t (exact: $72.1980)
    Escalation factor: 2.8494392065079523
    Total CAPEX: $518,211,344 (real 2008$)
    Total O&M: $1,207,208,500 (real 2008$)
    CO2 injection rate: 4,000,000 t/yr
    Capacity factor: 0.85
    Operations years: 30
    PISC years: 50
    Number of injection wells: 5
    Pipeline diameter: 12 inches
    Default formation: 1241_1 (Chandeleur Area)
"""

import pytest


# NETL cross-verification reference values
NETL_FYBE_2008 = 25.34       # $/t (2008$)
NETL_FYBE_2024 = 72.20       # $/t (2024$)
NETL_ESCALATION_FACTOR = 2.8494392065079523
NETL_TOTAL_CAPEX = 518_211_344.0  # 2008$
NETL_TOTAL_OPEX = 1_207_208_500.0  # 2008$
NETL_N_INJECTION_WELLS = 5
NETL_PIPELINE_DIAMETER_INCHES = 12
NETL_INJECTION_RATE_TPA = 4_000_000
NETL_CAPACITY_FACTOR = 0.85
NETL_OPS_YEARS = 30
NETL_DEFAULT_FORMATION = "1241_1"
NETL_DEFAULT_REGION = "us-goa"


@pytest.fixture
def netl_defaults():
    """NETL default scenario reference values as dict."""
    return {
        "fybe_2008": NETL_FYBE_2008,
        "fybe_2024": NETL_FYBE_2024,
        "escalation_factor": NETL_ESCALATION_FACTOR,
        "total_capex": NETL_TOTAL_CAPEX,
        "total_opex": NETL_TOTAL_OPEX,
        "n_injection_wells": NETL_N_INJECTION_WELLS,
        "pipeline_diameter_inches": NETL_PIPELINE_DIAMETER_INCHES,
        "injection_rate_tpa": NETL_INJECTION_RATE_TPA,
        "capacity_factor": NETL_CAPACITY_FACTOR,
        "ops_years": NETL_OPS_YEARS,
        "formation_id": NETL_DEFAULT_FORMATION,
        "region": NETL_DEFAULT_REGION,
    }

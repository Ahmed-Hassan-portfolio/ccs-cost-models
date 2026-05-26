"""Page 1: Evaluate a single formation."""

import sys
from pathlib import Path

import streamlit as st

# Ensure app/components is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.formation_selector import formation_selector
from components.result_display import render_results

from ccs_costs.config import load_region
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

REGION_LABELS = {"us-goa": "US Gulf of America", "norway-ncs": "Norwegian Continental Shelf"}

st.header("Evaluate a Formation")

# Get region from session state
region_id = st.session_state.get("region_id", "us-goa")

# Sidebar: region info (consistent with Home)
region = st.session_state.get("region")
if region is None:
    @st.cache_resource
    def _load_region(rid):
        return load_region(rid)
    region = _load_region(region_id)

n_formations = len(region.formations)
st.sidebar.markdown(f"**Region:** {REGION_LABELS.get(region_id, region_id)}")
st.sidebar.markdown(f"**{n_formations}** formations loaded")
st.sidebar.markdown(f"Currency: **{region.currency}** | Base year: **{region.base_year}**")

# Clear stale results when region changes
if "last_region" in st.session_state and st.session_state["last_region"] != region_id:
    for key in ["last_result", "last_formation"]:
        st.session_state.pop(key, None)
st.session_state["last_region"] = region_id

# Formation selector
formation_id = formation_selector(region)

if formation_id is None:
    st.stop()

# Optional overrides
with st.expander("Advanced overrides", expanded=False):
    col_a, col_b = st.columns(2)
    with col_a:
        injection_rate = st.number_input(
            "Injection rate (Mt/yr)",
            min_value=0.5, max_value=20.0,
            value=4.0 if region_id == "us-goa" else 3.0,
            step=0.5,
            help="Annual CO2 injection rate in million tonnes per year.",
        )
    with col_b:
        ops_years = st.number_input(
            "Operations years (0 = default)",
            min_value=0, max_value=50, value=0, step=5,
            help="Override injection period length. 0 uses region default.",
        )

# Evaluate button
if st.button("Evaluate", type="primary", use_container_width=True):
    config = ScenarioConfig(
        formation_id=formation_id,
        region=region_id,
        injection_rate_tpa=injection_rate * 1_000_000,
        operations_years=ops_years if ops_years > 0 else None,
    )
    with st.spinner(f"Evaluating {formation_id}..."):
        try:
            result = evaluate_scenario(config)
            st.session_state["last_result"] = result
            st.session_state["last_formation"] = formation_id
        except Exception as e:
            st.error(f"Evaluation failed: {e}")

# Render results from session state (survives widget reruns)
if "last_result" in st.session_state:
    r = st.session_state["last_result"]

    # Anchor comparison
    anchor_label = None
    anchor_value = None
    if region_id == "us-goa":
        anchor_label = "NETL reference (1241_1)"
        anchor_value = 25.34
    elif region_id == "norway-ncs":
        anchor_label = "Northern Lights est."
        anchor_value = 35.0  # EUR/t approximate

    render_results(
        r,
        percentile=None,
        anchor_label=anchor_label,
        anchor_value=anchor_value,
    )

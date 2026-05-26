"""Page 3: Sensitivity analysis and Monte Carlo."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.formation_selector import formation_selector
from components.charts import render_tornado, render_monte_carlo

from ccs_costs.config import load_region

REGION_LABELS = {"us-goa": "US Gulf of America", "norway-ncs": "Norwegian Continental Shelf"}

# Default parameters for tornado sensitivity analysis
DEFAULT_TORNADO_PARAMS = [
    {"parameter": "porosity", "low": 0.05, "high": 0.35, "base": 0.15},
    {"parameter": "permeability_md", "low": 5.0, "high": 500.0, "base": 50.0},
    {"parameter": "depth_m", "low": 800.0, "high": 3500.0, "base": 2000.0},
    {"parameter": "thickness_m", "low": 10.0, "high": 200.0, "base": 50.0},
    {"parameter": "injection_rate_mtpa", "low": 1.0, "high": 8.0, "base": 4.0},
]

st.header("Sensitivity & Uncertainty Analysis")

region_id = st.session_state.get("region_id", "us-goa")

# Sidebar: region info (consistent with Home)
region = st.session_state.get("region")
if region is None:
    @st.cache_resource
    def _load_region(rid):
        return load_region(rid)
    region = _load_region(region_id)

currency_sym = {"USD": "$", "NOK": "NOK ", "EUR": "\u20ac"}.get(region.currency, "")

st.sidebar.markdown(f"**Region:** {REGION_LABELS.get(region_id, region_id)}")
st.sidebar.markdown(f"**{len(region.formations)}** formations loaded")
st.sidebar.markdown(f"Currency: **{region.currency}** | Base year: **{region.base_year}**")

# Clear stale results when region changes
if "uncertainty_region" in st.session_state and st.session_state["uncertainty_region"] != region_id:
    for key in ["tornado_result", "mc_result"]:
        st.session_state.pop(key, None)
st.session_state["uncertainty_region"] = region_id

formation_id = formation_selector(region)

if formation_id is None:
    st.stop()

if region_id == "norway-ncs":
    st.warning("NCS drilling model is preliminary. Uncertainty results are indicative only.")

# ── Tornado Sensitivity ──
st.subheader("Tornado Sensitivity")
st.caption("Shows how each parameter affects the break-even cost when varied between P10 and P90.")

if st.button("Run Sensitivity Analysis", type="primary", key="tornado_btn"):
    with st.spinner("Running sensitivity analysis..."):
        try:
            from ccs_costs.analysis import tornado_analysis
            result = tornado_analysis(
                formation_id=formation_id,
                region=region_id,
                parameters_to_vary=DEFAULT_TORNADO_PARAMS,
            )
            st.session_state["tornado_result"] = result
        except Exception as e:
            st.error(f"Sensitivity analysis failed: {e}")

if "tornado_result" in st.session_state:
    tr = st.session_state["tornado_result"]
    base = tr.base_output if hasattr(tr, "base_output") else 0
    bars = [b.model_dump() if hasattr(b, "model_dump") else b for b in tr.bars] if hasattr(tr, "bars") else tr
    render_tornado(bars, base_fbye=base, currency_sym=currency_sym)

st.divider()

# ── Monte Carlo ──
st.subheader("Monte Carlo Simulation")
st.caption("Probabilistic FBYE distribution from sampling uncertain parameters.")

col_mc1, col_mc2 = st.columns(2)
with col_mc1:
    n_samples = st.number_input("Samples", min_value=100, max_value=10000, value=500, step=100)
with col_mc2:
    seed = st.number_input("Random seed", min_value=0, max_value=99999, value=42)

if st.button("Run Monte Carlo", type="primary", key="mc_btn"):
    with st.spinner(f"Running {n_samples} Monte Carlo samples..."):
        try:
            from ccs_costs.analysis import run_monte_carlo
            mc_result = run_monte_carlo(
                formation_id=formation_id,
                region=region_id,
                n_samples=int(n_samples),
                seed=int(seed),
            )
            # Convert to dict if it's a Pydantic model
            if hasattr(mc_result, "model_dump"):
                mc_dict = mc_result.model_dump()
            elif hasattr(mc_result, "__dict__"):
                mc_dict = mc_result.__dict__
            else:
                mc_dict = mc_result
            st.session_state["mc_result"] = mc_dict
        except Exception as e:
            st.error(f"Monte Carlo failed: {e}")

if "mc_result" in st.session_state:
    render_monte_carlo(st.session_state["mc_result"], currency_sym=currency_sym)

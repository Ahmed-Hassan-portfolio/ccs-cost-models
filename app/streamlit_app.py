"""CCS Cost Engine — Streamlit App.

Entry point for the multi-page Streamlit application.
Run with: streamlit run app/streamlit_app.py
"""

import streamlit as st

st.set_page_config(
    page_title="CCS Cost Engine",
    page_icon="\u2699\ufe0f",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Shared state: region loading ──
from ccs_costs.config import list_available_regions, load_region


@st.cache_resource
def get_region(region_id: str):
    """Load region data (static reference data — cached as resource)."""
    return load_region(region_id)


@st.cache_data
def get_available_regions():
    return list_available_regions()


# ── Sidebar: region selector ──
st.sidebar.title("CCS Cost Engine")

regions = get_available_regions()
region_labels = {"us-goa": "US Gulf of America (117 formations)", "norway-ncs": "Norwegian Continental Shelf (14 formations)"}
region_id = st.sidebar.selectbox(
    "Region",
    options=regions,
    format_func=lambda x: region_labels.get(x, x),
)

region = get_region(region_id)
st.session_state["region_id"] = region_id
st.session_state["region"] = region

n_formations = len(region.formations)
st.sidebar.markdown(f"**{n_formations}** formations loaded")
st.sidebar.markdown(f"Currency: **{region.currency}** | Base year: **{region.base_year}**")

if region_id == "norway-ncs":
    st.sidebar.warning("NCS drilling model is preliminary. Results are indicative, not validated.")

st.sidebar.divider()
st.sidebar.caption("Engine: ccs-costs v1.0 | Python-based CO\u2082 storage cost estimation")

# ── Main page content ──
st.title("CO\u2082 Storage Cost Estimation")
st.markdown(
    "Calculate break-even storage costs for saline aquifer CCS projects. "
    "Select a region in the sidebar, then use the pages below."
)

st.markdown("### Pages")
st.page_link("pages/1_Evaluate.py", label="Evaluate a Formation", icon=":material/bar_chart:")
st.page_link("pages/2_Compare.py", label="Compare All Formations (Supply Curve)", icon=":material/trending_up:")
st.page_link("pages/3_Uncertainty.py", label="Sensitivity & Monte Carlo", icon=":material/casino:")
st.page_link("pages/4_Co_Author_Brief.py", label="Co-Author Brief", icon=":material/handshake:")

st.divider()
st.markdown("### Quick Start")
st.markdown(
    "1. **Select a region** in the sidebar\n"
    "2. Go to **Evaluate** and pick a formation\n"
    "3. Click **Evaluate** to see the break-even storage cost\n"
    "4. Use **Compare** to rank all formations by cost\n"
    "5. Use **Uncertainty** to see sensitivity and probability ranges"
)

if region_id == "us-goa":
    st.info(
        "The US-GOA model is cross-verified against the NETL CO\u2082_S_COM_Offshore Excel model. "
        "93.5% of 117 formations match within $3.00/t. "
        "Calibration formation (1241_1) matches within $0.42/t."
    )

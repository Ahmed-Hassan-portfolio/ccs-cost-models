"""Page 2: Compare all formations — supply curve."""

import sys
from pathlib import Path

import streamlit as st
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.charts import render_supply_curve

from ccs_costs.config import load_region
from ccs_costs.scenario import ScenarioConfig, evaluate_scenario

REGION_LABELS = {"us-goa": "US Gulf of America", "norway-ncs": "Norwegian Continental Shelf"}

st.header("Compare Formations (Supply Curve)")

region_id = st.session_state.get("region_id", "us-goa")

# Sidebar: region info (consistent with Home)
region = st.session_state.get("region")
if region is None:
    @st.cache_resource
    def _load_region(rid):
        return load_region(rid)
    region = _load_region(region_id)

n_formations = len(region.formations)
currency_sym = {"USD": "$", "NOK": "NOK ", "EUR": "\u20ac"}.get(region.currency, "")

st.sidebar.markdown(f"**Region:** {REGION_LABELS.get(region_id, region_id)}")
st.sidebar.markdown(f"**{n_formations}** formations loaded")
st.sidebar.markdown(f"Currency: **{region.currency}** | Base year: **{region.base_year}**")

region_display = REGION_LABELS.get(region_id, region_id)
st.markdown(f"Evaluate all **{n_formations}** formations in **{region_display}** and rank by break-even cost.")

if region_id == "norway-ncs":
    st.warning("NCS drilling model is preliminary. Rankings are indicative only.")

# Clear stale results when region changes
if "supply_curve_region" in st.session_state and st.session_state["supply_curve_region"] != region_id:
    st.session_state.pop("supply_curve", None)
st.session_state["supply_curve_region"] = region_id

if st.button(f"Generate Supply Curve ({n_formations} formations)", type="primary", use_container_width=True):
    progress = st.progress(0, text="Starting evaluation...")
    results = []

    for i, (fid, f) in enumerate(region.formations.items()):
        try:
            config = ScenarioConfig(formation_id=fid, region=region_id)
            r = evaluate_scenario(config)
            results.append({
                "formation_id": fid,
                "formation_name": f.name,
                "fybe": r.fybe,
                "well_count": r.n_injection_wells,
                "capex_musd": r.total_capex / 1e6,
                "opex_musd": r.total_opex / 1e6,
                "co2_mt": r.total_co2_stored_mt,
            })
        except Exception as e:
            results.append({
                "formation_id": fid,
                "formation_name": f.name,
                "fybe": None,
                "well_count": None,
                "capex_musd": None,
                "opex_musd": None,
                "co2_mt": None,
                "error": str(e)[:80],
            })
        progress.progress(
            (i + 1) / n_formations,
            text=f"Evaluated {i + 1}/{n_formations}: {f.name}",
        )

    progress.empty()
    st.session_state["supply_curve"] = results

if "supply_curve" in st.session_state:
    results = st.session_state["supply_curve"]
    successful = [r for r in results if r.get("fybe") is not None]
    failed = [r for r in results if r.get("fybe") is None]

    st.success(f"Evaluated {len(successful)}/{len(results)} formations successfully.")
    if failed:
        st.warning(f"{len(failed)} formations failed: {', '.join(f['formation_id'] for f in failed)}")

    if successful:
        render_supply_curve(successful, currency_sym=currency_sym)

        # Summary stats
        fybe_values = [r["fybe"] for r in successful]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cheapest", f"{currency_sym}{min(fybe_values):.2f}/t")
        c2.metric("Median", f"{currency_sym}{sorted(fybe_values)[len(fybe_values)//2]:.2f}/t")
        c3.metric("Most Expensive", f"{currency_sym}{max(fybe_values):.2f}/t")
        c4.metric("Formations", len(successful))

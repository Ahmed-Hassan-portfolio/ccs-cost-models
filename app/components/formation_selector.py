"""Reusable formation selector widget with property preview."""

from __future__ import annotations

import streamlit as st

from ccs_costs.config import RegionConfig


def formation_selector(region: RegionConfig) -> str | None:
    """Render a searchable formation selectbox with property preview.

    Args:
        region: Loaded RegionConfig with formations dict.

    Returns:
        Selected formation_id, or None if no formations available.
    """
    formations = region.formations
    if not formations:
        st.warning("No formations available for this region.")
        return None

    # Build display labels: "1241_1 — PL_A1 (1048m, phi=0.15)"
    options = list(formations.keys())
    labels = {}
    for fid, f in formations.items():
        depth = f"{f.depth_m:.0f}m"
        phi = f"\u03c6={f.porosity:.2f}"
        wd = f"WD={f.water_depth_m:.0f}m" if (f.water_depth_m or 0) > 0 else "onshore"
        labels[fid] = f"{f.name} ({fid}) \u2014 {depth}, {phi}, {wd}"

    selected = st.selectbox(
        "Formation",
        options=options,
        format_func=lambda x: labels[x],
    )

    # Show properties of selected formation
    f = formations[selected]
    with st.expander("Formation properties", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Depth", f"{f.depth_m:.0f} m")
        c2.metric("Porosity", f"{f.porosity:.2%}")
        c3.metric("Permeability", f"{f.permeability_md:.1f} mD")
        c4.metric("Water Depth", f"{f.water_depth_m or 0:.0f} m")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Temperature", f"{f.temperature_c:.1f} \u00b0C")
        c6.metric("Pressure", f"{f.pressure_mpa:.1f} MPa")
        c7.metric("Thickness", f"{f.thickness_m:.0f} m")
        c8.metric("Area", f"{f.area_km2:.0f} km\u00b2" if f.area_km2 else "N/A")

    return selected

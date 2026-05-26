"""Plotly chart builders for sensitivity, supply curve, and Monte Carlo."""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_tornado(tornado_data: list[dict], base_fbye: float, currency_sym: str = "$") -> None:
    """Render a tornado (sensitivity) chart from tornado_analysis results."""
    import plotly.graph_objects as go

    if not tornado_data:
        st.info("No sensitivity data to display.")
        return

    # Sort by swing ascending (plotly renders bottom-to-top)
    bars = sorted(tornado_data, key=lambda x: x.get("swing", 0))

    params = [b["parameter"] for b in bars]
    low_deltas = [b.get("output_at_low", b.get("fybe_at_low", 0)) - base_fbye for b in bars]
    high_deltas = [b.get("output_at_high", b.get("fbye_at_high", 0)) - base_fbye for b in bars]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=params, x=low_deltas, orientation="h",
        name="Low parameter", marker_color="#2196F3",
        hovertemplate="%{y}: %{x:+.2f}/t<extra>Low</extra>",
    ))
    fig.add_trace(go.Bar(
        y=params, x=high_deltas, orientation="h",
        name="High parameter", marker_color="#F44336",
        hovertemplate="%{y}: %{x:+.2f}/t<extra>High</extra>",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        barmode="overlay",
        height=max(300, len(bars) * 40 + 100),
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title=f"FBYE change ({currency_sym}/t)",
        title="Parameter Sensitivity (Tornado)",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_supply_curve(formations: list[dict], currency_sym: str = "$") -> None:
    """Render a step-function supply curve from run_supply_curve results."""
    import plotly.graph_objects as go
    import pandas as pd

    successful = [f for f in formations if f.get("fybe") is not None]
    if not successful:
        st.warning("No formations were successfully evaluated.")
        return

    df = pd.DataFrame(successful).sort_values("fybe")
    storage_key = "storage_capacity_gt" if "storage_capacity_gt" in df.columns else "co2_mt"
    if storage_key not in df.columns:
        # Fallback: use a constant
        df["cumulative"] = range(1, len(df) + 1)
        x_label = "Formation rank"
    else:
        df["cumulative"] = df[storage_key].cumsum()
        x_label = "Cumulative CO\u2082 Stored (Gt)" if storage_key == "storage_capacity_gt" else "Cumulative CO\u2082 (Mt)"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["cumulative"], y=df["fybe"],
        mode="lines", line_shape="hv",
        fill="tozeroy", fillcolor="rgba(33, 150, 243, 0.1)",
        line=dict(color="#2196F3", width=2),
        hovertemplate="%{text}<br>FBYE: " + currency_sym + "%{y:.2f}/t<extra></extra>",
        text=[f.get("formation_name", f.get("formation_id", "")) for f in df.to_dict("records")],
    ))
    fig.update_layout(
        xaxis_title=x_label,
        yaxis_title=f"FBYE ({currency_sym}/t)",
        height=500,
        title="Supply Curve \u2014 Formations Ranked by Cost",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Table below
    display_cols = ["formation_name", "formation_id", "fybe"]
    if "well_count" in df.columns:
        display_cols.append("well_count")
    if "capex_musd" in df.columns:
        display_cols.append("capex_musd")
    st.dataframe(df[display_cols].reset_index(drop=True), hide_index=True, use_container_width=True)


def render_monte_carlo(mc_result: dict, currency_sym: str = "$") -> None:
    """Render Monte Carlo summary metrics (P10/P50/P90/Mean)."""
    import plotly.graph_objects as go

    p10 = mc_result.get("p10", 0)
    p50 = mc_result.get("p50", 0)
    p90 = mc_result.get("p90", 0)
    mean = mc_result.get("mean", 0)

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("P10", f"{currency_sym}{p10:.2f}/t")
    c2.metric("P50 (Median)", f"{currency_sym}{p50:.2f}/t")
    c3.metric("P90", f"{currency_sym}{p90:.2f}/t")
    c4.metric("Mean", f"{currency_sym}{mean:.2f}/t")

    st.caption(
        f"Based on {mc_result.get('n_success', '?')} successful samples "
        f"({mc_result.get('n_failed', 0)} failed). "
        f"Seed: {mc_result.get('seed', 'N/A')}"
    )

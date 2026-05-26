"""Three-tier result rendering: Answer -> Story -> Details."""

from __future__ import annotations

import streamlit as st

from ccs_costs.scenario import ScenarioResults


# Cost category display groups: map raw categories to user-friendly names
_CATEGORY_GROUPS = {
    "drilling": "Drilling & Wells",
    "pipeline": "Pipeline & Transport",
    "infrastructure": "Surface Facilities",
    "monitoring": "Monitoring",
    "regulatory": "Regulatory & Compliance",
    "decommissioning": "Decommissioning",
    "additional": "Additional / Owner's Costs",
}


def _group_costs(cost_breakdown: dict[str, float]) -> dict[str, float]:
    """Group raw cost categories into display groups."""
    grouped: dict[str, float] = {}
    for raw_key, value in cost_breakdown.items():
        display = _CATEGORY_GROUPS.get(raw_key, raw_key.replace("_", " ").title())
        grouped[display] = grouped.get(display, 0.0) + value
    return dict(sorted(grouped.items(), key=lambda x: -x[1]))


def render_results(
    r: ScenarioResults,
    percentile: float | None = None,
    anchor_label: str | None = None,
    anchor_value: float | None = None,
) -> None:
    """Render a full scenario result in three tiers.

    Args:
        r: ScenarioResults from evaluate_scenario().
        percentile: Optional percentile position (0-100) among region formations.
        anchor_label: Optional comparison label (e.g., "NETL reference").
        anchor_value: Optional comparison FBYE value.
    """
    currency_sym = {"USD": "$", "NOK": "NOK ", "EUR": "\u20ac"}.get(r.currency, r.currency + " ")

    # ── Layer 1: THE ANSWER ──
    st.subheader("Break-Even Storage Cost")

    # Hero metric: FBYE in current-year dollars (or base year if no escalation)
    if r.fybe_current_year and r.fybe_current_year != r.fybe:
        col_hero, col_base, col_ref = st.columns(3)
        with col_hero:
            st.metric(
                "FBYE (2024 est.)",
                f"{currency_sym}{r.fybe_current_year:.2f}/t",
            )
        with col_base:
            st.metric(
                f"FBYE ({r.base_year} {r.currency})",
                f"{currency_sym}{r.fybe:.2f}/t",
            )
        with col_ref:
            if anchor_label and anchor_value is not None:
                delta = r.fybe - anchor_value
                st.metric(anchor_label, f"{currency_sym}{anchor_value:.2f}/t",
                           delta=f"{delta:+.2f}/t", delta_color="inverse")
    else:
        col_hero, col_ref = st.columns(2)
        with col_hero:
            st.metric(
                f"FBYE ({r.base_year} {r.currency})",
                f"{currency_sym}{r.fybe:.2f}/t",
            )
        with col_ref:
            if anchor_label and anchor_value is not None:
                delta = r.fybe - anchor_value
                st.metric(anchor_label, f"{currency_sym}{anchor_value:.2f}/t",
                           delta=f"{delta:+.2f}/t", delta_color="inverse")

    if percentile is not None:
        pct_int = int(percentile)
        filled = pct_int // 5
        empty = 20 - filled
        bar = "\u2588" * filled + "\u2591" * empty
        st.text(f"Percentile: P{pct_int} of region formations")
        st.text(bar)

    # ── Layer 2: THE STORY ──
    st.divider()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Injection Wells", r.n_injection_wells)
    c2.metric("Monitoring Wells", r.n_monitoring_wells)
    c3.metric("Pipeline Length", f"{r.pipeline_length_km:.0f} km")
    c4.metric("Pipeline Dia.", f'{r.pipeline_diameter_inches:.0f}"')
    c5.metric("CO\u2082 Stored", f"{r.total_co2_stored_mt:.0f} Mt")

    c6, c7, c8, c9 = st.columns(4)
    c6.metric("Total CAPEX", f"{currency_sym}{r.total_capex / 1e6:,.0f}M")
    c7.metric("Total OPEX", f"{currency_sym}{r.total_opex / 1e6:,.0f}M")
    c8.metric("Project Duration", f"{r.project_duration_years} yr")
    c9.metric("CO\u2082 Density", f"{r.co2_density_kgm3:.0f} kg/m\u00b3")

    # Cost breakdown chart
    if r.cost_breakdown:
        st.divider()
        st.subheader("Cost Breakdown")
        _render_cost_chart(r.cost_breakdown, r.total_capex + r.total_opex, currency_sym)

    # ── Layer 3: DETAILS ──
    with st.expander("Detailed cost table"):
        _render_cost_table(r.cost_breakdown, r.total_capex + r.total_opex, currency_sym)

    with st.expander("Geological parameters"):
        gc1, gc2, gc3 = st.columns(3)
        gc1.metric("Storage Coefficient", f"{r.storage_coefficient:.4f}")
        gc2.metric("Plume Area", f"{r.plume_area_km2:.1f} km\u00b2")
        gc3.metric("CO\u2082 Density", f"{r.co2_density_kgm3:.1f} kg/m\u00b3")

    with st.expander("Interpretation"):
        st.info(r.fybe_interpretation)


def _render_cost_chart(
    cost_breakdown: dict[str, float],
    total: float,
    currency_sym: str,
) -> None:
    """Horizontal stacked bar chart for cost breakdown."""
    import plotly.graph_objects as go

    grouped = _group_costs(cost_breakdown)

    colors = [
        "#2196F3", "#4CAF50", "#FF9800", "#9C27B0",
        "#F44336", "#00BCD4", "#795548", "#607D8B",
    ]

    fig = go.Figure()
    for i, (cat, val) in enumerate(grouped.items()):
        pct = val / total * 100 if total > 0 else 0
        fig.add_trace(go.Bar(
            y=["Total Cost"],
            x=[val / 1e6],
            name=f"{cat} ({pct:.0f}%)",
            orientation="h",
            marker_color=colors[i % len(colors)],
            text=f"{currency_sym}{val / 1e6:,.0f}M",
            textposition="inside",
            hovertemplate=f"{cat}<br>{currency_sym}{val / 1e6:,.1f}M ({pct:.1f}%)<extra></extra>",
        ))

    fig.update_layout(
        barmode="stack",
        height=180,
        margin=dict(l=0, r=0, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=f"{currency_sym}M (lifetime undiscounted)",
        xaxis_title_standoff=15,
        yaxis=dict(visible=False),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_cost_table(
    cost_breakdown: dict[str, float],
    total: float,
    currency_sym: str,
) -> None:
    """Detailed cost table with percentages."""
    import pandas as pd

    grouped = _group_costs(cost_breakdown)

    rows = []
    for cat, val in grouped.items():
        pct = val / total * 100 if total > 0 else 0
        rows.append({
            "Category": cat,
            f"Cost ({currency_sym}M)": f"{val / 1e6:,.1f}",
            "Share (%)": f"{pct:.1f}%",
        })
    rows.append({
        "Category": "TOTAL",
        f"Cost ({currency_sym}M)": f"{total / 1e6:,.1f}",
        "Share (%)": "100.0%",
    })

    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)

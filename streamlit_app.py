from __future__ import annotations

import json

import streamlit as st

from VO_GERT_MCS_Final_Appendix import (
    DEFAULT_REPLICATIONS,
    DEFAULT_SEED,
    GERT_ARCS,
    PERT_ACTIVITIES,
    run_gert,
    run_pert,
    summarise_results,
    validate_model,
)
from dashboard_analysis import (
    dispute_comparison_figure,
    ecdf_figure,
    histogram_with_refs,
    loop_depth_figure,
    loop_frequency_figure,
    outcome_probability_convergence_figure,
    outcome_probability_figure,
    outcome_variance_decomposition,
    overall_gert_outcome_histogram,
    overlay_histogram,
    percentile_comparison_figure,
    pert_activity_variance_figure,
    quantile_difference_figure,
    route_pareto_figure,
    rows_to_csv,
    summary_rows,
    top_routes_rows,
    upper_tail_composition_figure,
    convergence_figure,
)

st.set_page_config(
    page_title="GERT–MCS VO Lifecycle Simulator",
    page_icon="📊",
    layout="wide",
)

@st.cache_data(show_spinner=False)
def run_thesis_simulation(replications: int, seed: int):
    validate_model(PERT_ACTIVITIES, GERT_ARCS)
    pert = run_pert(PERT_ACTIVITIES, replications=replications, seed=seed)
    gert = run_gert(GERT_ARCS, replications=replications, seed=seed)
    summary = summarise_results(pert, gert, seed)
    return pert, gert, summary

def json_bytes(obj: object) -> bytes:
    return json.dumps(obj, indent=2).encode("utf-8")

st.title("GERT–MCS Variation Order Lifecycle Simulator")
st.caption(
    "Thesis reproduction dashboard for fixed-route PERT–MCS and routing-aware GERT–MCS."
)

with st.sidebar:
    st.header("Simulation settings")
    replications = st.number_input(
        "Replications",
        min_value=1_000,
        max_value=100_000,
        value=DEFAULT_REPLICATIONS,
        step=1_000,
    )
    seed = st.number_input(
        "Random seed",
        min_value=0,
        max_value=2_147_483_647,
        value=DEFAULT_SEED,
        step=1,
    )
    run_button = st.button("Run full thesis dashboard", type="primary", use_container_width=True)

st.info(
    "This version reproduces and compares the thesis PERT–MCS and GERT–MCS analyses using the "
    "verified baseline network and parameters. Custom VO input will be added after the thesis "
    "reproduction dashboard is fully verified."
)

if not run_button:
    st.markdown(
        """
### Baseline configuration
- Fixed-route PERT–MCS and routing-aware GERT–MCS
- Beta-PERT duration sampling
- PCG64 random-number generation
- Per-draw ceiling to whole working days
- Bounded recurrence with XOR routing
- Outcome-conditioned comparison between PERT and Successful GERT
"""
    )
    st.write("Set the simulation options in the sidebar and click **Run full thesis dashboard**.")
    st.stop()

with st.spinner("Running PERT–MCS and GERT–MCS and preparing analytical outputs..."):
    pert, gert, summary = run_thesis_simulation(int(replications), int(seed))

pert_summary = summary["pert_mcs"]
gert_summary = summary["gert_mcs"]
success_summary = gert_summary["successful_closeout"]
withdrawn_summary = gert_summary["withdrawn_rejected"]

success_mask = gert.outcome_codes == 1
withdrawn_mask = gert.outcome_codes == 0
gert_success = gert.totals[success_mask]
gert_withdrawn = gert.totals[withdrawn_mask]

st.success("Simulation completed successfully.")

st.subheader("Executive comparison")
c1, c2, c3, c4 = st.columns(4)
c1.metric("PERT mean", f'{pert_summary["mean"]:.3f} days')
c2.metric("Successful GERT mean", f'{success_summary["mean"]:.3f} days')
c3.metric("PERT P95", f'{pert_summary["p95"]} days')
c4.metric("Successful GERT P95", f'{success_summary["p95"]} days')

c5, c6, c7, c8 = st.columns(4)
c5.metric("PERT P50", f'{pert_summary["p50"]} days')
c6.metric("Successful GERT P50", f'{success_summary["p50"]} days')
c7.metric("Successful Closeout", f'{100 * gert_summary["successful_probability"]:.2f}%')
c8.metric("Non-Implementation Closure", f'{100 * gert_summary["withdrawn_rejected_probability"]:.2f}%')

tabs = st.tabs([
    "Overview",
    "PERT analysis",
    "GERT analysis",
    "PERT vs GERT",
    "Structural GERT",
    "Upper tail",
    "Downloads",
])

with tabs[0]:
    st.subheader("Principal thesis results")
    rows = summary_rows(pert, gert)
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.pyplot(percentile_comparison_figure(pert.totals, gert_success))
    st.pyplot(outcome_probability_figure(gert))

with tabs[1]:
    st.subheader("PERT–MCS fixed-route analysis")
    st.pyplot(
        histogram_with_refs(
            pert.totals,
            "PERT–MCS Fixed-Route Lifecycle-Time Distribution",
            {
                "Mean": float(pert_summary["mean"]),
                "P50": float(pert_summary["p50"]),
                "P90": float(pert_summary["p90"]),
                "P95": float(pert_summary["p95"]),
            },
        )
    )
    st.pyplot(ecdf_figure([("PERT–MCS", pert.totals)], "PERT–MCS Empirical Cumulative Distribution"))
    st.pyplot(convergence_figure(pert.totals, "Convergence of PERT–MCS Mean, P90, and P95"))
    activity_labels = [item.tag for item in PERT_ACTIVITIES]
    variance_fig, shares = pert_activity_variance_figure(pert, activity_labels)
    st.pyplot(variance_fig)
    variance_rows = [
        {"Transition": item.tag, "Stage": item.stage, "Variance share (%)": float(share)}
        for item, share in zip(PERT_ACTIVITIES, shares)
    ]
    st.dataframe(variance_rows, use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("GERT–MCS outcome-conditioned analysis")
    st.pyplot(overall_gert_outcome_histogram(gert))
    st.pyplot(outcome_probability_figure(gert))
    variance_fig, within_share, between_share = outcome_variance_decomposition(gert)
    st.pyplot(variance_fig)
    st.caption(
        f"Within-outcome variance share: {within_share:.3f}% | "
        f"Between-outcome variance share: {between_share:.3f}%"
    )

    st.markdown("#### Successful Closeout")
    st.pyplot(
        histogram_with_refs(
            gert_success,
            "GERT–MCS Successful-Closeout Lifecycle-Time Distribution",
            {
                "Mean": float(success_summary["mean"]),
                "P50": float(success_summary["p50"]),
                "P90": float(success_summary["p90"]),
                "P95": float(success_summary["p95"]),
            },
        )
    )
    st.pyplot(ecdf_figure([("Successful GERT–MCS", gert_success)], "Successful GERT–MCS ECDF"))
    st.pyplot(convergence_figure(gert_success, "Convergence of Successful GERT–MCS Mean, P90, and P95"))
    st.pyplot(outcome_probability_convergence_figure(gert))

    st.markdown("#### Withdrawn/Rejected Closure")
    st.pyplot(
        histogram_with_refs(
            gert_withdrawn,
            "GERT–MCS Withdrawn/Rejected Lifecycle-Time Distribution",
            {
                "Mean": float(withdrawn_summary["mean"]),
                "P50": float(withdrawn_summary["p50"]),
                "P95": float(withdrawn_summary["p95"]),
            },
        )
    )

with tabs[3]:
    st.subheader("Controlled PERT–MCS vs Successful GERT–MCS comparison")
    st.caption(
        "Successful GERT outcomes are used for the direct duration comparison because they reach "
        "the same terminal objective represented by the fixed-route PERT baseline."
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.pyplot(overlay_histogram(pert.totals, gert_success))
    st.pyplot(
        ecdf_figure(
            [("PERT–MCS", pert.totals), ("Successful GERT–MCS", gert_success)],
            "PERT–MCS vs Successful GERT–MCS ECDF",
        )
    )
    st.pyplot(percentile_comparison_figure(pert.totals, gert_success))
    st.pyplot(quantile_difference_figure(pert.totals, gert_success))

with tabs[4]:
    st.subheader("Structural behavior of the GERT network")
    st.pyplot(loop_depth_figure(gert))
    st.pyplot(loop_frequency_figure(gert))
    st.pyplot(route_pareto_figure(gert, top_n=25))

    st.markdown("#### Ten most frequently realised exact routes")
    routes = top_routes_rows(gert, top_n=10)
    st.dataframe(routes, use_container_width=True, hide_index=True)

    st.markdown("#### Dispute diversion")
    st.pyplot(dispute_comparison_figure(gert))
    d1, d2, d3 = st.columns(3)
    d1.metric("Dispute diversion probability", f'{100 * gert_summary["dispute_diversion_probability"]:.2f}%')
    d2.metric("Any-loop probability", f'{100 * gert_summary["any_loop_probability"]:.2f}%')
    d3.metric("Exact realised routes", f'{gert_summary["exact_route_count"]}')

with tabs[5]:
    st.subheader("Successful upper-tail structural analysis")
    st.pyplot(upper_tail_composition_figure(gert))
    tail_rows = []
    for label, details in gert_summary["upper_tail_diagnostics"].items():
        tail_rows.append({
            "Tail": label.upper(),
            "Threshold (days)": details["threshold_working_days"],
            "Cases": details["count"],
            "Loop-bearing share (%)": 100 * details["feedback_or_self_loop_share"],
            "Dispute-bearing share (%)": 100 * details["dispute_share"],
        })
    st.dataframe(tail_rows, use_container_width=True, hide_index=True)

with tabs[6]:
    st.subheader("Download reproducibility outputs")
    st.download_button(
        "Download complete simulation summary (JSON)",
        data=json_bytes(summary),
        file_name="simulation_summary.json",
        mime="application/json",
    )
    st.download_button(
        "Download PERT vs GERT comparison (CSV)",
        data=rows_to_csv(rows),
        file_name="pert_vs_gert_comparison.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download top realised routes (CSV)",
        data=rows_to_csv(top_routes_rows(gert, top_n=50)),
        file_name="top_realised_routes.csv",
        mime="text/csv",
    )

st.warning(
    "Scope: this application evaluates process-level VO lifecycle time under the specified model "
    "assumptions. It does not determine whole-project completion delay, EOT entitlement, "
    "contractual liability, or cost impact."
)

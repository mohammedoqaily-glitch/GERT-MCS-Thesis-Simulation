from __future__ import annotations

import json
from dataclasses import replace

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

# Redeploy trigger: stable dashboard baseline after rollback.
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
    scenario_mode = st.radio(
        "Input mode",
        ["Thesis baseline", "Custom input scenario"],
        index=0,
    )
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
    "The thesis baseline reproduces the verified model. Custom input mode allows all O/ML/P duration "
    "triplets and GERT routing probabilities to be edited while keeping loop caps, network topology, "
    "RNG logic, and rounding rules fixed."
)


st.subheader("Model inputs")

EDITOR_VERSION = "routing-editable-v2"
if st.session_state.get("_editor_version") != EDITOR_VERSION:
    st.session_state["_editor_version"] = EDITOR_VERSION
    st.session_state.pop("duration_editor", None)
    st.session_state.pop("custom_input_editor_v2", None)

if "custom_duration_rows" not in st.session_state:
    st.session_state.custom_duration_rows = [
        {
            "Arc": arc.tag,
            "From": arc.from_state,
            "To": arc.to_state,
            "Probability": arc.probability,
            "Loop cap": None if arc.loop_cap is None else arc.loop_cap,
            "O": float(arc.optimistic),
            "ML": float(arc.most_likely),
            "P": float(arc.pessimistic),
        }
        for arc in GERT_ARCS
    ]

if "custom_loop_caps" not in st.session_state:
    st.session_state.custom_loop_caps = [
        {"Arc": arc.tag, "From": arc.from_state, "To": arc.to_state, "Loop cap": int(arc.loop_cap)}
        for arc in GERT_ARCS
        if arc.loop_cap is not None
    ]

duration_errors = []
loop_cap_errors = []

if scenario_mode == "Thesis baseline":
    st.caption("Authoritative thesis inputs (read-only).")
    input_tabs = st.tabs(["PERT fixed-route inputs", "GERT network inputs"])

    with input_tabs[0]:
        pert_rows = [
            {
                "Arc": item.tag,
                "Process stage": item.stage,
                "From": item.predecessor,
                "To": item.successor,
                "O": item.optimistic,
                "ML": item.most_likely,
                "P": item.pessimistic,
            }
            for item in PERT_ACTIVITIES
        ]
        st.dataframe(pert_rows, width="stretch", hide_index=True)

    with input_tabs[1]:
        gert_rows = [
            {
                "Arc": arc.tag,
                "From": arc.from_state,
                "To": arc.to_state,
                "Probability": arc.probability,
                "Loop cap": "—" if arc.loop_cap is None else arc.loop_cap,
                "O": arc.optimistic,
                "ML": arc.most_likely,
                "P": arc.pessimistic,
            }
            for arc in GERT_ARCS
        ]
        st.dataframe(gert_rows, width="stretch", hide_index=True)
else:
    st.caption(
        "Edit the GERT routing probabilities and all O/ML/P duration triplets below. "
        "PERT common-route durations are synchronized automatically from matching GERT arcs."
    )
    edited = st.data_editor(
        st.session_state.custom_duration_rows,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=["Arc", "From", "To", "Loop cap"],
        column_config={
            "Probability": st.column_config.NumberColumn("Probability", min_value=0.0, max_value=1.0, step=0.01, format="%.4f"),
            "O": st.column_config.NumberColumn("O", min_value=0.0, step=1.0),
            "ML": st.column_config.NumberColumn("ML", min_value=0.0, step=1.0),
            "P": st.column_config.NumberColumn("P", min_value=0.0, step=1.0),
        },
        key="custom_input_editor_v2",
    )
    if hasattr(edited, "to_dict"):
        st.session_state.custom_duration_rows = edited.to_dict("records")
    else:
        st.session_state.custom_duration_rows = [dict(row) for row in edited]

    for row in st.session_state.custom_duration_rows:
        try:
            o, ml, p = float(row["O"]), float(row["ML"]), float(row["P"])
            if not (0 <= o <= ml <= p):
                duration_errors.append(
                    f'{row["Arc"]}: require 0 ≤ O ≤ ML ≤ P; received {o:g}, {ml:g}, {p:g}.'
                )
        except Exception:
            duration_errors.append(f'{row["Arc"]}: duration values must be numeric.')

    routing_errors = []
    custom_routing_totals = {}
    for row in st.session_state.custom_duration_rows:
        state = str(row["From"])
        try:
            probability = float(row["Probability"])
            if not (0.0 <= probability <= 1.0):
                routing_errors.append(
                    f'{row["Arc"]}: probability must be between 0 and 1; received {probability:g}.'
                )
            custom_routing_totals.setdefault(state, 0.0)
            custom_routing_totals[state] += probability
        except Exception:
            routing_errors.append(f'{row["Arc"]}: probability must be numeric.')

    for state, total in custom_routing_totals.items():
        if abs(total - 1.0) > 1e-12:
            routing_errors.append(
                f'{state}: outgoing probabilities must sum to 1.000000; current sum={total:.6f}.'
            )

    if duration_errors:
        st.error("Duration-input validation failed.")
        for error in duration_errors:
            st.write("• " + error)
    else:
        st.success("All duration triplets satisfy 0 ≤ O ≤ ML ≤ P.")

    if routing_errors:
        st.error("Routing-probability validation failed.")
        for error in routing_errors:
            st.write("• " + error)
    else:
        st.success("All routing probabilities are within [0,1] and each XOR group sums to 1.")

    st.markdown("#### Loop-cap settings")
    st.caption("Edit the maximum permitted traversals for each bounded feedback/self-loop arc.")

    updated_caps = []
    cap_cols = st.columns(2)
    for idx, row in enumerate(st.session_state.custom_loop_caps):
        with cap_cols[idx % 2]:
            cap_value = st.number_input(
                f'{row["Arc"]} ({row["From"]}→{row["To"]})',
                min_value=0,
                max_value=20,
                value=int(row["Loop cap"]),
                step=1,
                key=f'loop_cap_input_v2_{row["Arc"]}',
            )
        updated_caps.append(
            {
                "Arc": row["Arc"],
                "From": row["From"],
                "To": row["To"],
                "Loop cap": int(cap_value),
            }
        )
    st.session_state.custom_loop_caps = updated_caps

    for row in st.session_state.custom_loop_caps:
        cap = row["Loop cap"]
        if not isinstance(cap, int) or cap < 0:
            loop_cap_errors.append(
                f'{row["Arc"]}: loop cap must be a non-negative integer; received {cap}.'
            )

    if loop_cap_errors:
        st.error("Loop-cap validation failed.")
        for error in loop_cap_errors:
            st.write("• " + error)
    else:
        st.success("All 10 bounded-recurrence loop caps are valid non-negative integers.")

    if st.button("Restore thesis input defaults", width="stretch"):
        st.session_state.custom_duration_rows = [
            {
                "Arc": arc.tag,
                "From": arc.from_state,
                "To": arc.to_state,
                "Probability": arc.probability,
                "Loop cap": None if arc.loop_cap is None else arc.loop_cap,
                "O": float(arc.optimistic),
                "ML": float(arc.most_likely),
                "P": float(arc.pessimistic),
            }
            for arc in GERT_ARCS
        ]
        st.session_state.custom_loop_caps = [
            {"Arc": arc.tag, "From": arc.from_state, "To": arc.to_state, "Loop cap": int(arc.loop_cap)}
            for arc in GERT_ARCS
            if arc.loop_cap is not None
        ]
        st.session_state.pop("duration_editor", None)
        st.session_state.pop("custom_input_editor_v2", None)
        st.session_state.pop("loop_cap_editor_v1", None)
        for arc in GERT_ARCS:
            if arc.loop_cap is not None:
                st.session_state.pop(f"loop_cap_input_v2_{arc.tag}", None)
        st.rerun()

routing_totals = {}
if scenario_mode == "Thesis baseline":
    for arc in GERT_ARCS:
        routing_totals.setdefault(arc.from_state, 0.0)
        routing_totals[arc.from_state] += arc.probability
else:
    for row in st.session_state.custom_duration_rows:
        state = str(row["From"])
        routing_totals.setdefault(state, 0.0)
        routing_totals[state] += float(row["Probability"])
st.markdown("#### XOR routing totals")
st.dataframe(
    [
        {
            "Branching state": state,
            "Σp": total,
            "Status": "PASS" if abs(total - 1.0) <= 1e-12 else "FAIL",
        }
        for state, total in routing_totals.items()
    ],
    width="stretch",
    hide_index=True,
)

if run_button and scenario_mode == "Custom input scenario" and (duration_errors or routing_errors or loop_cap_errors):
    st.error("Simulation was not started because one or more custom inputs are invalid.")
    st.stop()

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
    if scenario_mode == "Thesis baseline":
        active_pert_activities = PERT_ACTIVITIES
        active_gert_arcs = GERT_ARCS
        pert, gert, summary = run_thesis_simulation(int(replications), int(seed))
    else:
        custom_by_tag = {row["Arc"]: row for row in st.session_state.custom_duration_rows}
        custom_caps = {
            row["Arc"]: int(float(row["Loop cap"])) for row in st.session_state.custom_loop_caps
        }
        active_gert_arcs = tuple(
            replace(
                arc,
                probability=float(custom_by_tag[arc.tag]["Probability"]),
                loop_cap=custom_caps.get(arc.tag, arc.loop_cap),
                optimistic=float(custom_by_tag[arc.tag]["O"]),
                most_likely=float(custom_by_tag[arc.tag]["ML"]),
                pessimistic=float(custom_by_tag[arc.tag]["P"]),
            )
            for arc in GERT_ARCS
        )
        active_arc_by_tag = {arc.tag: arc for arc in active_gert_arcs}
        active_pert_activities = tuple(
            replace(
                item,
                optimistic=active_arc_by_tag[item.tag].optimistic,
                most_likely=active_arc_by_tag[item.tag].most_likely,
                pessimistic=active_arc_by_tag[item.tag].pessimistic,
            )
            for item in PERT_ACTIVITIES
        )
        validate_model(active_pert_activities, active_gert_arcs)
        pert = run_pert(active_pert_activities, replications=int(replications), seed=int(seed))
        gert = run_gert(active_gert_arcs, replications=int(replications), seed=int(seed))
        summary = summarise_results(pert, gert, int(seed))

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
    activity_labels = [item.tag for item in active_pert_activities]
    variance_fig, shares = pert_activity_variance_figure(pert, activity_labels)
    st.pyplot(variance_fig)
    variance_rows = [
        {"Transition": item.tag, "Stage": item.stage, "Variance share (%)": float(share)}
        for item, share in zip(active_pert_activities, shares)
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

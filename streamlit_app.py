from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from VO_GERT_MCS_Final_Appendix import (
    DEFAULT_REPLICATIONS,
    DEFAULT_SEED,
    GERT_ARCS,
    PERT_ACTIVITIES,
    summarise_results,
    validate_model,
    run_gert,
    run_pert,
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
from interactive_engine import run_gert_custom, run_pert_custom
from model_inputs import (
    dataframe_to_activities,
    dataframe_to_arcs,
    full_input_validation,
    thesis_gert_dataframe,
    thesis_pert_dataframe,
    validation_passes,
)

st.set_page_config(
    page_title="GERT–MCS VO Lifecycle Simulator",
    page_icon="📊",
    layout="wide",
)

def json_bytes(obj: object) -> bytes:
    return json.dumps(obj, indent=2).encode("utf-8")


@st.cache_data(show_spinner=False)
def run_thesis_simulation(replications: int, seed: int):
    validate_model(PERT_ACTIVITIES, GERT_ARCS)
    pert = run_pert(PERT_ACTIVITIES, replications=replications, seed=seed)
    gert = run_gert(GERT_ARCS, replications=replications, seed=seed)
    summary = summarise_results(pert, gert, seed)
    return pert, gert, summary


@st.cache_data(show_spinner=False)
def run_custom_simulation(
    pert_records: list[dict],
    gert_records: list[dict],
    replications: int,
    seed: int,
    distribution: str,
    beta_lambda: float,
    max_steps: int,
):
    pert_df = pd.DataFrame(pert_records)
    gert_df = pd.DataFrame(gert_records)
    activities = dataframe_to_activities(pert_df)
    arcs = dataframe_to_arcs(gert_df)
    validate_model(activities, arcs)

    pert = run_pert_custom(
        activities,
        replications=replications,
        seed=seed,
        distribution=distribution,
        beta_pert_lambda=beta_lambda,
    )
    gert = run_gert_custom(
        arcs,
        replications=replications,
        seed=seed,
        distribution=distribution,
        beta_pert_lambda=beta_lambda,
        max_steps=max_steps,
    )
    summary = summarise_results(pert, gert, seed)
    summary["configuration"]["duration_distribution"] = distribution
    summary["configuration"]["beta_pert_lambda"] = beta_lambda
    summary["configuration"]["maximum_steps"] = max_steps
    return activities, arcs, pert, gert, summary


def render_results(activities, pert, gert, summary, heading: str) -> None:
    pert_summary = summary["pert_mcs"]
    gert_summary = summary["gert_mcs"]
    success_summary = gert_summary["successful_closeout"]
    withdrawn_summary = gert_summary["withdrawn_rejected"]

    success_mask = gert.outcome_codes == 1
    withdrawn_mask = gert.outcome_codes == 0
    gert_success = gert.totals[success_mask]
    gert_withdrawn = gert.totals[withdrawn_mask]

    st.header(heading)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PERT mean", f'{pert_summary["mean"]:.3f} days')
    c2.metric("Successful GERT mean", f'{success_summary["mean"]:.3f} days')
    c3.metric("PERT P95", f'{pert_summary["p95"]} days')
    c4.metric("Successful GERT P95", f'{success_summary["p95"]} days')

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("PERT P50", f'{pert_summary["p50"]} days')
    c6.metric("Successful GERT P50", f'{success_summary["p50"]} days')
    c7.metric("Successful Closeout", f'{100 * gert_summary["successful_probability"]:.2f}%')
    c8.metric("Withdrawn/Rejected", f'{100 * gert_summary["withdrawn_rejected_probability"]:.2f}%')

    tabs = st.tabs([
        "Overview",
        "PERT–MCS",
        "GERT–MCS",
        "PERT vs GERT",
        "Structural GERT",
        "Upper tail",
        "Downloads",
    ])

    rows = summary_rows(pert, gert)

    with tabs[0]:
        st.subheader("Principal comparison")
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.pyplot(percentile_comparison_figure(pert.totals, gert_success))
        st.pyplot(outcome_probability_figure(gert))

    with tabs[1]:
        st.subheader("PERT–MCS fixed-route results")
        st.pyplot(
            histogram_with_refs(
                pert.totals,
                "PERT–MCS Fixed-Route Lifecycle-Time Distribution",
                {
                    "Mean": float(pert_summary["mean"]),
                    "P50": float(pert_summary["p50"]),
                    "P80": float(pert_summary["p80"]),
                    "P90": float(pert_summary["p90"]),
                    "P95": float(pert_summary["p95"]),
                },
            )
        )
        st.pyplot(ecdf_figure([("PERT–MCS", pert.totals)], "PERT–MCS Empirical Cumulative Distribution"))
        st.pyplot(convergence_figure(pert.totals, "Convergence of PERT–MCS Mean, P90, and P95"))

        labels = [item.tag for item in activities]
        variance_fig, shares = pert_activity_variance_figure(pert, labels)
        st.pyplot(variance_fig)
        variance_rows = [
            {"Transition": item.tag, "Stage": item.stage, "Variance share (%)": float(share)}
            for item, share in zip(activities, shares)
        ]
        st.dataframe(variance_rows, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("GERT–MCS results by terminal outcome")
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
                    "P80": float(success_summary["p80"]),
                    "P90": float(success_summary["p90"]),
                    "P95": float(success_summary["p95"]),
                    "P99": float(success_summary["p99"]),
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
                    "P99": float(withdrawn_summary["p99"]),
                },
            )
        )

    with tabs[3]:
        st.subheader("Controlled PERT–MCS vs Successful GERT–MCS comparison")
        st.caption(
            "The direct duration comparison conditions GERT on Successful Closeout so that both "
            "models are compared against the same terminal objective."
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


st.title("GERT–MCS Variation Order Lifecycle Simulator")
st.caption("Full-input PERT–MCS and routing-aware GERT–MCS simulation interface.")

mode = st.sidebar.radio(
    "Mode",
    ["Reproduce thesis model", "Custom VO scenario"],
    index=0,
)

if mode == "Reproduce thesis model":
    with st.sidebar:
        st.header("Execution settings")
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
        run_button = st.button("Run thesis reproduction", type="primary", use_container_width=True)

    st.info(
        "This mode uses the authoritative thesis PERT activities, GERT network, probabilities, "
        "duration triplets, loop caps, Beta-PERT λ=4, and the selected replication/seed settings."
    )

    if run_button:
        with st.spinner("Running thesis PERT–MCS and GERT–MCS..."):
            pert, gert, summary = run_thesis_simulation(int(replications), int(seed))
        st.success("Thesis simulation completed.")
        render_results(PERT_ACTIVITIES, pert, gert, summary, "Thesis reproduction results")
    else:
        st.write("Click **Run thesis reproduction** to generate the complete baseline results.")

else:
    st.warning(
        "Custom mode keeps the thesis network topology fixed but exposes the complete numerical "
        "simulation inputs: all PERT O/ML/P values, all 29 GERT O/ML/P values, all routing "
        "probabilities, all loop caps, distribution settings, replications, seed, λ, and step guard."
    )

    config_tab, pert_tab, gert_tab, validation_tab, results_tab = st.tabs([
        "1. Configuration",
        "2. PERT inputs",
        "3. GERT inputs",
        "4. Validate",
        "5. Results",
    ])

    if "custom_pert_df" not in st.session_state:
        st.session_state.custom_pert_df = thesis_pert_dataframe()
    if "custom_gert_df" not in st.session_state:
        st.session_state.custom_gert_df = thesis_gert_dataframe()

    with config_tab:
        c1, c2, c3 = st.columns(3)
        custom_replications = c1.number_input(
            "Replications",
            min_value=1_000,
            max_value=100_000,
            value=50_000,
            step=1_000,
            key="custom_replications",
        )
        custom_seed = c2.number_input(
            "Random seed",
            min_value=0,
            max_value=2_147_483_647,
            value=42,
            step=1,
            key="custom_seed",
        )
        distribution_label = c3.selectbox(
            "Duration distribution",
            ["Beta-PERT", "Triangular"],
            index=0,
            key="custom_distribution",
        )

        c4, c5 = st.columns(2)
        beta_lambda = c4.number_input(
            "Beta-PERT lambda (λ)",
            min_value=0.1,
            max_value=20.0,
            value=4.0,
            step=0.1,
            disabled=distribution_label != "Beta-PERT",
            key="custom_lambda",
        )
        max_steps = c5.number_input(
            "Maximum-step safeguard",
            min_value=10,
            max_value=1_000_000,
            value=100_000,
            step=1_000,
            key="custom_max_steps",
        )

        if st.button("Restore all thesis defaults", use_container_width=True):
            st.session_state.custom_pert_df = thesis_pert_dataframe()
            st.session_state.custom_gert_df = thesis_gert_dataframe()
            st.session_state.custom_replications = 50_000
            st.session_state.custom_seed = 42
            st.session_state.custom_distribution = "Beta-PERT"
            st.session_state.custom_lambda = 4.0
            st.session_state.custom_max_steps = 100_000
            st.rerun()

    with pert_tab:
        st.subheader("Complete PERT fixed-route duration inputs")
        st.caption("Edit O, ML, and P. Structural identifiers are locked to preserve the thesis comparison topology.")
        pert_columns = {
            "tag": st.column_config.TextColumn("Arc", disabled=True),
            "stage": st.column_config.TextColumn("Process stage", disabled=True),
            "predecessor": st.column_config.TextColumn("From", disabled=True),
            "successor": st.column_config.TextColumn("To", disabled=True),
            "optimistic": st.column_config.NumberColumn("O", min_value=0.0, step=1.0),
            "most_likely": st.column_config.NumberColumn("ML", min_value=0.0, step=1.0),
            "pessimistic": st.column_config.NumberColumn("P", min_value=0.0, step=1.0),
        }
        st.session_state.custom_pert_df = st.data_editor(
            st.session_state.custom_pert_df,
            column_config=pert_columns,
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="pert_editor",
        )

    with gert_tab:
        st.subheader("Complete GERT routing, duration, and recurrence inputs")
        st.caption("All 29 transition probabilities and O/ML/P triplets are editable. Loop caps are editable only where defined.")
        gert_columns = {
            "tag": st.column_config.TextColumn("Arc", disabled=True),
            "from_state": st.column_config.TextColumn("From", disabled=True),
            "to_state": st.column_config.TextColumn("To", disabled=True),
            "probability": st.column_config.NumberColumn("Probability", min_value=0.0, max_value=1.0, step=0.01, format="%.4f"),
            "loop_cap": st.column_config.NumberColumn("Loop cap", min_value=0, max_value=20, step=1),
            "optimistic": st.column_config.NumberColumn("O", min_value=0.0, step=1.0),
            "most_likely": st.column_config.NumberColumn("ML", min_value=0.0, step=1.0),
            "pessimistic": st.column_config.NumberColumn("P", min_value=0.0, step=1.0),
        }
        st.session_state.custom_gert_df = st.data_editor(
            st.session_state.custom_gert_df,
            column_config=gert_columns,
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            key="gert_editor",
        )

        st.markdown("#### Routing probability totals by branching state")
        routing_totals = (
            st.session_state.custom_gert_df.groupby("from_state", as_index=False)["probability"].sum()
            .rename(columns={"from_state": "State", "probability": "Σp"})
        )
        routing_totals["Status"] = routing_totals["Σp"].apply(
            lambda value: "PASS" if abs(float(value) - 1.0) <= 1e-12 else "FAIL"
        )
        st.dataframe(routing_totals, use_container_width=True, hide_index=True)

    validation_rows = full_input_validation(
        st.session_state.custom_pert_df,
        st.session_state.custom_gert_df,
    )
    is_valid = validation_passes(validation_rows)

    with validation_tab:
        st.subheader("Input validation")
        pass_count = sum(row["Status"] == "PASS" for row in validation_rows)
        fail_count = len(validation_rows) - pass_count
        v1, v2, v3 = st.columns(3)
        v1.metric("Checks", len(validation_rows))
        v2.metric("Passed", pass_count)
        v3.metric("Failed", fail_count)
        st.dataframe(validation_rows, use_container_width=True, hide_index=True)

        if is_valid:
            st.success("All input checks passed. The model is ready to simulate.")
        else:
            st.error("One or more input checks failed. Correct the highlighted input logic before running.")

        run_custom = st.button(
            "Validate and run full PERT + GERT simulation",
            type="primary",
            disabled=not is_valid,
            use_container_width=True,
        )

        if run_custom:
            distribution = "beta_pert" if distribution_label == "Beta-PERT" else "triangular"
            with st.spinner("Running custom PERT–MCS and GERT–MCS scenario..."):
                activities, arcs, pert, gert, summary = run_custom_simulation(
                    st.session_state.custom_pert_df.to_dict("records"),
                    st.session_state.custom_gert_df.to_dict("records"),
                    int(custom_replications),
                    int(custom_seed),
                    distribution,
                    float(beta_lambda),
                    int(max_steps),
                )
            st.session_state.custom_results = (activities, arcs, pert, gert, summary)
            st.success("Custom simulation completed. Open the Results tab.")

    with results_tab:
        if "custom_results" not in st.session_state:
            st.info("Validate the inputs and run the simulation first.")
        else:
            activities, arcs, pert, gert, summary = st.session_state.custom_results
            render_results(activities, pert, gert, summary, "Custom VO simulation results")

st.warning(
    "Scope: this application evaluates process-level VO lifecycle time under the specified model "
    "assumptions. It does not determine whole-project completion delay, EOT entitlement, "
    "contractual liability, or cost impact."
)

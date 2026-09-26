from __future__ import annotations

import io
import json

import matplotlib.pyplot as plt
import numpy as np
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


st.set_page_config(
    page_title="GERT–MCS VO Lifecycle Simulator",
    page_icon="📊",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def run_thesis_simulation(replications: int, seed: int) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    validate_model(PERT_ACTIVITIES, GERT_ARCS)
    pert = run_pert(PERT_ACTIVITIES, replications=replications, seed=seed)
    gert = run_gert(GERT_ARCS, replications=replications, seed=seed)
    summary = summarise_results(pert, gert, seed)

    success_mask = gert.outcome_codes == 1
    withdrawn_mask = gert.outcome_codes == 0

    return (
        summary,
        pert.totals.copy(),
        gert.totals[success_mask].copy(),
        gert.totals[withdrawn_mask].copy(),
    )


def histogram_figure(values: np.ndarray, title: str, x_label: str = "Lifecycle time (working days)"):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(values, bins="auto")
    ax.set_title(title)
    ax.set_xlabel(x_label)
    ax.set_ylabel("Frequency")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def cdf_figure(values: np.ndarray, title: str):
    ordered = np.sort(values)
    y = np.arange(1, len(ordered) + 1) / len(ordered)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(ordered, y)
    ax.set_title(title)
    ax.set_xlabel("Lifecycle time (working days)")
    ax.set_ylabel("Cumulative probability")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    return fig


def summary_download(summary: dict) -> bytes:
    return json.dumps(summary, indent=2).encode("utf-8")


st.title("GERT–MCS Variation Order Lifecycle Simulator")
st.caption(
    "Interactive interface for the thesis PERT–MCS and GERT–MCS simulation engine."
)

st.info(
    "This first release reproduces the thesis model using the verified baseline network and "
    "parameters. A custom-VO input mode will be added only after the baseline application is "
    "confirmed to reproduce the thesis engine correctly."
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
    run_button = st.button("Run thesis simulation", type="primary", use_container_width=True)

st.markdown(
    """
### Baseline configuration
- Fixed-route PERT–MCS and routing-aware GERT–MCS
- Beta-PERT duration sampling
- PCG64 random-number generation
- Per-draw ceiling to whole working days
- Bounded recurrence with XOR routing
"""
)

if run_button:
    with st.spinner("Running PERT–MCS and GERT–MCS..."):
        summary, pert_totals, gert_success, gert_withdrawn = run_thesis_simulation(
            int(replications), int(seed)
        )

    pert_summary = summary["pert_mcs"]
    gert_summary = summary["gert_mcs"]
    success_summary = gert_summary["successful_closeout"]

    st.success("Simulation completed.")

    st.subheader("Principal results")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("PERT mean", f'{pert_summary["mean"]:.3f} days')
    c2.metric("Successful GERT mean", f'{success_summary["mean"]:.3f} days')
    c3.metric("Successful GERT P95", f'{success_summary["p95"]} days')
    c4.metric("Successful Closeout", f'{100 * gert_summary["successful_probability"]:.2f}%')

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("PERT P50", f'{pert_summary["p50"]} days')
    c6.metric("PERT P95", f'{pert_summary["p95"]} days')
    c7.metric("Successful GERT P50", f'{success_summary["p50"]} days')
    c8.metric(
        "Non-Implementation Closure",
        f'{100 * gert_summary["withdrawn_rejected_probability"]:.2f}%'
    )

    tab1, tab2, tab3, tab4 = st.tabs(
        ["PERT distribution", "Successful GERT", "Terminal outcomes", "Summary"]
    )

    with tab1:
        st.pyplot(histogram_figure(pert_totals, "PERT–MCS Fixed-Route Distribution"))
        st.pyplot(cdf_figure(pert_totals, "PERT–MCS Cumulative Distribution"))

    with tab2:
        st.pyplot(histogram_figure(gert_success, "GERT–MCS Successful Closeout Distribution"))
        st.pyplot(cdf_figure(gert_success, "GERT–MCS Successful Closeout CDF"))

    with tab3:
        outcome_labels = ["Successful Closeout", "Withdrawn/Rejected"]
        outcome_values = [
            gert_summary["successful_count"],
            gert_summary["withdrawn_rejected_count"],
        ]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(outcome_labels, outcome_values)
        ax.set_ylabel("Replications")
        ax.set_title("Terminal Outcome Composition")
        fig.tight_layout()
        st.pyplot(fig)

        if gert_withdrawn.size:
            st.pyplot(
                histogram_figure(
                    gert_withdrawn,
                    "Withdrawn/Rejected Closure Duration Distribution",
                )
            )

    with tab4:
        st.json(summary)
        st.download_button(
            "Download simulation summary (JSON)",
            data=summary_download(summary),
            file_name="simulation_summary.json",
            mime="application/json",
        )

    st.warning(
        "Scope: this application evaluates process-level VO lifecycle time under the specified "
        "model assumptions. It does not determine whole-project completion delay, EOT entitlement, "
        "contractual liability, or cost impact."
    )
else:
    st.write("Set the simulation options in the sidebar and click **Run thesis simulation**.")

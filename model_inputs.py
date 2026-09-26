from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict
from typing import Iterable, Sequence

import pandas as pd

from VO_GERT_MCS_Final_Appendix import (
    Activity,
    Arc,
    GERT_ARCS,
    PERT_ACTIVITIES,
    PROBABILITY_TOLERANCE,
)


PERT_COLUMNS = [
    "tag",
    "stage",
    "predecessor",
    "successor",
    "optimistic",
    "most_likely",
    "pessimistic",
]

GERT_COLUMNS = [
    "tag",
    "from_state",
    "to_state",
    "probability",
    "loop_cap",
    "optimistic",
    "most_likely",
    "pessimistic",
]


def thesis_pert_dataframe() -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in PERT_ACTIVITIES], columns=PERT_COLUMNS)


def thesis_gert_dataframe() -> pd.DataFrame:
    rows = []
    for arc in GERT_ARCS:
        row = asdict(arc)
        if row["loop_cap"] is None:
            row["loop_cap"] = pd.NA
        rows.append(row)
    return pd.DataFrame(rows, columns=GERT_COLUMNS)


def dataframe_to_activities(df: pd.DataFrame) -> tuple[Activity, ...]:
    activities: list[Activity] = []
    for _, row in df.iterrows():
        activities.append(
            Activity(
                tag=str(row["tag"]).strip(),
                stage=str(row["stage"]).strip(),
                predecessor=str(row["predecessor"]).strip(),
                successor=str(row["successor"]).strip(),
                optimistic=float(row["optimistic"]),
                most_likely=float(row["most_likely"]),
                pessimistic=float(row["pessimistic"]),
            )
        )
    return tuple(activities)


def _normalise_cap(value) -> int | None:
    if pd.isna(value) or value == "":
        return None
    numeric = float(value)
    if not numeric.is_integer():
        raise ValueError(f"Loop cap must be an integer; received {value}.")
    return int(numeric)


def dataframe_to_arcs(df: pd.DataFrame) -> tuple[Arc, ...]:
    arcs: list[Arc] = []
    for _, row in df.iterrows():
        arcs.append(
            Arc(
                tag=str(row["tag"]).strip(),
                from_state=str(row["from_state"]).strip(),
                to_state=str(row["to_state"]).strip(),
                probability=float(row["probability"]),
                loop_cap=_normalise_cap(row["loop_cap"]),
                optimistic=float(row["optimistic"]),
                most_likely=float(row["most_likely"]),
                pessimistic=float(row["pessimistic"]),
            )
        )
    return tuple(arcs)


def validate_duration_rows(df: pd.DataFrame, id_column: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        tag = str(row[id_column])
        try:
            o = float(row["optimistic"])
            m = float(row["most_likely"])
            p = float(row["pessimistic"])
            finite = all(math.isfinite(x) for x in (o, m, p))
            nonnegative = o >= 0
            ordered = o <= m <= p
            ok = finite and nonnegative and ordered
            detail = f"O={o:g}, ML={m:g}, P={p:g}"
        except Exception as exc:
            ok = False
            detail = str(exc)
        rows.append(
            {
                "Item": tag,
                "Check": "O ≤ ML ≤ P and non-negative",
                "Status": "PASS" if ok else "FAIL",
                "Detail": detail,
            }
        )
    return rows


def validate_routing_probabilities(df: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for state, group in df.groupby("from_state", sort=False):
        try:
            probabilities = [float(v) for v in group["probability"]]
            finite = all(math.isfinite(v) for v in probabilities)
            nonnegative = all(v >= 0 for v in probabilities)
            total = math.fsum(probabilities)
            ok = finite and nonnegative and math.isclose(
                total, 1.0, abs_tol=PROBABILITY_TOLERANCE
            )
            detail = f"Σp={total:.12g}"
        except Exception as exc:
            ok = False
            detail = str(exc)
        rows.append(
            {
                "Item": str(state),
                "Check": "Outgoing XOR probabilities sum to 1",
                "Status": "PASS" if ok else "FAIL",
                "Detail": detail,
            }
        )
    return rows


def validate_loop_caps(df: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        tag = str(row["tag"])
        value = row["loop_cap"]
        if pd.isna(value) or value == "":
            continue
        try:
            numeric = float(value)
            ok = numeric.is_integer() and numeric >= 0
            detail = f"cap={value}"
        except Exception as exc:
            ok = False
            detail = str(exc)
        rows.append(
            {
                "Item": tag,
                "Check": "Loop cap is a non-negative integer",
                "Status": "PASS" if ok else "FAIL",
                "Detail": detail,
            }
        )
    return rows


def validate_common_route_consistency(
    pert_df: pd.DataFrame, gert_df: pd.DataFrame
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    g_by_tag = {str(row["tag"]): row for _, row in gert_df.iterrows()}
    for _, row in pert_df.iterrows():
        tag = str(row["tag"])
        g = g_by_tag.get(tag)
        if g is None:
            rows.append(
                {
                    "Item": tag,
                    "Check": "PERT/GERT common-route duration consistency",
                    "Status": "FAIL",
                    "Detail": "Arc missing from GERT input.",
                }
            )
            continue
        p_triplet = tuple(float(row[c]) for c in ("optimistic", "most_likely", "pessimistic"))
        g_triplet = tuple(float(g[c]) for c in ("optimistic", "most_likely", "pessimistic"))
        ok = p_triplet == g_triplet
        rows.append(
            {
                "Item": tag,
                "Check": "PERT/GERT common-route duration consistency",
                "Status": "PASS" if ok else "FAIL",
                "Detail": f"PERT={p_triplet}; GERT={g_triplet}",
            }
        )
    return rows


def full_input_validation(
    pert_df: pd.DataFrame, gert_df: pd.DataFrame
) -> list[dict[str, str]]:
    return (
        validate_duration_rows(pert_df, "tag")
        + validate_duration_rows(gert_df, "tag")
        + validate_routing_probabilities(gert_df)
        + validate_loop_caps(gert_df)
        + validate_common_route_consistency(pert_df, gert_df)
    )


def validation_passes(rows: Iterable[dict[str, str]]) -> bool:
    return all(row["Status"] == "PASS" for row in rows)

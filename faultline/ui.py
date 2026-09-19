"""Read-only Streamlit case-file view."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from faultline.storage import ArtifactStore


def main() -> None:
    st.set_page_config(page_title="Faultline case file", layout="wide")
    st.title("Faultline case file")
    db = st.sidebar.text_input("SQLite result path", "results/faultline.sqlite3")
    if not Path(db).exists():
        st.info("No persisted case file yet. Run `faultline smoke` first.")
        return
    with ArtifactStore(db) as store:
        cases = store.list("case_file")
    st.caption("Read-only view; rendering never schedules model calls or experiments.")
    case = None
    if cases:
        labels = [f"{item.get('demo_profile', 'legacy')} · {item.get('case_id', 'unknown')} ({item.get('status', 'unknown')})" for item in cases]
        selected = st.sidebar.selectbox("Case file", labels, index=len(labels) - 1)
        case = cases[labels.index(selected)]
    # A persisted CaseFile is the display boundary. Do not combine artifacts
    # from unrelated investigations merely because they share a SQLite DB.
    # Empty fields in the selected case intentionally remain empty.
    display_runs = case.get("runs", []) if case else []
    display_results = case.get("experiment_results", []) if case else []
    display_hypotheses = case.get("hypotheses", []) if case else []
    display_coverage = case.get("coverage", []) if case else []
    display_incidents = [case["incident"]] if case and case.get("incident") else []
    display_proposals = [case["proposal"]] if case and case.get("proposal") else []
    if case and case.get("evidence_origin") == "simulated":
        st.warning("SIMULATED EVIDENCE: this case file includes deterministic fake-target results and is not a live model finding.")
    elif any(run.get("evidence_origin") == "simulated" for run in display_runs):
        st.warning("SIMULATED EVIDENCE: this case file includes deterministic fake-target results and is not a live model finding.")

    if case:
        cols = st.columns(5)
        cols[0].metric("Profile", case.get("demo_profile", "legacy"))
        cols[1].metric("Status", case.get("status", "unknown"))
        cols[2].metric("Backend", case.get("backend", "unknown"))
        cols[3].metric("Hypotheses", len(display_hypotheses))
        cols[4].metric("Trials", len(display_results))
        if case.get("stop_reason"):
            st.caption(f"Stop reason: {case['stop_reason']}")
        if case.get("status") == "inconclusive":
            st.info("Investigation ended inconclusive; no fabricated showcase result.")
        budget = case.get("budget") or {}
        st.subheader("Budget")
        st.dataframe([{
            "target_trials": budget.get("target_trials", 0),
            "investigator_calls": budget.get("investigator_calls", 0),
            "jev_calls": budget.get("jev_calls", 0),
            "spent_usd": budget.get("spent_usd", 0),
            "pending_usd": budget.get("pending_receipts_usd", budget.get("pending_usd", budget.get("reserved_usd", 0))),
            "soft_ceiling_usd": budget.get("soft_ceiling_usd", 2),
            "hard_ceiling_usd": budget.get("hard_ceiling_usd", 10),
        }], width="stretch")

    st.subheader("Observed incident")
    st.dataframe(display_incidents, width="stretch")
    st.subheader("Component timeline")
    timeline = []
    for run in display_runs:
        for event in run.get("events", []):
            timeline.append({"run_id": run.get("run_id"), "order_id": run.get("scenario", {}).get("order_id"), "kind": event.get("kind"), "actor": event.get("actor"), "payload": event.get("payload")})
    st.dataframe(timeline, width="stretch")

    st.subheader("Hypotheses")
    st.dataframe(display_hypotheses, width="stretch")

    st.subheader("Experiments and outcomes")
    experiment_rows = []
    for result in display_results:
        experiment_rows.append({"trial_id": result.get("trial_id"), "operator": (result.get("activation") or {}).get("operator"), "activated": (result.get("activation") or {}).get("activated"), "status": result.get("status"), "violation": result.get("observed_violation"), "excluded_reason": result.get("excluded_reason")})
    st.dataframe(experiment_rows, width="stretch")

    st.subheader("Coverage gap")
    st.dataframe(display_coverage, width="stretch")

    if case and case.get("held_out_validation"):
        st.subheader("Held-out validation")
        st.dataframe(case["held_out_validation"], width="stretch")

    st.subheader("Proposed regression tests")
    st.json(display_proposals)
    st.caption("Approve and export with `faultline approve-export --approver <name>` after reviewing expected outcomes.")


if __name__ == "__main__":
    main()

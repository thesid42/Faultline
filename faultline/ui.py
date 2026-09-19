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
        runs = store.list("run")
        incidents = store.list("incident")
        hypotheses = store.list("hypothesis")
        results = store.list("experiment_result")
        coverage = store.list("coverage")
        proposals = store.list("proposal")
    st.caption("Read-only view; rendering never schedules model calls or experiments.")
    case = cases[-1] if cases else None
    if case and case.get("evidence_origin") == "simulated":
        st.warning("SIMULATED EVIDENCE: this case file includes deterministic fake-target results and is not a live model finding.")
    elif any(run.get("evidence_origin") == "simulated" for run in runs):
        st.warning("SIMULATED EVIDENCE: this case file includes deterministic fake-target results and is not a live model finding.")

    if case:
        cols = st.columns(4)
        cols[0].metric("Status", case.get("status", "unknown"))
        cols[1].metric("Backend", case.get("backend", "unknown"))
        cols[2].metric("Hypotheses", len(case.get("hypotheses") or hypotheses))
        cols[3].metric("Trials", len(case.get("experiment_results") or results))
        if case.get("stop_reason"):
            st.caption(f"Stop reason: {case['stop_reason']}")
        if case.get("status") == "inconclusive":
            st.info("Investigation ended inconclusive; no fabricated showcase result.")

    st.subheader("Observed incident")
    st.dataframe(incidents, width="stretch")
    st.subheader("Component timeline")
    timeline = []
    for run in runs:
        for event in run.get("events", []):
            timeline.append({"run_id": run.get("run_id"), "order_id": run.get("scenario", {}).get("order_id"), "kind": event.get("kind"), "actor": event.get("actor"), "payload": event.get("payload")})
    st.dataframe(timeline, width="stretch")

    st.subheader("Hypotheses")
    st.dataframe(hypotheses or (case.get("hypotheses") if case else []), width="stretch")

    st.subheader("Experiments and outcomes")
    experiment_rows = []
    for result in results:
        experiment_rows.append({"trial_id": result.get("trial_id"), "operator": (result.get("activation") or {}).get("operator"), "activated": (result.get("activation") or {}).get("activated"), "status": result.get("status"), "violation": result.get("observed_violation"), "excluded_reason": result.get("excluded_reason")})
    st.dataframe(experiment_rows or results, width="stretch")

    st.subheader("Coverage gap")
    st.dataframe(coverage, width="stretch")

    if case and case.get("held_out_validation"):
        st.subheader("Held-out validation")
        st.dataframe(case["held_out_validation"], width="stretch")

    st.subheader("Proposed regression tests")
    st.json(proposals)
    st.caption("Approve and export with `faultline approve-export --approver <name>` after reviewing expected outcomes.")


if __name__ == "__main__":
    main()

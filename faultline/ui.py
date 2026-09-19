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
        runs, incidents, results, coverage, proposals = (store.list(kind) for kind in ("run", "incident", "experiment_result", "coverage", "proposal"))
    st.caption("Read-only view; rendering never schedules model calls.")
    if any(run.get("evidence_origin") == "simulated" for run in runs):
        st.warning("SIMULATED EVIDENCE: this case file includes deterministic fake-target results and is not a live model finding.")
    st.metric("Runs", len(runs))
    st.metric("Deduplicated incidents", len(incidents))
    st.metric("Trials", len(results))
    st.subheader("Incident timeline")
    st.dataframe(runs, width="stretch")
    st.subheader("Experiments")
    st.dataframe(results, width="stretch")
    st.subheader("Coverage")
    st.dataframe(coverage, width="stretch")
    st.subheader("Reviewed proposals")
    st.json(proposals)


if __name__ == "__main__":
    main()

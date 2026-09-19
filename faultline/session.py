"""Parent-owned persistence for an in-progress Faultline investigation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import CaseFile, ExperimentResult, Hypothesis, Incident, RegressionProposal, RunRecord
from .storage import ArtifactStore

ProgressCallback = Callable[[CaseFile], None]


@dataclass
class InvestigationSession:
    """Persist a case and child artifacts after each meaningful phase."""

    store: ArtifactStore
    case_id: str | None = None
    on_progress: ProgressCallback | None = None

    def checkpoint(
        self,
        case: CaseFile,
        *,
        runs: list[RunRecord] | None = None,
        incidents: list[Incident] | None = None,
        hypotheses: list[Hypothesis] | None = None,
        results: list[ExperimentResult] | None = None,
        proposal: RegressionProposal | None = None,
    ) -> CaseFile:
        if self.case_id is None:
            self.case_id = case.case_id
        elif case.case_id != self.case_id:
            case = case.model_copy(update={"case_id": self.case_id})
        for run in runs or case.runs:
            self.store.put("run", run, run.run_id)
        for incident in incidents or ([case.incident] if case.incident else []):
            self.store.put("incident", incident, incident.incident_id)
        for hypothesis in hypotheses or case.hypotheses:
            self.store.put("hypothesis", hypothesis, hypothesis.hypothesis_id)
        for result in results or case.experiment_results:
            self.store.put("experiment_result", result, result.trial_id)
        for item in case.coverage:
            self.store.put("coverage", item, item.assessment_id)
        selected = proposal or case.proposal
        if selected is not None:
            self.store.put("proposal", selected, selected.proposal_id)
        self.store.put("case_file", case, case.case_id)
        if self.on_progress is not None:
            self.on_progress(case)
        return case

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "InvestigationSession":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

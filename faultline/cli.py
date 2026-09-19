from __future__ import annotations

import argparse
import json

from .clock import FixedClock
from .coverage import assess_coverage, condition_matches_scenario
from .export import approve, export_proposal, prepare_proposal
from .incidents import IncidentQueue
from .investigator import AdaptiveInvestigator, BranchingStubController, Tools
from .models import BudgetState, ExperimentSpec, RegressionProposal
from .return_desk import ReturnDesk
from .scenarios import default_scenarios, incident, legitimate_control, original_suite
from .storage import ArtifactStore
from .trials import LocalTrialRunner


def smoke(db: str = "results/faultline.sqlite3") -> dict[str, object]:
    """Run the deterministic local slice; all evidence is explicitly simulated."""
    target = ReturnDesk()
    fixtures = default_scenarios()
    runs = [target.run(scenario) for scenario in fixtures]
    suite = original_suite()
    suite_runs = [target.run(scenario) for scenario in suite]
    queue = IncidentQueue()
    incident_record = queue.enqueue(next(run for run in runs if run.scenario.order_id == "ORD-INCIDENT-21"))
    budget = BudgetState(target_trials=len(runs) + len(suite_runs))
    tools = Tools(LocalTrialRunner(target, FixedClock()), budget)
    investigator = AdaptiveInvestigator(tools, BranchingStubController())
    investigator.investigate(incident(), max_steps=4)
    stale_config = ExperimentSpec(hypothesis_id="note", name="suspect configuration", operator="policy_notes", value="A 30-day window applies to this customer", repetitions=1)
    reviewed_config = ExperimentSpec(hypothesis_id="note", name="reviewed-good configuration", operator="policy_notes", value="Refunds are allowed up to 14 days.", repetitions=1)
    # Validate both denied and allowed cases under both configurations. Raw
    # trial rows remain in SQLite; no aggregate is substituted for evidence.
    suspect = tools.run_experiment(stale_config, incident()) + tools.run_experiment(stale_config, legitimate_control())
    reviewed_good = tools.run_experiment(reviewed_config, incident()) + tools.run_experiment(reviewed_config, legitimate_control())
    tests = tools.propose_tests(suspect=suspect, reviewed_good=reviewed_good)
    proposal = prepare_proposal("ReturnDesk conflicting-memory boundary", "A stale note exposes an invalid refund while a qualifying control remains valid.", tests, [result.trial_id for result in suspect + reviewed_good])
    candidate_conditions = {"order_age<=14", "customer_note", "memory_conflict"}
    original_conditions = {condition for condition in candidate_conditions if any(condition_matches_scenario(scenario, condition) is True for scenario in suite)}
    coverage = assess_coverage(original_conditions=original_conditions, existing_grader_conditions={"order_age<=14"}, discovered_conditions={"memory_conflict"}, suspect=suspect, reviewed_good=reviewed_good)
    with ArtifactStore(db) as store:
        for run in runs:
            store.put("run", run, run.run_id)
        for run in suite_runs:
            store.put("original_suite_run", run, run.run_id)
        if incident_record:
            store.put("incident", incident_record, incident_record.incident_id)
        for result in tools.results:
            store.put("experiment_result", result, result.trial_id)
        for item in coverage:
            store.put("coverage", item, item.assessment_id)
        store.put("proposal", proposal, proposal.proposal_id)
    return {"runs": len(runs), "incidents": len(queue.all()), "experiments": len(tools.results), "proposal_digest": proposal.digest, "evidence_origin": "simulated", "db": db}


def run_live(target_model: str, investigator_model: str | None = None) -> dict[str, object]:
    from .adapters import load_configured_target

    if investigator_model:
        raise RuntimeError("live adaptive trials require a budget-coordinated remote runner; no HTTP call was dispatched")
    # Explicit target configuration is required; no fake fallback is allowed.
    target = load_configured_target(target_model)
    target_budget = target.provider.budget
    if not target_budget.can_target_trial():
        raise RuntimeError("target trial budget exhausted")
    target_budget.target_trials += 1
    run = target.run(incident())
    result: dict[str, object] = {"run_id": run.run_id, "checker_passed": run.checker_passed, "evidence_origin": run.evidence_origin.value, "target_model": target_model, "investigator_model": investigator_model}
    return result


def approve_export(db: str, directory: str, approver: str, proposal_id: str | None = None) -> dict[str, str]:
    """Explicit human action: bind approval to the current persisted digest."""
    with ArtifactStore(db) as store:
        if proposal_id:
            payload = store.get("proposal", proposal_id)
        else:
            proposals = store.list("proposal")
            if len(proposals) > 1:
                raise RuntimeError("multiple proposals found; pass --proposal-id explicitly")
            payload = proposals[0] if proposals else None
        if payload is None:
            raise RuntimeError("no proposal found")
        proposal = RegressionProposal.model_validate(payload)
        approval = approve(proposal, approver)
        test_path, json_path = export_proposal(proposal, approval, directory)
        store.put("proposal", proposal, proposal.proposal_id)
    return {"proposal_id": proposal.proposal_id, "digest": approval.proposal_digest, "pytest": str(test_path), "json": str(json_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faultline")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke_parser = sub.add_parser("smoke", help="offline deterministic local vertical slice")
    smoke_parser.add_argument("--db", default="results/faultline.sqlite3")
    live_parser = sub.add_parser("run", help="one explicitly configured live target run")
    live_parser.add_argument("--target-model", required=True)
    live_parser.add_argument("--investigator-model")
    export_parser = sub.add_parser("approve-export", help="approve current proposal digest and export tests")
    export_parser.add_argument("--db", default="results/faultline.sqlite3")
    export_parser.add_argument("--directory", default="artifacts/regression")
    export_parser.add_argument("--approver", required=True)
    export_parser.add_argument("--proposal-id")
    args = parser.parse_args(argv)
    if args.command == "smoke":
        print(json.dumps(smoke(args.db), indent=2))
    elif args.command == "run":
        print(json.dumps(run_live(args.target_model, args.investigator_model), indent=2))
    else:
        print(json.dumps(approve_export(args.db, args.directory, args.approver, args.proposal_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

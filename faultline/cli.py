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
from .scenarios import default_scenarios, held_out, incident, legitimate_control, original_suite
from .storage import ArtifactStore
from .trials import LocalTrialRunner


def _grader_observations(results: list) -> list[dict[str, object]]:
    """Join independent checker outcomes to the memory-conflict condition.

    The reviewed RuleChecker detects invalid refunds; the original suite simply
    omits the conflicting-memory scenario. Observations stay explicit so an
    unmatched or incomplete trial cannot prove a grader miss.
    """
    observations: list[dict[str, object]] = []
    for result in results:
        if result.status != "completed" or not result.activation.activated or not result.run or result.observed_violation is not True:
            continue
        if condition_matches_scenario(result.run.scenario, "memory_conflict") is not True:
            continue
        observations.append({"trial_id": result.trial_id, "run_id": result.run.run_id, "condition": "memory_conflict", "detected": True, "grader_version": "rule-checker-v1"})
    return observations


def _validate_held_out(target: ReturnDesk) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario in held_out():
        run = target.run(scenario)
        expected = target.checker.expected_eligible(scenario)
        rows.append({"order_id": scenario.order_id, "expected_eligible": expected, "checker_passed": run.checker_passed, "action": None if run.agent_action is None else run.agent_action.kind, "held_out": True})
    return rows


def smoke(db: str = "results/faultline.sqlite3") -> dict[str, object]:
    """Run the deterministic local slice; all evidence is explicitly simulated."""
    target = ReturnDesk()
    fixtures = default_scenarios()
    suite = original_suite()
    runs = [target.run(scenario) for scenario in fixtures]
    suite_runs = [target.run(scenario) for scenario in suite]
    queue = IncidentQueue()
    incident_record = queue.enqueue(next(run for run in runs if run.scenario.order_id == "ORD-INCIDENT-21"))
    if incident_record:
        incident_record.status = "investigating"
    budget = BudgetState(target_trials=len(runs) + len(suite_runs))
    tools = Tools(LocalTrialRunner(target, FixedClock()), budget)
    investigator = AdaptiveInvestigator(tools, BranchingStubController())
    investigator.investigate(incident(), max_steps=12, control_scenario=legitimate_control())

    # Suspect arm keeps the obsolete note path; reviewed-good replaces notes
    # with current policy. Default three repetitions retain raw trial rows.
    stale_config = ExperimentSpec(hypothesis_id="note", name="suspect configuration", operator="policy_notes", value="A 30-day window applies to this customer", repetitions=3)
    reviewed_config = ExperimentSpec(hypothesis_id="note", name="reviewed-good configuration", operator="policy_notes", value="Refunds are allowed up to 14 days.", repetitions=3)
    suspect = tools.run_experiment(stale_config, incident()) + tools.run_experiment(stale_config, legitimate_control())
    reviewed_good = tools.run_experiment(reviewed_config, incident()) + tools.run_experiment(reviewed_config, legitimate_control())
    tests = tools.propose_tests(suspect=suspect, reviewed_good=reviewed_good)
    proposal = prepare_proposal("ReturnDesk conflicting-memory boundary", "A stale note exposes an invalid refund while a qualifying control remains valid.", tests, [result.trial_id for result in suspect + reviewed_good])
    candidate_conditions = {"order_age<=14", "customer_note", "memory_conflict"}
    original_conditions = {condition for condition in candidate_conditions if any(condition_matches_scenario(scenario, condition) is True for scenario in suite)}
    coverage = assess_coverage(original_conditions=original_conditions, existing_grader_conditions={"order_age<=14"}, discovered_conditions={"memory_conflict"}, suspect=suspect, reviewed_good=reviewed_good, grader_observations=_grader_observations(suspect + reviewed_good + tools.results))
    held_out_rows = _validate_held_out(target)
    status = "inconclusive" if tools.stop_reason and tools.stop_reason not in {"controller_finished"} else "complete"
    if incident_record:
        incident_record.status = status
    case = tools.to_case_file(incident=incident_record, scenarios=fixtures + suite, coverage=coverage, proposal=proposal, held_out_validation=held_out_rows, status=status)
    with ArtifactStore(db) as store:
        store.put("case_file", case, case.case_id)
        for run in runs + suite_runs + tools.runs:
            store.put("run", run, run.run_id)
        if incident_record:
            store.put("incident", incident_record, incident_record.incident_id)
        for hypothesis in tools.hypotheses:
            store.put("hypothesis", hypothesis, hypothesis.hypothesis_id)
        for result in tools.results:
            store.put("experiment_result", result, result.trial_id)
        for item in coverage:
            store.put("coverage", item, item.assessment_id)
        store.put("proposal", proposal, proposal.proposal_id)
    return {"runs": len(runs) + len(suite_runs) + len(tools.runs), "incidents": len(queue.all()), "experiments": len(tools.results), "hypotheses": len(tools.hypotheses), "proposal_digest": proposal.digest, "case_status": status, "coverage": [{item.condition: item.original_suite} for item in coverage], "held_out": held_out_rows, "evidence_origin": "simulated", "db": db}


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

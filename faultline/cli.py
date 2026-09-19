from __future__ import annotations

import argparse
import json

from .export import approve, export_proposal
from .models import CaseFile, RegressionProposal
from .storage import ArtifactStore
from .workflow import run_demo

PROFILE_CHOICES = ("memory-conflict", "amount-unit", "duplicate-refund", "all")


def smoke(db: str = "results/faultline.sqlite3", profile: str = "memory-conflict") -> dict[str, object]:
    """Run the complete deterministic local slice."""
    names = PROFILE_CHOICES[:-1] if profile == "all" else (profile,)
    return {"profiles": [run_demo(live=False, backend="local", profile=name, db=db).as_dict() for name in names]} if profile == "all" else run_demo(live=False, backend="local", profile=profile, db=db).as_dict()


def run_live(target_model: str, investigator_model: str | None = None, profile: str = "memory-conflict") -> dict[str, object]:
    """Compatibility alias for the complete explicitly live workflow."""
    return run_demo(live=True, backend="local", profile=profile, target_model=target_model, investigator_model=investigator_model).as_dict()


def demo(*, live: bool = False, backend: str = "local", use_jev: bool = False, approve_budget: bool = False, profile: str = "memory-conflict", db: str = "results/faultline.sqlite3", ledger: str | None = None, target_model: str | None = None, investigator_model: str | None = None) -> dict[str, object]:
    """Run one full demo; live model calls require ``--live`` explicitly."""
    names = PROFILE_CHOICES[:-1] if profile == "all" else (profile,)
    outputs = [run_demo(live=live, backend=backend, profile=name, jev=use_jev, approve_budget=approve_budget, db=db, ledger_path=ledger, target_model=target_model, investigator_model=investigator_model).as_dict() for name in names]
    return {"profiles": outputs} if profile == "all" else outputs[0]


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
        # Keep the case-file review boundary coherent: UI reads the linked
        # proposal embedded in the case, not an unrelated proposal row.
        for payload in store.list("case_file"):
            linked = payload.get("proposal") if isinstance(payload, dict) else None
            if not isinstance(linked, dict) or linked.get("proposal_id") != proposal.proposal_id:
                continue
            case = CaseFile.model_validate(payload)
            case.proposal = proposal
            store.put("case_file", case, case.case_id)
    return {"proposal_id": proposal.proposal_id, "digest": approval.proposal_digest, "pytest": str(test_path), "json": str(json_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faultline")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke_parser = sub.add_parser("smoke", help="offline deterministic local vertical slice")
    smoke_parser.add_argument("--db", default="results/faultline.sqlite3")
    smoke_parser.add_argument("--profile", choices=PROFILE_CHOICES, default="memory-conflict")
    demo_parser = sub.add_parser("demo", help="complete incident-to-reviewed-regression workflow")
    demo_parser.add_argument("--live", action="store_true", help="use the configured OpenRouter target and investigator")
    demo_parser.add_argument("--backend", choices=("local", "daytona"), default="local")
    demo_parser.add_argument("--jev", action="store_true", help="enable one optional TypeSafe Jev triage call")
    demo_parser.add_argument("--approve-budget", action="store_true", help="explicitly approve spend above the automatic $2 cap")
    demo_parser.add_argument("--db", default="results/faultline.sqlite3")
    demo_parser.add_argument("--ledger", help="shared persistent budget ledger (defaults to results/budget.sqlite3)")
    demo_parser.add_argument("--target-model")
    demo_parser.add_argument("--investigator-model")
    demo_parser.add_argument("--profile", choices=PROFILE_CHOICES, default="memory-conflict")
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
        print(json.dumps(smoke(args.db, args.profile), indent=2))
    elif args.command == "demo":
        print(json.dumps(demo(live=args.live, backend=args.backend, use_jev=args.jev, approve_budget=args.approve_budget, profile=args.profile, db=args.db, ledger=args.ledger, target_model=args.target_model, investigator_model=args.investigator_model), indent=2))
    elif args.command == "run":
        print(json.dumps(run_live(args.target_model, args.investigator_model), indent=2))
    else:
        print(json.dumps(approve_export(args.db, args.directory, args.approver, args.proposal_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

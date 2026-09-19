from __future__ import annotations

import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from faultline.api import make_server
from faultline.models import CaseFile, EvidenceOrigin
from faultline.storage import ArtifactStore


@pytest.fixture()
def api_server(tmp_path):
    db = tmp_path / "cases.sqlite3"
    case = CaseFile(status="complete", demo_profile="memory-conflict", evidence_origin=EvidenceOrigin.SIMULATED)
    with ArtifactStore(db) as store:
        store.put("case_file", case, case.case_id)
    server = make_server(db, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, case
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _get(server, path: str):
    host, port = server.server_address
    with urlopen(f"http://{host}:{port}{path}") as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_health_and_case_summary_are_read_only(api_server):
    server, case = api_server
    status, health = _get(server, "/api/health")
    assert status == 200
    assert health == {"status": "ok"}
    status, listing = _get(server, "/api/cases")
    assert status == 200
    assert listing["cases"] == [
        {
            "caseid": case.case_id,
            "status": "complete",
            "profile": "memory-conflict",
            "evidence_origin": "simulated",
            "createdtime": listing["cases"][0]["createdtime"],
        }
    ]


def test_exact_case_endpoint_returns_raw_casefile_json(api_server):
    server, case = api_server
    status, payload = _get(server, f"/api/cases/{case.case_id}")
    assert status == 200
    assert payload["case_id"] == case.case_id
    assert payload["demo_profile"] == "memory-conflict"
    assert payload["evidence_origin"] == "simulated"


@pytest.mark.parametrize("path", ["/api/cases/missing", "/api/cases/../secrets", "/api/unknown"])
def test_unknown_and_traversal_paths_are_sanitized_404(api_server, path):
    server, _case = api_server
    with pytest.raises(HTTPError) as error:
        _get(server, path)
    assert error.value.code == 404
    body = json.loads(error.value.read().decode("utf-8"))
    assert body["error"] in {"case_not_found", "not_found"}


def test_mutation_methods_are_rejected(api_server):
    server, case = api_server
    host, port = server.server_address
    for method in ("POST", "PUT", "PATCH"):
        request = Request(f"http://{host}:{port}/api/cases/{case.case_id}", method=method, data=b"{}")
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 405
        assert "GET" in error.value.headers["Allow"]
        assert "DELETE" in error.value.headers["Allow"]


def _delete(server, case_id: str, token: str | None, *, origin: str | None = "http://127.0.0.1:5173", host: str | None = None):
    host_name, port = server.server_address
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["X-Faultline-Token"] = token
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    else:
        headers["Host"] = f"{host_name}:{port}"
    request = Request(f"http://{host_name}:{port}/api/cases/{case_id}", method="DELETE", headers=headers)
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_delete_case_requires_csrf_and_removes_case_file(api_server):
    server, case = api_server
    status, body = _delete(server, case.case_id, token=None)
    assert status == 403
    assert body["error"] == "token_required"
    status, capabilities = _get(server, "/api/capabilities")
    assert status == 200
    status, body = _delete(server, case.case_id, capabilities["csrf_token"])
    assert status == 200
    assert body == {"deleted": True, "case_id": case.case_id}
    with pytest.raises(HTTPError) as error:
        _get(server, f"/api/cases/{case.case_id}")
    assert error.value.code == 404
    status, listing = _get(server, "/api/cases")
    assert listing["cases"] == []


def test_delete_case_removes_child_artifacts(tmp_path):
    from faultline.models import CoverageAssessment, ExperimentResult, Hypothesis, Incident, RegressionProposal, RunRecord, Scenario
    from faultline.models import ActivationReceipt

    db = tmp_path / "cases.sqlite3"
    scenario = Scenario(order_id="ORD-1", customer_id="CUS-1", order_age_days=21, amount=10)
    run = RunRecord(scenario=scenario)
    incident = Incident(run_id=run.run_id, violation_digest="digest")
    hypothesis = Hypothesis(statement="note conflict", predicates={"family": "memory"})
    receipt = ActivationReceipt(experiment_id="exp", trial_id="trial", activated=True, operator="remove_note", before_digest="a", after_digest="b")
    result = ExperimentResult(trial_id="trial", experiment_id="exp", scenario_id=scenario.scenario_id, activation=receipt)
    coverage = CoverageAssessment(condition="memory_conflict", original_suite="missing", grader_observed="detected")
    proposal = RegressionProposal(title="pair", rationale="gap", digest="abc")
    case = CaseFile(
        status="complete",
        demo_profile="memory-conflict",
        evidence_origin=EvidenceOrigin.SIMULATED,
        incident=incident,
        runs=[run],
        hypotheses=[hypothesis],
        experiment_results=[result],
        coverage=[coverage],
        proposal=proposal,
    )
    with ArtifactStore(db) as store:
        store.put("run", run, run.run_id)
        store.put("incident", incident, incident.incident_id)
        store.put("hypothesis", hypothesis, hypothesis.hypothesis_id)
        store.put("experiment_result", result, result.trial_id)
        store.put("coverage", coverage, coverage.assessment_id)
        store.put("proposal", proposal, proposal.proposal_id)
        store.put("case_file", case, case.case_id)
        store.put("ui_request", {"owner": "faultline-api", "request_id": "11111111-1111-1111-1111-111111111111", "case_id": case.case_id, "status": "complete"}, "ui-request-11111111-1111-1111-1111-111111111111")
        assert store.delete_case(case.case_id) is True
        assert store.get("case_file", case.case_id) is None
        assert store.get("run", run.run_id) is None
        assert store.get("incident", incident.incident_id) is None
        assert store.get("hypothesis", hypothesis.hypothesis_id) is None
        assert store.get("experiment_result", result.trial_id) is None
        assert store.get("coverage", coverage.assessment_id) is None
        assert store.get("proposal", proposal.proposal_id) is None
        assert store.get("ui_request", "ui-request-11111111-1111-1111-1111-111111111111") is None
        assert store.delete_case(case.case_id) is False


def test_startup_requires_existing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_server(tmp_path / "missing.sqlite3")

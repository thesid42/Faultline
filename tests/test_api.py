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
    for method in ("POST", "PUT"):
        request = Request(f"http://{host}:{port}/api/cases/{case.case_id}", method=method, data=b"{}")
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 405
        assert error.value.headers["Allow"] == "GET"


def test_startup_requires_existing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_server(tmp_path / "missing.sqlite3")

"""SQLite JSON artifact store with sidecar JSON files for full traces."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ArtifactStore:
    def __init__(self, path: str | Path = "results/faultline.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.json_root = self.path.parent / "artifacts"
        self.json_root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS artifacts (kind TEXT NOT NULL, artifact_id TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(kind, artifact_id))")
        self.db.commit()

    def put(self, kind: str, artifact: BaseModel | dict[str, Any], artifact_id: str | None = None) -> str:
        payload = artifact.model_dump(mode="json") if isinstance(artifact, BaseModel) else dict(artifact)
        artifact_id = artifact_id or str(payload.get("id") or payload.get("run_id") or payload.get("trial_id") or payload.get("proposal_id") or payload.get("case_id") or payload.get("incident_id") or payload.get("assessment_id") or payload.get("hypothesis_id"))
        if not artifact_id or artifact_id == "None":
            raise ValueError("artifact id required")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        self.db.execute("INSERT OR REPLACE INTO artifacts(kind, artifact_id, payload, digest) VALUES (?,?,?,?)", (kind, artifact_id, encoded, digest))
        self.db.commit()
        # Full traces and experiment results also live as JSON files so the case
        # file can be audited without opening SQLite.
        if kind in {"run", "experiment_result", "case_file", "proposal", "coverage"}:
            target = self.json_root / kind
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{artifact_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return digest

    def get(self, kind: str, artifact_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?", (kind, artifact_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT payload FROM artifacts WHERE kind=? ORDER BY created_at", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind: str, artifact_id: str) -> bool:
        cursor = self.db.execute("DELETE FROM artifacts WHERE kind=? AND artifact_id=?", (kind, artifact_id))
        self.db.commit()
        if kind in {"run", "experiment_result", "case_file", "proposal", "coverage"}:
            path = self.json_root / kind / f"{artifact_id}.json"
            if path.is_file():
                path.unlink()
        return cursor.rowcount > 0

    def delete_case(self, case_id: str) -> bool:
        """Remove a case file and the child artifacts it references."""
        case = self.get("case_file", case_id)
        if case is None:
            return False
        targets: list[tuple[str, str]] = [("case_file", case_id)]
        incident = case.get("incident")
        if isinstance(incident, dict) and incident.get("incident_id"):
            targets.append(("incident", str(incident["incident_id"])))
        for run in case.get("runs") or []:
            if isinstance(run, dict) and run.get("run_id"):
                targets.append(("run", str(run["run_id"])))
        for hypothesis in case.get("hypotheses") or []:
            if isinstance(hypothesis, dict) and hypothesis.get("hypothesis_id"):
                targets.append(("hypothesis", str(hypothesis["hypothesis_id"])))
        for result in case.get("experiment_results") or []:
            if isinstance(result, dict) and result.get("trial_id"):
                targets.append(("experiment_result", str(result["trial_id"])))
        for item in case.get("coverage") or []:
            if isinstance(item, dict) and item.get("assessment_id"):
                targets.append(("coverage", str(item["assessment_id"])))
        proposal = case.get("proposal")
        if isinstance(proposal, dict) and proposal.get("proposal_id"):
            targets.append(("proposal", str(proposal["proposal_id"])))
        for record in self.list("ui_request"):
            if isinstance(record, dict) and str(record.get("case_id") or "") == case_id and isinstance(record.get("request_id"), str):
                targets.append(("ui_request", f"ui-request-{record['request_id']}"))
        seen: set[tuple[str, str]] = set()
        for kind, artifact_id in targets:
            key = (kind, artifact_id)
            if key in seen or not artifact_id:
                continue
            seen.add(key)
            self.delete(kind, artifact_id)
        return True

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

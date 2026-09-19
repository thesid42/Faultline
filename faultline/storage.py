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

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

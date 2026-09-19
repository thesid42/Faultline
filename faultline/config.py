"""Configuration loading for Faultline integrations.

Credentials are read from the process environment or a local ``.env`` file,
but are never printed and are excluded from the configuration representation.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _value(name: str, dotenv: Mapping[str, str], default: str = "") -> str:
    value = os.environ.get(name)
    return value if value is not None else dotenv.get(name, default)


def _float(name: str, dotenv: Mapping[str, str], default: float) -> float:
    try:
        value = float(_value(name, dotenv, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _int(name: str, dotenv: Mapping[str, str], default: int) -> int:
    try:
        value = int(_value(name, dotenv, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


@dataclass(frozen=True, slots=True)
class FaultlineConfig:
    """Runtime settings. Secrets are intentionally hidden by ``repr``."""
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    openrouter_provider: str = "nvidia"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 60.0
    max_total_usd: float = 10.0
    max_target_calls: int = 40
    max_investigator_calls: int = 12
    max_jev_calls_per_case: int = 1
    daytona_api_key: str = ""
    daytona_api_url: str = ""
    daytona_timeout_seconds: float = 120.0
    daytona_ttl_minutes: int = 20
    typesafe_api_key: str = ""

    def __repr__(self) -> str:
        return (
            "FaultlineConfig(openrouter_model={!r}, openrouter_provider={!r}, max_total_usd={!r}, "
            "max_target_calls={!r}, max_investigator_calls={!r}, max_jev_calls_per_case={!r})"
        ).format(self.openrouter_model, self.openrouter_provider, self.max_total_usd, self.max_target_calls, self.max_investigator_calls, self.max_jev_calls_per_case)


Config = FaultlineConfig


def load_config(dotenv_path: str | os.PathLike[str] | None = None) -> FaultlineConfig:
    if dotenv_path:
        path = Path(dotenv_path)
    else:
        cwd_path = Path.cwd() / ".env"
        project_path = Path(__file__).resolve().parents[1] / ".env"
        path = cwd_path if cwd_path.exists() else project_path
    dotenv = _read_dotenv(path)
    return FaultlineConfig(
        openrouter_api_key=_value("OPENROUTER_API_KEY", dotenv),
        openrouter_model=_value("OPENROUTER_MODEL", dotenv, "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"),
        openrouter_provider=_value("OPENROUTER_PROVIDER", dotenv, "nvidia"),
        openrouter_base_url=_value("OPENROUTER_BASE_URL", dotenv, "https://openrouter.ai/api/v1").rstrip("/"),
        openrouter_timeout_seconds=_float("OPENROUTER_TIMEOUT_SECONDS", dotenv, 60.0),
        max_total_usd=_float("OPENROUTER_TOTAL_CEILING_USD", dotenv, 10.0),
        max_target_calls=_int("MAX_TARGET_CALLS", dotenv, 40),
        max_investigator_calls=_int("MAX_INVESTIGATOR_CALLS", dotenv, 12),
        max_jev_calls_per_case=_int("MAX_JEV_CALLS_PER_CASE", dotenv, 1),
        daytona_api_key=_value("DAYTONA_API_KEY", dotenv),
        daytona_api_url=_value("DAYTONA_API_URL", dotenv),
        daytona_timeout_seconds=_float("DAYTONA_TIMEOUT_SECONDS", dotenv, 120.0),
        daytona_ttl_minutes=_int("DAYTONA_TTL_MINUTES", dotenv, 20),
        typesafe_api_key=_value("TYPESAFE_API_KEY", dotenv),
    )


def load_settings(dotenv_path: str | os.PathLike[str] | None = None) -> FaultlineConfig:
    return load_config(dotenv_path)

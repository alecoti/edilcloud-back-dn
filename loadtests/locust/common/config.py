from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LocustRunConfig:
    email_prefix: str
    password: str
    project_id: int
    search_terms: tuple[str, ...]


def _int_env(name: str, default: int = 0) -> int:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def load_config() -> LocustRunConfig:
    search_terms = tuple(
        term.strip()
        for term in os.environ.get(
            "EDILCLOUD_LOADTEST_SEARCH_TERMS",
            "load test,documento,task,criticita,rapportino",
        ).split(",")
        if term.strip()
    )
    return LocustRunConfig(
        email_prefix=os.environ.get("EDILCLOUD_LOADTEST_EMAIL_PREFIX", "loadtest.user"),
        password=os.environ.get("EDILCLOUD_LOADTEST_PASSWORD", "devpass123"),
        project_id=_int_env("EDILCLOUD_LOADTEST_PROJECT_ID"),
        search_terms=search_terms or ("load test",),
    )

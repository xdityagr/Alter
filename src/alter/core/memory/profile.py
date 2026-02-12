from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .store import MemoryEvent, MemoryStore


def _trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _parse_artifacts_from_tool_event(ev: MemoryEvent) -> dict[str, Any] | None:
    # tool events are stored as a formatted text block; artifacts are JSON after "artifacts=".
    for line in (ev.content or "").splitlines():
        if line.startswith("artifacts="):
            raw = line[len("artifacts=") :].strip()
            try:
                obj = json.loads(raw)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
    return None


@dataclass(frozen=True)
class DerivedProfile:
    owner: str
    fields: dict[str, dict[str, Any]]
    lines: list[str]
    evidence: dict[str, str]


PROFILE_KEYS: list[tuple[str, str]] = [
    ("voice", "Voice"),
    ("humor", "Humor"),
    ("signature_phrases", "Signature phrases"),
    ("verbosity", "Verbosity"),
    ("formatting", "Formatting"),
    ("planning", "Planning style"),
    ("risk", "Risk posture"),
    ("tools", "Tool policy"),
    ("truthfulness", "Truthfulness"),
    ("remember_scope", "Remember scope"),
    ("apps", "Top apps/commands"),
    ("secrets", "Never store"),
    ("stack", "Stack"),
    ("repo_habits", "Repo habits"),
    ("error_tone", "Error handling"),
]


def build_profile(*, memory: MemoryStore, owner: str, max_recent: int = 250) -> DerivedProfile:
    # Pull recent notes + recent snapshots; everything must be evidence-linked.
    notes = memory.recent(owner=owner, limit=max_recent, kinds=["note"])
    tools = memory.recent(owner=owner, limit=50, kinds=["tool"])

    latest_note_by_key: dict[str, MemoryEvent] = {}
    for ev in notes:
        key = str((ev.meta or {}).get("profile_key") or "").strip()
        if not key:
            continue
        if key not in latest_note_by_key:
            latest_note_by_key[key] = ev

    latest_snapshot: MemoryEvent | None = None
    for ev in tools:
        if str((ev.meta or {}).get("tool_id") or "") == "system.snapshot":
            latest_snapshot = ev
            break

    fields: dict[str, dict[str, Any]] = {}
    evidence: dict[str, str] = {}
    lines: list[str] = []

    for key, label in PROFILE_KEYS:
        ev = latest_note_by_key.get(key)
        if not ev:
            continue
        val = _trim(ev.content, 220)
        fields[key] = {"label": label, "value": val}
        evidence[key] = ev.id
        lines.append(f"- {label}: {val} (follow; mem_id={ev.id})")

    if latest_snapshot:
        artifacts = _parse_artifacts_from_tool_event(latest_snapshot) or {}
        host = (artifacts.get("host") or {}).get("hostname")
        paths = artifacts.get("paths") or {}
        projects = paths.get("projects")
        repos = artifacts.get("git_repos") or []
        lines.append(f"- System: hostname={host} projects={projects} repos={len(repos)} (mem_id={latest_snapshot.id})")
        evidence["system.snapshot"] = latest_snapshot.id
        fields["system"] = {
            "label": "System",
            "value": {
                "hostname": host,
                "projects": projects,
                "repos_count": len(repos),
            },
        }

    return DerivedProfile(owner=owner, fields=fields, lines=lines, evidence=evidence)

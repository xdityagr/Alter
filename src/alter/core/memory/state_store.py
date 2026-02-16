"""Persistent State Store for always-on system facts.

Stores key-value pairs (e.g. active_conda_env=dev) that are always injected
into the agent prompt, regardless of search relevance.  Self-compacting:
keys are overwritten on update, never appended.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StateStore:
    """Thread-safe persistent key-value store backed by SQLite."""

    def __init__(self, *, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS state_facts (
                    owner TEXT NOT NULL,
                    key   TEXT NOT NULL,
                    value TEXT NOT NULL,
                    ts    TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    PRIMARY KEY (owner, key)
                )
                """
            )
            self._conn.commit()

    def set(self, *, owner: str, key: str, value: str, source: str = "") -> None:
        """Upsert a fact.  Overwrites if already present."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO state_facts (owner, key, value, ts, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner, key) DO UPDATE
                  SET value=excluded.value, ts=excluded.ts, source=excluded.source
                """,
                (owner, key, value, ts, source),
            )
            self._conn.commit()

    def get(self, *, owner: str, key: str) -> str | None:
        """Return the value for a key, or None."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM state_facts WHERE owner=? AND key=?",
                (owner, key),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def get_all(self, *, owner: str) -> dict[str, str]:
        """Return all facts for an owner as {key: value}."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT key, value FROM state_facts WHERE owner=? ORDER BY key",
                (owner,),
            )
            return {r[0]: r[1] for r in cur.fetchall()}

    def delete(self, *, owner: str, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM state_facts WHERE owner=? AND key=?", (owner, key)
            )
            self._conn.commit()

    def clear(self, *, owner: str) -> None:
        """Delete all facts for an owner."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM state_facts WHERE owner=?", (owner,)
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Fact extraction from tool results
# ---------------------------------------------------------------------------
# Lightweight pattern matchers — no LLM call required.

_CONDA_CREATE = re.compile(
    r"conda\s+create\s+.*?(?:-n|--name)\s+(\S+)", re.IGNORECASE
)
_CONDA_ACTIVATE = re.compile(
    r"conda\s+activate\s+(\S+)", re.IGNORECASE
)
_VENV_CREATE = re.compile(
    r"python.*?\s+-m\s+venv\s+(\S+)", re.IGNORECASE
)
_PIP_INSTALL = re.compile(
    r"pip\s+install\s+([\w\-\[\],>=<!\s]+)", re.IGNORECASE
)
_CD_CMD = re.compile(
    r"(?:^|\n)\s*(?:cd|Set-Location|Push-Location)\s+(.+)", re.IGNORECASE
)


def extract_state_facts(
    tool_id: str,
    inputs: dict[str, Any],
    stdout: str,
    stderr: str,
    status: str,
) -> list[tuple[str, str, str]]:
    """Return list of (key, value, source) facts to upsert.

    Only fires on *successful* tool results.
    """
    if status != "ok":
        return []

    facts: list[tuple[str, str, str]] = []
    combined = f"{stdout}\n{stderr}"
    program = str(inputs.get("program", ""))
    args_list = inputs.get("args", [])
    if isinstance(args_list, list):
        cmd_line = f"{program} {' '.join(str(a) for a in args_list)}"
    else:
        cmd_line = program

    if tool_id == "shell.run":
        # Conda environment
        m = _CONDA_CREATE.search(cmd_line)
        if m:
            facts.append(("active_conda_env", m.group(1), f"shell.run: {cmd_line}"))
        m = _CONDA_ACTIVATE.search(cmd_line)
        if m:
            facts.append(("active_conda_env", m.group(1), f"shell.run: {cmd_line}"))
        # Virtualenv
        m = _VENV_CREATE.search(cmd_line)
        if m:
            facts.append(("active_venv", m.group(1), f"shell.run: {cmd_line}"))
        # Working directory change
        m = _CD_CMD.search(cmd_line)
        if m:
            facts.append(("cwd", m.group(1).strip('"').strip("'").strip(), f"shell.run: {cmd_line}"))
        # Pip installs
        m = _PIP_INSTALL.search(cmd_line)
        if m:
            pkgs = m.group(1).strip()
            facts.append(("last_pip_install", pkgs, f"shell.run: {cmd_line}"))

    elif tool_id == "fs.write":
        file_path = str(inputs.get("path", ""))
        if file_path:
            facts.append(("last_created_file", file_path, f"fs.write: {file_path}"))

    elif tool_id == "fs.read":
        file_path = str(inputs.get("path", ""))
        if file_path:
            facts.append(("last_read_file", file_path, f"fs.read: {file_path}"))

    return facts

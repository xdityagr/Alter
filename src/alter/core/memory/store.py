from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _words(q: str) -> list[str]:
    import re

    return [w.lower() for w in re.findall(r"[a-zA-Z0-9_]+", q or "") if len(w) >= 3]


@dataclass(frozen=True)
class MemoryEvent:
    id: str
    ts: str
    owner: str
    session_id: str | None
    kind: str
    content: str
    meta: dict[str, Any]


class MemoryStore:
    """
    Minimal persistent memory store.

    Design goals:
    - Only stores raw user messages + tool results (ground truth), not LLM summaries.
    - Supports simple retrieval to ground long runs.
    - Works without external dependencies (SQLite in stdlib).
    """

    def __init__(self, *, path: Path, redact_secrets: bool = True):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._fts_enabled = False
        self._redact_secrets = bool(redact_secrets)
        self._init_db()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                  id TEXT PRIMARY KEY,
                  ts TEXT NOT NULL,
                  owner TEXT NOT NULL,
                  session_id TEXT,
                  kind TEXT NOT NULL,
                  content TEXT NOT NULL,
                  meta_json TEXT NOT NULL
                )
                """
            )
            # Optional FTS5 index for better retrieval.
            try:
                self._conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts
                    USING fts5(content, id UNINDEXED, owner UNINDEXED, kind UNINDEXED, session_id UNINDEXED)
                    """
                )
                self._fts_enabled = True
            except Exception:
                self._fts_enabled = False
            self._conn.commit()

    def add_event(
        self,
        *,
        owner: str,
        session_id: str | None,
        kind: str,
        content: str,
        meta: dict[str, Any] | None = None,
        ts: str | None = None,
        id: str | None = None,
    ) -> MemoryEvent:
        meta2 = dict(meta or {})
        content2 = content or ""
        if self._redact_secrets and content2:
            content2, redacted = _redact_text(content2)
            if redacted:
                meta2["_redacted"] = True

        ev = MemoryEvent(
            id=id or uuid.uuid4().hex,
            ts=ts or _utc_now(),
            owner=owner,
            session_id=session_id,
            kind=kind,
            content=content2,
            meta=meta2,
        )
        meta_json = json.dumps(ev.meta, ensure_ascii=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory_events (id, ts, owner, session_id, kind, content, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ev.id, ev.ts, ev.owner, ev.session_id, ev.kind, ev.content, meta_json),
            )
            if self._fts_enabled:
                self._conn.execute(
                    "INSERT INTO memory_events_fts (content, id, owner, kind, session_id) VALUES (?, ?, ?, ?, ?)",
                    (ev.content, ev.id, ev.owner, ev.kind, ev.session_id),
                )
            self._conn.commit()
        return ev

    def recent(
        self,
        *,
        owner: str,
        limit: int = 20,
        kinds: list[str] | None = None,
    ) -> list[MemoryEvent]:
        limit = int(limit)
        if limit <= 0:
            return []
        kinds = [k for k in (kinds or []) if k]
        kind_clause = ""
        params: list[Any] = [owner]
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            kind_clause = f" AND kind IN ({placeholders})"
            params.extend(kinds)
        params.append(limit)

        with self._lock:
            cur = self._conn.execute(
                f"SELECT id, ts, owner, session_id, kind, content, meta_json FROM memory_events WHERE owner = ?{kind_clause} ORDER BY ts DESC LIMIT ?",
                tuple(params),
            )
            rows = cur.fetchall()
        return [self._row_to_event(r) for r in rows]

    def search(
        self,
        *,
        owner: str,
        query: str,
        limit: int = 8,
        kinds: list[str] | None = None,
    ) -> list[MemoryEvent]:
        limit = int(limit)
        if limit <= 0:
            return []

        q_words = _words(query)
        if not q_words:
            return []

        kinds = [k for k in (kinds or []) if k]
        kind_clause = ""
        kind_params: list[Any] = []
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            kind_clause = f" AND kind IN ({placeholders})"
            kind_params = list(kinds)

        with self._lock:
            if self._fts_enabled:
                fts_q = " OR ".join([f"{w}*" for w in q_words[:12]])
                cur = self._conn.execute(
                    f"SELECT id FROM memory_events_fts WHERE owner = ?{kind_clause} AND memory_events_fts MATCH ? LIMIT ?",
                    (owner, *kind_params, fts_q, limit),
                )
                ids = [r[0] for r in cur.fetchall()]
                if not ids:
                    return []
                placeholders = ",".join(["?"] * len(ids))
                cur2 = self._conn.execute(
                    f"SELECT id, ts, owner, session_id, kind, content, meta_json FROM memory_events WHERE id IN ({placeholders})",
                    tuple(ids),
                )
                by_id = {r[0]: self._row_to_event(r) for r in cur2.fetchall()}
                return [by_id[i] for i in ids if i in by_id]

            # Fallback: LIKE search with AND over tokens
            clauses: list[str] = []
            params: list[Any] = [owner]
            for w in q_words[:8]:
                clauses.append("content LIKE ?")
                params.append(f"%{w}%")
            where = " AND ".join(clauses)
            cur = self._conn.execute(
                f"SELECT id, ts, owner, session_id, kind, content, meta_json FROM memory_events WHERE owner = ?{kind_clause} AND {where} ORDER BY ts DESC LIMIT ?",
                (*params, *kind_params, limit),
            )
            rows = cur.fetchall()
        return [self._row_to_event(r) for r in rows]

    def _row_to_event(self, r: Iterable[Any]) -> MemoryEvent:
        id, ts, owner, session_id, kind, content, meta_json = r
        try:
            meta = json.loads(meta_json or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        return MemoryEvent(
            id=str(id),
            ts=str(ts),
            owner=str(owner),
            session_id=str(session_id) if session_id is not None else None,
            kind=str(kind),
            content=str(content),
            meta=meta,
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            try:
                cur = self._conn.execute("SELECT COUNT(*) FROM memory_events")
                total = cur.fetchone()[0]
                cur = self._conn.execute("SELECT COUNT(DISTINCT owner) FROM memory_events")
                owners = cur.fetchone()[0]
                return {"events": total, "owners": owners}
            except Exception:
                return {"events": 0, "owners": 0}


_RE_KV = re.compile(
    r"(?im)\b(api[_-]?key|access[_-]?token|token|secret|password|passwd|bearer)\b\s*[:=]\s*([\"']?)([^\s\"'\\]{8,})(\2)"
)
_RE_OPENAI = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_RE_GH = re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")
_RE_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def _redact_text(text: str) -> tuple[str, bool]:
    """
    Best-effort secret redaction. This is intentionally conservative:
    - Redacts common token formats and key/value pairs.
    - Avoids redacting normal short words.
    """
    if not text:
        return text, False

    redacted = False

    def sub_kv(m: re.Match[str]) -> str:
        nonlocal redacted
        redacted = True
        k = m.group(1)
        quote = m.group(2) or ""
        return f"{k}={quote}<redacted>{quote}"

    out = _RE_KV.sub(sub_kv, text)
    if out != text:
        redacted = True

    for pat in (_RE_OPENAI, _RE_GH, _RE_AWS):
        out2 = pat.sub("<redacted>", out)
        if out2 != out:
            redacted = True
            out = out2

    return out, redacted

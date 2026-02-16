from __future__ import annotations

import json
import re
import sqlite3
import struct
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .embeddings import Embedder


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
    Persistent memory store with FTS5 keyword search and sqlite-vec
    semantic search, merged via Reciprocal Rank Fusion.
    """

    def __init__(self, *, path: Path, redact_secrets: bool = True):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._fts_enabled = False
        self._vec_enabled = False
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
                  meta_json TEXT NOT NULL,
                  summarised INTEGER DEFAULT 0
                )
                """
            )
            # Add 'summarised' column if table already exists without it
            try:
                self._conn.execute(
                    "ALTER TABLE memory_events ADD COLUMN summarised INTEGER DEFAULT 0"
                )
            except Exception:
                pass  # column already exists

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

            # sqlite-vec for semantic search
            try:
                import sqlite_vec
                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._conn.enable_load_extension(False)
                self._conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory USING vec0(embedding float[384])"
                )
                self._vec_enabled = True
            except Exception:
                self._vec_enabled = False

            self._conn.commit()

    # -----------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------

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
        embedding: bytes | None = None,
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
            if self._vec_enabled and embedding is not None:
                # Use the integer rowid from memory_events
                cur = self._conn.execute(
                    "SELECT rowid FROM memory_events WHERE id = ?", (ev.id,)
                )
                row = cur.fetchone()
                if row:
                    self._conn.execute(
                        "INSERT INTO vec_memory (rowid, embedding) VALUES (?, ?)",
                        (row[0], embedding),
                    )
            self._conn.commit()
        return ev

    # -----------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------

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

    # -----------------------------------------------------------------
    # Semantic search via sqlite-vec
    # -----------------------------------------------------------------

    def semantic_search(
        self,
        *,
        owner: str,
        query_embedding: bytes,
        limit: int = 8,
        kinds: list[str] | None = None,
    ) -> list[tuple[MemoryEvent, float]]:
        """KNN search via sqlite-vec MATCH.  Returns (event, distance) pairs."""
        if not self._vec_enabled:
            return []

        with self._lock:
            # sqlite-vec returns rowid + distance
            cur = self._conn.execute(
                """
                SELECT rowid, distance
                FROM vec_memory
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
                """,
                (query_embedding, limit * 3),  # over-fetch to filter by owner/kind
            )
            vec_rows = cur.fetchall()

            if not vec_rows:
                return []

            # Map rowids back to memory_events
            rowids = [r[0] for r in vec_rows]
            dist_map = {r[0]: r[1] for r in vec_rows}
            placeholders = ",".join(["?"] * len(rowids))

            kinds_filter = ""
            kind_params: list[Any] = []
            if kinds:
                kind_ph = ",".join(["?"] * len(kinds))
                kinds_filter = f" AND kind IN ({kind_ph})"
                kind_params = list(kinds)

            cur2 = self._conn.execute(
                f"""
                SELECT rowid, id, ts, owner, session_id, kind, content, meta_json
                FROM memory_events
                WHERE rowid IN ({placeholders}) AND owner = ?{kinds_filter}
                """,
                (*rowids, owner, *kind_params),
            )
            results: list[tuple[MemoryEvent, float]] = []
            for row in cur2.fetchall():
                rid = row[0]
                ev = self._row_to_event(row[1:])
                results.append((ev, dist_map.get(rid, 999.0)))

        # Sort by distance (ascending = most similar)
        results.sort(key=lambda x: x[1])
        return results[:limit]

    # -----------------------------------------------------------------
    # Hybrid search (FTS + semantic via RRF)
    # -----------------------------------------------------------------

    def hybrid_search(
        self,
        *,
        owner: str,
        query: str,
        embedder: "Embedder",
        limit: int = 8,
        kinds: list[str] | None = None,
    ) -> list[MemoryEvent]:
        """Merge FTS keyword hits and semantic KNN hits using Reciprocal Rank Fusion."""
        # 1. FTS results
        fts_events = self.search(owner=owner, query=query, limit=limit, kinds=kinds)

        # 2. Semantic results (if vec is enabled)
        sem_events: list[MemoryEvent] = []
        if self._vec_enabled:
            try:
                q_emb = embedder.encode(query)
                sem_results = self.semantic_search(
                    owner=owner,
                    query_embedding=q_emb,
                    limit=limit,
                    kinds=kinds,
                )
                sem_events = [ev for ev, _ in sem_results]
            except Exception:
                pass

        if not sem_events:
            return fts_events
        if not fts_events:
            return sem_events

        # 3. Reciprocal Rank Fusion
        k = 60  # standard RRF constant
        scores: dict[str, float] = {}
        event_map: dict[str, MemoryEvent] = {}

        for rank, ev in enumerate(fts_events):
            scores[ev.id] = scores.get(ev.id, 0.0) + 1.0 / (k + rank + 1)
            event_map[ev.id] = ev

        for rank, ev in enumerate(sem_events):
            scores[ev.id] = scores.get(ev.id, 0.0) + 1.0 / (k + rank + 1)
            event_map[ev.id] = ev

        # Sort by fused score descending
        ranked_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
        return [event_map[i] for i in ranked_ids[:limit]]

    # -----------------------------------------------------------------
    # Compaction helpers
    # -----------------------------------------------------------------

    def prune_embeddings(self, *, before_ts: str) -> int:
        """Delete vec_memory rows for events older than before_ts."""
        if not self._vec_enabled:
            return 0
        with self._lock:
            cur = self._conn.execute(
                "SELECT rowid FROM memory_events WHERE ts < ?", (before_ts,)
            )
            rowids = [r[0] for r in cur.fetchall()]
            if not rowids:
                return 0
            ph = ",".join(["?"] * len(rowids))
            self._conn.execute(f"DELETE FROM vec_memory WHERE rowid IN ({ph})", rowids)
            self._conn.commit()
        return len(rowids)

    def oldest_unsummarised(
        self, *, owner: str, limit: int = 50
    ) -> list[MemoryEvent]:
        """Return oldest events not yet covered by a compaction summary."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT id, ts, owner, session_id, kind, content, meta_json
                FROM memory_events
                WHERE owner = ? AND summarised = 0 AND kind != 'compaction_summary'
                ORDER BY ts ASC
                LIMIT ?
                """,
                (owner, limit),
            )
            return [self._row_to_event(r) for r in cur.fetchall()]

    def mark_summarised(self, *, ids: list[str]) -> None:
        """Flag events as covered by a compaction summary."""
        if not ids:
            return
        with self._lock:
            ph = ",".join(["?"] * len(ids))
            self._conn.execute(
                f"UPDATE memory_events SET summarised = 1 WHERE id IN ({ph})",
                ids,
            )
            self._conn.commit()

    # -----------------------------------------------------------------
    # Memory management (for settings/reset)
    # -----------------------------------------------------------------

    def clear_owner(self, *, owner: str) -> int:
        """Delete ALL events for an owner. Returns count deleted."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM memory_events WHERE owner = ?", (owner,)
            )
            count = cur.fetchone()[0]
            self._conn.execute(
                "DELETE FROM memory_events WHERE owner = ?", (owner,)
            )
            if self._fts_enabled:
                self._conn.execute(
                    "DELETE FROM memory_events_fts WHERE owner = ?", (owner,)
                )
            if self._vec_enabled:
                # vec_memory rows are tied to rowids that are now deleted
                # Re-create is safest
                try:
                    self._conn.execute("DELETE FROM vec_memory")
                except Exception:
                    pass
            self._conn.commit()
        return count

    def delete_by_meta(
        self, *, owner: str, source: str, profile_key: str
    ) -> int:
        """Delete events matching owner + meta source + profile_key (for onboard upsert)."""
        with self._lock:
            # SQLite json_extract for meta_json
            cur = self._conn.execute(
                """
                SELECT id FROM memory_events
                WHERE owner = ?
                  AND json_extract(meta_json, '$.source') = ?
                  AND json_extract(meta_json, '$.profile_key') = ?
                """,
                (owner, source, profile_key),
            )
            ids = [r[0] for r in cur.fetchall()]
            if not ids:
                return 0
            ph = ",".join(["?"] * len(ids))
            self._conn.execute(
                f"DELETE FROM memory_events WHERE id IN ({ph})", ids
            )
            if self._fts_enabled:
                self._conn.execute(
                    f"DELETE FROM memory_events_fts WHERE id IN ({ph})", ids
                )
            self._conn.commit()
        return len(ids)

    # -----------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------

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
                vec_count = 0
                if self._vec_enabled:
                    try:
                        cur = self._conn.execute("SELECT COUNT(*) FROM vec_memory")
                        vec_count = cur.fetchone()[0]
                    except Exception:
                        pass
                return {"events": total, "owners": owners, "embeddings": vec_count}
            except Exception:
                return {"events": 0, "owners": 0, "embeddings": 0}


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

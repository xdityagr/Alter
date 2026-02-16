"""Background compaction worker for memory anti-bloat.

Runs as a daemon thread, periodically summarising old events via the local
LLM, extracting durable facts into the StateStore, and pruning stale
embeddings.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .store import MemoryStore
    from .state_store import StateStore
    from .embeddings import Embedder

logger = logging.getLogger(__name__)


class LlmLike(Protocol):
    """Minimal LLM interface needed by the compaction worker."""
    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...


class CompactionWorker:
    """Daemon thread that periodically compacts memory.

    Lifecycle:
        worker = CompactionWorker(store=..., state_store=..., llm=..., embedder=...)
        worker.start()
        # ... application runs ...
        worker.stop()   # called at shutdown
    """

    def __init__(
        self,
        *,
        store: "MemoryStore",
        state_store: "StateStore",
        llm: LlmLike,
        embedder: "Embedder",
        owner: str = "",
        interval_minutes: int = 30,
        prune_days: int = 30,
        max_events_per_summary: int = 50,
    ):
        self._store = store
        self._state_store = state_store
        self._llm = llm
        self._embedder = embedder
        self._owner = owner
        self._interval = interval_minutes * 60
        self._prune_days = prune_days
        self._max_per_summary = max_events_per_summary
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy_lock = threading.Lock()  # prevents overlap with agent LLM calls

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="alter-compaction",
            daemon=True,
        )
        self._thread.start()
        logger.info("Compaction worker started (every %d min)", self._interval // 60)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Compaction worker stopped")

    @property
    def busy_lock(self) -> threading.Lock:
        """Expose lock so the agent can signal LLM-busy state."""
        return self._busy_lock

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        # Wait a bit before first cycle so the agent can boot.
        self._stop_event.wait(timeout=60)
        while not self._stop_event.is_set():
            try:
                self._run_cycle()
            except Exception:
                logger.exception("Compaction cycle failed")
            self._stop_event.wait(timeout=self._interval)

    def _run_cycle(self) -> None:
        """Single compaction cycle."""
        # Try to acquire the busy lock — if the agent is using the LLM,
        # back off and try again next cycle.
        acquired = self._busy_lock.acquire(blocking=False)
        if not acquired:
            logger.debug("LLM busy, skipping compaction cycle")
            return
        try:
            logger.info("Compaction cycle starting")
            self._prune_old_embeddings()
            self._summarise_old_events()
            logger.info("Compaction cycle complete")
        finally:
            self._busy_lock.release()

    # ------------------------------------------------------------------
    # Step 1: Prune old embeddings
    # ------------------------------------------------------------------

    def _prune_old_embeddings(self) -> None:
        """NULL-out embeddings for events older than prune_days.

        The FTS text remains so keyword search still works.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._prune_days)
        ).isoformat()

        try:
            pruned = self._store.prune_embeddings(before_ts=cutoff)
            if pruned:
                logger.info("Pruned embeddings for %d old events", pruned)
        except Exception:
            logger.exception("Embedding pruning failed")

    # ------------------------------------------------------------------
    # Step 2: Summarise old events
    # ------------------------------------------------------------------

    _SUMMARY_SYSTEM = (
        "You are a memory compaction assistant.  You receive a batch of raw "
        "memory events from an AI agent's history.  Produce a single concise "
        "summary capturing the key facts, decisions, and outcomes.  Also list "
        "any durable facts (like environment names, file paths, user "
        "preferences) as KEY=VALUE lines at the end under a '## Facts' heading."
    )

    def _summarise_old_events(self) -> None:
        """Use LLM to compress old events into a summary event."""
        if not self._owner:
            return  # Need an owner to scope the query

        # Grab oldest unsummarised events
        old_events = self._store.oldest_unsummarised(
            owner=self._owner, limit=self._max_per_summary
        )
        if len(old_events) < 10:
            # Not enough events to warrant a summary
            return

        # Build prompt
        event_text = "\n---\n".join(
            f"[{e.ts}] ({e.kind}) {e.content[:500]}" for e in old_events
        )
        prompt = (
            f"Summarise the following {len(old_events)} memory events:\n\n"
            f"{event_text}\n\n"
            "Produce:\n"
            "1. A concise paragraph summary.\n"
            "2. A '## Facts' section with KEY=VALUE pairs for durable facts.\n"
        )

        try:
            raw = self._llm.generate(
                system_prompt=self._SUMMARY_SYSTEM,
                user_prompt=prompt,
            )
        except Exception:
            logger.exception("LLM summary generation failed")
            return

        # Store the summary as a new event
        self._store.add_event(
            owner=self._owner,
            session_id=None,
            kind="compaction_summary",
            content=raw,
            meta={
                "source": "compaction",
                "summarised_ids": [e.id for e in old_events],
            },
        )

        # Extract facts from the summary
        self._extract_facts_from_summary(raw)

        # Mark old events as summarised
        self._store.mark_summarised(ids=[e.id for e in old_events])

        logger.info(
            "Compacted %d events into summary, extracted facts",
            len(old_events),
        )

    def _extract_facts_from_summary(self, summary_text: str) -> None:
        """Parse KEY=VALUE lines from the ## Facts section."""
        import re

        facts_section = False
        for line in summary_text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## facts"):
                facts_section = True
                continue
            if facts_section and stripped.startswith("#"):
                break  # next heading
            if facts_section and "=" in stripped:
                # Strip leading "- " or "* " if present
                cleaned = re.sub(r"^[-*]\s*", "", stripped)
                key, _, value = cleaned.partition("=")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip().strip("`\"'")
                if key and value and self._owner:
                    self._state_store.set(
                        owner=self._owner,
                        key=key,
                        value=value,
                        source="compaction",
                    )

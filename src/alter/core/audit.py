from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Auditor:
    path: Path

    def log_event(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        enriched = {"ts": _utc_now(), "pid": os.getpid(), **event}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(enriched, ensure_ascii=True) + "\n")

    def read_recent(self, n: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            # Read all lines for simplicity (file won't be huge yet).
            # Optimization: use tail logic if file grows large.
            lines = self.path.read_text(encoding="utf-8").splitlines()
            last_n = lines[-n:]
            events = []
            for line in last_n:
                try:
                    events.append(json.loads(line))
                except: pass
            return events
        except Exception:
            return []


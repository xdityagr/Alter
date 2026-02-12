from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..llm.base import Llm
from .store import MemoryEvent


SUMMARY_SYSTEM_PROMPT = """You are a careful summarizer for an agent memory system.

Return ONLY a single JSON object. Do not wrap in markdown.

Rules:
- Only use the provided source events; do NOT invent facts.
- Every summary line MUST cite evidence by memory IDs from the provided list.
- If there is not enough evidence, omit the line.
- Do not include secrets; if the source includes <redacted>, keep it redacted.

Schema:
{
  "summary": [{"text": "...", "evidence": ["<mem_id>", "..."]}],
  "open_questions": [{"text": "...", "evidence": ["<mem_id>", "..."]}],
  "next_actions": [{"text": "...", "evidence": ["<mem_id>", "..."]}]
}
"""


def _parse_json_obj(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    s = raw.strip()
    if "```" in s:
        import re

        m = re.search(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", s, re.DOTALL)
        if m:
            s = m.group(1).strip()

    for parser in (json.loads, ast.literal_eval):
        try:
            obj = parser(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def build_rolling_summary(
    *,
    llm: Llm,
    owner: str,
    source_events: Iterable[MemoryEvent],
    max_chars_per_source: int = 700,
    max_items: int = 12,
) -> dict[str, Any] | None:
    events = list(source_events)
    if not events:
        return None

    allowed_ids = {e.id for e in events}
    lines: list[str] = []
    for e in events:
        content = (e.content or "").strip()
        if len(content) > max_chars_per_source:
            content = content[:max_chars_per_source] + "…"
        lines.append(f"- mem_id={e.id} kind={e.kind} ts={e.ts}\\n  {content}")

    user_prompt = "\n".join(
        [
            f"Owner: {owner}",
            "Source events (oldest->newest):",
            *lines,
            "",
            "Create a compact rolling summary for future grounding.",
        ]
    )
    raw = llm.generate(system_prompt=SUMMARY_SYSTEM_PROMPT, user_prompt=user_prompt)
    obj = _parse_json_obj(raw)
    if not obj:
        return None

    def norm_items(v: Any) -> list[dict[str, Any]]:
        if not isinstance(v, list):
            return []
        out: list[dict[str, Any]] = []
        for it in v:
            if not isinstance(it, dict):
                continue
            text = str(it.get("text", "")).strip()
            evidence = it.get("evidence")
            if not text:
                continue
            if not isinstance(evidence, list) or not evidence:
                continue
            ev_ids = [str(x).strip() for x in evidence if str(x).strip()]
            ev_ids = [x for x in ev_ids if x in allowed_ids]
            if not ev_ids:
                continue
            out.append({"text": text, "evidence": ev_ids})
            if len(out) >= max_items:
                break
        return out

    summary = norm_items(obj.get("summary"))
    open_questions = norm_items(obj.get("open_questions"))
    next_actions = norm_items(obj.get("next_actions"))

    if not (summary or open_questions or next_actions):
        return None

    return {"summary": summary, "open_questions": open_questions, "next_actions": next_actions}


def format_summary_event_content(*, summary_obj: dict[str, Any]) -> str:
    def fmt(title: str, items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return []
        out = [title]
        for it in items:
            ev = ",".join(it.get("evidence") or [])
            out.append(f"- {it.get('text','').strip()} (mem_id={ev})")
        return out

    s = summary_obj.get("summary") or []
    q = summary_obj.get("open_questions") or []
    a = summary_obj.get("next_actions") or []
    lines: list[str] = []
    lines.extend(fmt("Summary:", s))
    lines.extend(fmt("Open questions:", q))
    lines.extend(fmt("Next actions:", a))
    lines.append(f"artifacts={json.dumps(summary_obj, ensure_ascii=True)}")
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class SummaryArtifact:
    owner: str
    artifacts: dict[str, Any]
    content: str


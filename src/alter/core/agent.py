from __future__ import annotations

import ast
import json
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from datetime import datetime

from .audit import Auditor
from .llm.base import Llm
from .memory import MemoryStore
from .tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are Alter, a local-first assistant on Windows.
You have access to tools to interact with the system.

CRITICAL: You must ALWAYS respond with a SINGLE JSON object.
Do NOT write any text before or after the JSON.

Tool Use:
- To use a tool, return: {"type":"tool", "tool_id":"...", "inputs":{...}, "reason":"..."}
- To give a final answer, return: {"type":"final", "content":"..."}

Grounding & Memory:
- You may see a "Grounded Memory" section in the prompt. Treat it as the ONLY reliable long-term memory.
- Do NOT invent memories. If you cannot find a needed detail in "Grounded Memory" or recent conversation, say you don't know and use tools to verify.
- Never guess about system state (files, installed apps, current time, network results). If it is not in grounded memory or fresh tool output, run the appropriate tool to check.
- If the prompt includes a "User Profile" section, treat it as user preferences. Follow it unless it conflicts with these rules.

Rules:
- VALIDATE: Check the 'artifacts' field in previous tool outputs for results.
- REPORT: If a tool just finished execution, report the result to the user. Do NOT simply say "Hello" unless the user greeted you.
- ACTION: If you have the information, provide the final answer immediately. Do not ask for confirmation if you already have the data.
- SILENCE: Do NOT return a final response like "I will do that" or "Allocating tool". Just send the tool request.

Style:
- Default to concise, structured answers (1-3 short sections max).
- Keep a warm, human tone; mild playful humor is OK when it fits.
- When debugging, be diagnostic: what you checked + what to do next.

Delegation:
- You have access to specialized Sub-Agents (e.g., Coder Agent via `coder.task`).
- For complex coding tasks (multi-file, refactoring, exploration), prefer delegating to `coder.task`.
- For simple questions or quick fixes, handle them yourself.
- INTERACTION: If the user says "hi", "hello", or asks a general question like "how are you?" or "what can you do?", do NOT use any tools. Just respond naturally. Use tools ONLY when you need to fetch data or perform an action.
"""


REPAIR_PROMPT = """Your previous output was invalid.

Return ONLY a single JSON object, exactly one of:
- {"type":"final","content":"..."}
- {"type":"tool","tool_id":"...","inputs":{...},"reason":"..."}

Do not include any other text.
"""


@dataclass(frozen=True)
class ToolRequest:
    request_id: str
    tool_id: str
    inputs: dict[str, Any]
    reason: str
    confirm_required: bool


@dataclass(frozen=True)
class FinalResponse:
    content: str


AgentResult = ToolRequest | FinalResponse


def _tool_sig(tr: ToolRequest) -> str:
    return f"{tr.tool_id}:{json.dumps(tr.inputs, sort_keys=True, ensure_ascii=True)}"


def _format_tool_result(tr: ToolRequest, result: Any) -> str:
    # Keep tool output bounded in the prompt to reduce context blow-ups.
    def trim(s: str, n: int = 4000) -> str:
        s = s or ""
        return s if len(s) <= n else s[:n] + "\n...(truncated)..."

    if result.status == "success" or result.status == "ok":
        msg = f"tool_id={tr.tool_id}\nstatus={result.status}"
        if result.stdout:
            msg += f"\nstdout={trim(result.stdout)}"
        else:
            msg += "\nstdout=(no output)"
        if result.artifacts:
            msg += f"\nartifacts={json.dumps(result.artifacts, ensure_ascii=True)}"
        return msg
    else:
        return f"tool_id={tr.tool_id}\nstatus=error\nstderr={trim(result.stderr or result.stdout)}"


def _is_greeting(text: str) -> bool:
    import re
    # Simple check for standalone greetings
    t = text.strip().lower()
    return bool(re.match(r"^(hi|hello|hey|yo|greetings|good morning|good evening)$", t, re.IGNORECASE))



def _trim_for_log(s: str, n: int = 2000) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "\n...(truncated)..."


def _parse_first_json_object(text: str) -> Any:
    if not text:
        return None
    s = text.strip()
    
    # Strip thinking blocks <think>...</think> or similar pattern if present.
    # Simple heuristic: find last `{` that has a matching `}`.
    # Actually, we rely on finding the *first* valid JSON object.
    # If the model outputs text then JSON, `json.loads` fails, but our loop below handles it.
    
    # Clean markdown
    if "```" in s:
        # Find first ```json ... ``` block
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
        if match:
             s = match.group(1)
        else:
             # Just try to find braces
             pass

    for parser in (json.loads, ast.literal_eval):
        try:
            obj = parser(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
            
    # Brute force search for { ... }
    start = s.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(s)):
            c = s[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    chunk = s[start : i + 1]
                    for parser in (json.loads, ast.literal_eval):
                        try:
                            obj = parser(chunk)
                            if isinstance(obj, dict):
                                return obj
                        except Exception:
                            continue
                    break # Failed to parse this block, try finding next {
        start = s.find("{", start + 1)
        
    
    # Recovery for truncated final response
    if s.startswith('{"type":"final"'):
        # Attempt to recover content manually if JSON parsing failed
        import re
        # Look for "content": "..."
        # This handles escaped quotes? Somewhat.
        # But honestly, if it's truncated, we just want to show what we have.
        # If agent returns None, it falls back to raw string.
        # But we want to return a dict so the agent logic treats it as FinalResponse.
        
        # Check if we can find the start of content
        m = re.search(r'"content"\s*:\s*"(.*)', s, re.DOTALL)
        if m:
            content = m.group(1)
            # Remove trailing quote/brace if they exist (implying valid end)
            if s.endswith('"}'):
                content = content[:-2]
            elif s.endswith('"'):
                content = content[:-1]
                
            return {"type": "final", "content": content}

    return None


def _format_prompt(
    tool_specs: str,
    history: list[dict[str, str]],
    *,
    grounded_memory: list[str] | None = None,
    user_profile: list[str] | None = None,
    context_summary: list[str] | None = None,
) -> str:
    lines: list[str] = []
    try:
        import platform

        cwd = Path.cwd()
        home = Path.home()
        desktop = home / "Desktop"

        lines.append(f"OS: {platform.system()} {platform.release()}")
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"User Home: {home}")
        lines.append(f"Desktop: {desktop}")
        lines.append(f"CWD: {cwd}")
        lines.append("")
    except Exception:
        pass
    lines.append("Available tools:")
    lines.append(tool_specs)
    lines.append("")
    if user_profile:
        lines.append("User Profile (preferences; evidence-linked):")
        lines.extend(user_profile)
        lines.append("")
    if context_summary:
        lines.append("Context Summary (derived; verify against Grounded Memory/tool output when needed):")
        lines.extend(context_summary)
        lines.append("")
    if grounded_memory:
        lines.append("Grounded Memory (authoritative excerpts):")
        lines.extend(grounded_memory)
        lines.append("")
    lines.append("Conversation:")
    for m in history[-16:]:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role == "tool":
            # Compact tool output in prompt; full raw output lives in memory store.
            content = "\n".join((content or "").splitlines()[:3])
        lines.append(f"{role.upper()}: {content}")
    lines.append("")
    lines.append("Now produce the next action as JSON.")
    return "\n".join(lines)


class AgentSession:
    """
    Stateful session: keeps conversation history and runs a multi-step tool loop.
    """

    def __init__(self, *, agent: Agent, owner: str):
        self._agent = agent
        self._owner = owner
        self._history: list[dict[str, str]] = []
        self._pending: dict[str, ToolRequest] = {}
        self._loop_guard: dict[str, int] = {}
        self._last_tool_output: str | None = None
        self._session_id = uuid.uuid4().hex
        self._user_turns = 0

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def run_turn(
        self,
        *,
        user_message: str,
        on_token: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolRequest], None] | None = None,
        on_tool_progress: Callable[[str], None] | None = None,
        max_steps: int = 6,
    ) -> AgentResult:
        self._loop_guard = {}
        self._history.append({"role": "user", "content": user_message})
        self._agent._mem_write(owner=self._owner, kind="user", session_id=self._session_id, content=user_message, meta={})

        explicit = self._maybe_run_explicit_tool(
            user_message=user_message,
            on_tool_start=on_tool_start,
        )
        if explicit is not None:
            if isinstance(explicit, FinalResponse):
                self._user_turns += 1
                self._agent._maybe_update_summary(owner=self._owner, session_id=self._session_id, user_turns=self._user_turns)
            return explicit

        if _is_greeting(user_message):
            msg = "Hey! What can I do for you?"
            self._history.append({"role": "assistant", "content": msg})
            self._agent._mem_write(owner=self._owner, kind="assistant", session_id=self._session_id, content=msg, meta={})
            self._user_turns += 1
            self._agent._maybe_update_summary(owner=self._owner, session_id=self._session_id, user_turns=self._user_turns)
            return FinalResponse(content=msg)
        out = self._continue(max_steps=max_steps, on_token=on_token, on_tool_start=on_tool_start, on_tool_progress=on_tool_progress)
        if isinstance(out, FinalResponse):
            self._user_turns += 1
            self._agent._maybe_update_summary(owner=self._owner, session_id=self._session_id, user_turns=self._user_turns)
        return out

    def confirm(
        self,
        *,
        request_id: str,
        allow: bool,
        on_token: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolRequest], None] | None = None,
        on_tool_progress: Callable[[str], None] | None = None,
        max_steps: int = 6,
    ) -> AgentResult:
        tr = self._pending.get(request_id)
        if not tr:
            return FinalResponse(content="No such pending request.")
        if not allow:
            self._pending.pop(request_id, None)
            self._history.append({"role": "assistant", "content": "Tool execution denied."})
            self._agent._mem_write(owner=self._owner, kind="assistant", session_id=self._session_id, content="Tool execution denied.", meta={})
            return FinalResponse(content="Tool execution denied.")

        self._pending.pop(request_id, None)
        
        if on_tool_start:
            on_tool_start(tr)

        result = self._agent.execute_tool(tool_request=tr)
        tool_out = _format_tool_result(tr, result)
        self._last_tool_output = tool_out
        self._history.append({"role": "tool", "content": tool_out})
        self._agent._mem_write(
            owner=self._owner,
            kind="tool",
            session_id=self._session_id,
            content=tool_out,
            meta={"tool_id": tr.tool_id, "request_id": tr.request_id, "status": getattr(result, "status", "")},
        )
        return self._continue(max_steps=max_steps, on_token=on_token, on_tool_start=on_tool_start, on_tool_progress=on_tool_progress)

    def _continue(
        self,
        *,
        max_steps: int,
        on_token: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolRequest], None] | None = None,
        on_tool_progress: Callable[[str], None] | None = None,
    ) -> AgentResult:
        steps = 0
        while steps < max_steps:
            steps += 1
            action = self._agent._plan_from_history(history=self._history, owner=self._owner, on_token=on_token)
            if isinstance(action, FinalResponse):
                self._history.append({"role": "assistant", "content": action.content})
                self._agent._mem_write(owner=self._owner, kind="assistant", session_id=self._session_id, content=action.content, meta={})
                return action

            sig = _tool_sig(action)
            self._loop_guard[sig] = self._loop_guard.get(sig, 0) + 1
            if self._loop_guard[sig] >= 2:
                # Instead of giving up, tell the agent to stop loops.
                msg = (
                    "SYSTEM ERROR: You are retrying the same tool call repeatedly with identical inputs. "
                    "This is getting you nowhere. Stop. Try a different approach or ask the user for clarification."
                )
                self._history.append({"role": "tool", "content": msg})
                # Do NOT return FinalResponse; let the loop continue so agent sees the error and retries.
                # However, if we keep looping even after error, we should probably hard break eventually.
                # But _continue loop is bounded by max_steps anyway.
                continue
            
            if action.confirm_required:
                self._pending[action.request_id] = action
                return action

            if on_tool_start:
                on_tool_start(action)

            result = self._agent.execute_tool(tool_request=action, on_progress=on_tool_progress)
            tool_out = _format_tool_result(action, result)
            self._last_tool_output = tool_out
            self._history.append({"role": "tool", "content": tool_out})
            self._agent._mem_write(
                owner=self._owner,
                kind="tool",
                session_id=self._session_id,
                content=tool_out,
                meta={"tool_id": action.tool_id, "request_id": action.request_id, "status": getattr(result, "status", "")},
            )

        return FinalResponse(content="Reached max tool steps without a final answer.")

    def _maybe_run_explicit_tool(
        self,
        *,
        user_message: str,
        on_tool_start: Callable[[ToolRequest], None] | None,
    ) -> AgentResult | None:
        import re

        m = re.match(r"^\s*@([a-zA-Z0-9_.-]+)\b(.*)$", user_message or "")
        if not m:
            return None

        tool_id = m.group(1).strip()
        arg = (m.group(2) or "").strip()

        # Only handle a small, predictable set here. Unknown tools should fall
        # back to the LLM so we don't guess inputs incorrectly.
        inputs: dict[str, Any] | None = None
        if tool_id in {"web.search", "web.surf"}:
            if not arg:
                return FinalResponse(content=f"Usage: `@{tool_id} <query>`")
            # Lightweight flag parsing for power users:
            #   @web.surf --rendered --pages 3 query...
            toks = arg.split()
            rendered = False
            max_pages: int | None = None
            i = 0
            while i < len(toks):
                t = toks[i]
                if t in {"--rendered", "-r"} and tool_id == "web.surf":
                    rendered = True
                    i += 1
                    continue
                if t in {"--pages", "--max-pages"} and tool_id == "web.surf":
                    if i + 1 < len(toks):
                        try:
                            max_pages = int(toks[i + 1])
                            i += 2
                            continue
                        except Exception:
                            pass
                break
            query = " ".join(toks[i:]).strip()
            if not query:
                return FinalResponse(content=f"Usage: `@{tool_id} <query>`")
            inputs = {"query": query}
            if tool_id == "web.surf":
                if rendered:
                    inputs["rendered"] = True
                if max_pages is not None:
                    inputs["max_pages"] = max_pages
        elif tool_id in {"web.visit", "web.visit_rendered"}:
            if not arg:
                return FinalResponse(content=f"Usage: `@{tool_id} <url>`")
            inputs = {"url": arg}
        elif tool_id == "time.now":
            # Best-effort: treat arg as a place/alias unless it looks like IANA.
            if not arg:
                inputs = {}
            elif "/" in arg:
                inputs = {"tz": arg}
            else:
                inputs = {"place": arg}
        else:
            return None

        try:
            tool = self._agent._tools.get(tool_id)
        except KeyError:
            return FinalResponse(content=f"Unknown tool: {tool_id}")

        try:
            self._agent._tools.validate_inputs(tool_id, inputs)
        except Exception as e:
            return FinalResponse(content=f"Invalid inputs for `{tool_id}`: {e}")

        request_id = uuid.uuid4().hex
        tr = ToolRequest(
            request_id=request_id,
            tool_id=tool_id,
            inputs=inputs,
            reason="Explicit user invocation",
            confirm_required=bool(tool.spec.confirm),
        )

        if tr.confirm_required:
            self._pending[tr.request_id] = tr
            return tr

        if on_tool_start:
            on_tool_start(tr)

        result = self._agent.execute_tool(tool_request=tr)
        tool_out = _format_tool_result(tr, result)
        self._last_tool_output = tool_out
        self._history.append({"role": "tool", "content": tool_out})
        self._agent._mem_write(
            owner=self._owner,
            kind="tool",
            session_id=self._session_id,
            content=tool_out,
            meta={"tool_id": tr.tool_id, "request_id": tr.request_id, "status": getattr(result, "status", "")},
        )

        # For explicit tools, return tool output directly (predictable UX).
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if stdout.strip():
            return FinalResponse(content=stdout.strip())
        if stderr.strip():
            return FinalResponse(content=f"Tool error:\n{stderr.strip()}")
        return FinalResponse(content=tool_out.strip())


class Agent:
    def __init__(
        self,
        *,
        llm: Llm,
        tools: ToolRegistry,
        auditor: Auditor,
        thinking_mode: str = "medium",
        memory_store: MemoryStore | None = None,
        memory_owner: str = "local",
        memory_enabled: bool = True,
        memory_max_relevant: int = 8,
        memory_max_chars_per_item: int = 800,
        memory_store_tool_outputs: bool = True,
        memory_store_assistant_outputs: bool = False,
        memory_retrieve_kinds: list[str] | None = None,
        memory_summary_enabled: bool = False,
        memory_summary_every_n_user_turns: int = 12,
        memory_summary_max_source_events: int = 80,
        memory_summary_max_chars_per_source: int = 700,
        system_prompt: str | None = None,
    ):
        self._llm = llm
        self._tools = tools
        self._auditor = auditor
        self._thinking_mode = thinking_mode
        self._memory_enabled = bool(memory_enabled)
        self._default_memory_owner = memory_owner
        self._memory_max_relevant = int(memory_max_relevant)
        self._memory_max_chars_per_item = int(memory_max_chars_per_item)
        self._memory_store_tool_outputs = bool(memory_store_tool_outputs)
        self._memory_store_assistant_outputs = bool(memory_store_assistant_outputs)
        self._memory_retrieve_kinds = (
            [k for k in (memory_retrieve_kinds or ["user", "tool"]) if k] or ["user", "tool"]
        )
        self._memory = memory_store
        self._profile_cache: dict[str, tuple[str, list[str]]] = {}
        self._summary_cache: dict[str, tuple[str, list[str]]] = {}

        self._memory_summary_enabled = bool(memory_summary_enabled)
        self._memory_summary_every_n_user_turns = max(1, int(memory_summary_every_n_user_turns))
        self._memory_summary_max_source_events = max(10, int(memory_summary_max_source_events))
        self._memory_summary_max_chars_per_source = max(200, int(memory_summary_max_chars_per_source))
        self._system_prompt = system_prompt or SYSTEM_PROMPT

    def new_session(self, *, owner: str | None = None) -> AgentSession:
        o = owner or self._default_memory_owner
        return AgentSession(agent=self, owner=o)

    @staticmethod
    def owner_from_secret(secret: str | None) -> str:
        if not secret:
            return "local"
        return "user:" + sha256(secret.encode("utf-8")).hexdigest()[:12]

    def _mem_write(self, *, owner: str, kind: str, session_id: str, content: str, meta: dict[str, Any]) -> None:
        if not self._memory_enabled or not self._memory:
            return
        if kind == "tool" and not self._memory_store_tool_outputs:
            return
        if kind == "assistant" and not self._memory_store_assistant_outputs:
            return
        try:
            self._memory.add_event(
                owner=owner,
                session_id=session_id,
                kind=kind,
                content=content,
                meta=meta,
            )
        except Exception:
            # Memory should never break the agent loop.
            return

    def tool_specs_for_prompt(self) -> str:
        specs = self._tools.list_specs()
        lines: list[str] = []
        for s in specs:
            lines.append(f"- {s['id']}: {s['name']} — {s['description']}")
            lines.append(f"  inputs_schema: {json.dumps(s['inputs_schema'], ensure_ascii=True)}")
            lines.append(f"  confirm: {s['confirm']}")
        return "\n".join(lines)

    def _get_thinking_instruction(self) -> str:
        # Only used for "auto" mode (adaptive prompt injection).
        # Fixed modes (low/medium/high) are handled natively by the LLM backend options.
        return (
            "Thinking Mode: ADAPTIVE. "
            "Assess the complexity of the request. "
            "- If SIMPLE (greetings, facts): Respond directly and successfully. "
            "- If COMPLEX (coding, system admin, multi-step): Engage in deep reasoning (Plan -> Execute -> Verify)."
        )

    def _plan_from_history(
        self,
        *,
        history: list[dict[str, str]],
        owner: str,
        on_token: Callable[[str], None] | None = None,
    ) -> AgentResult:
        grounded: list[str] = []
        profile_lines: list[str] = []
        summary_lines: list[str] = []
        if self._memory_enabled and self._memory and history:
            # Derived profile is stable per-owner and should not depend on the query.
            try:
                latest = self._memory.recent(owner=owner, limit=1)
                latest_ts = latest[0].ts if latest else ""
                cached = self._profile_cache.get(owner)
                if cached and cached[0] == latest_ts:
                    profile_lines = cached[1]
                else:
                    from .memory import build_profile

                    prof = build_profile(memory=self._memory, owner=owner)
                    profile_lines = prof.lines[:12]
                    self._profile_cache[owner] = (latest_ts, profile_lines)
            except Exception:
                profile_lines = []

            if self._memory_summary_enabled:
                try:
                    cached_s = self._summary_cache.get(owner)
                    if cached_s and cached_s[0] == latest_ts:
                        summary_lines = cached_s[1]
                    else:
                        evs = self._memory.recent(owner=owner, limit=1, kinds=["summary"])
                        if evs:
                            raw_lines = [ln for ln in (evs[0].content or "").splitlines() if not ln.startswith("artifacts=")]
                            summary_lines = raw_lines[:18]
                        self._summary_cache[owner] = (latest_ts, summary_lines)
                except Exception:
                    summary_lines = []

            # Use the last user message as retrieval query.
            last_user = ""
            for m in reversed(history):
                if m.get("role") == "user":
                    last_user = str(m.get("content", "")).strip()
                    break
            if last_user:
                try:
                    items = self._memory.search(
                        owner=owner,
                        query=last_user,
                        limit=self._memory_max_relevant,
                        kinds=self._memory_retrieve_kinds,
                    )
                    for ev in items:
                        txt = (ev.content or "").strip()
                        if len(txt) > self._memory_max_chars_per_item:
                            txt = txt[: self._memory_max_chars_per_item] + "\n...(truncated)..."
                        grounded.append(f"- mem_id={ev.id} kind={ev.kind} ts={ev.ts}\n  {txt}")
                except Exception:
                    grounded = []

        prompt = _format_prompt(
            self.tool_specs_for_prompt(),
            history,
            grounded_memory=grounded or None,
            user_profile=profile_lines or None,
            context_summary=summary_lines or None,
        )
        
        # Inject thinking instruction
        if self._thinking_mode == "auto":
             prompt += f"\n\n{self._get_thinking_instruction()}\n"
        
        if on_token:
            # Stream response
            raw_parts = []
            for chunk in self._llm.generate_stream(system_prompt=self._system_prompt, user_prompt=prompt):
                on_token(chunk)
                raw_parts.append(chunk)
            raw = "".join(raw_parts)
        else:
            raw = self._llm.generate(system_prompt=self._system_prompt, user_prompt=prompt)

        self._auditor.log_event({"type": "llm_output", "kind": "plan", "text": _trim_for_log(raw)})
        obj = _parse_first_json_object(raw)
        
        # Retry logic if invalid JSON
        if not isinstance(obj, dict) or "type" not in obj:
            # One repair attempt (we can stream this too if we want, but keeping it simple)
            raw2 = self._llm.generate(
                system_prompt=self._system_prompt,
                user_prompt=f"{REPAIR_PROMPT}\n\nInvalid output:\n{raw}",
            )
            self._auditor.log_event({"type": "llm_output", "kind": "repair", "text": _trim_for_log(raw2)})
            obj2 = _parse_first_json_object(raw2)
            if not isinstance(obj2, dict) or "type" not in obj2:
                return FinalResponse(content=raw.strip())
            obj = obj2

        # Normalize flattened tool calls (e.g. GPT-4o style: type="tool_id")
        raw_type = obj.get("type")
        tool_id = ""
        inputs = {}
        reason = ""
        
        if raw_type == "tool":
            tool_id = str(obj.get("tool_id", "")).strip()
            inputs = obj.get("inputs") or {}
            reason = str(obj.get("reason", "")).strip()
        elif raw_type == "final":
             return FinalResponse(content=str(obj.get("content", "")).strip())
        else:
             # Check if 'type' is actually a valid tool ID
             try:
                 # Check if it exists
                 self._tools.get(str(raw_type))
                 # It is a valid tool! Treat 'type' as 'tool_id'
                 tool_id = str(raw_type)
                 inputs = obj.get("inputs") or {}
                 reason = str(obj.get("reason", "")).strip()
             except KeyError:
                 # Not a tool, unrecognized type
                 pass

        if tool_id:
            if not isinstance(inputs, dict):
                return FinalResponse(content="I couldn't form a valid tool request (inputs must be a dict).")

            try:
                tool = self._tools.get(tool_id)
            except KeyError:
                return FinalResponse(content=f"Unknown tool requested: {tool_id}")

            try:
                self._tools.validate_inputs(tool_id, inputs)
            except Exception as e:
                return FinalResponse(content=f"Tool inputs were invalid: {e}")

            request_id = uuid.uuid4().hex
            self._auditor.log_event(
                {
                    "type": "tool_requested",
                    "request_id": request_id,
                    "tool_id": tool_id,
                    "inputs": inputs,
                    "reason": reason,
                }
            )
            return ToolRequest(
                request_id=request_id,
                tool_id=tool_id,
                inputs=inputs,
                reason=reason,
                confirm_required=bool(tool.spec.confirm),
            )

        # Fallback for weird objects
        return FinalResponse(
            content=f"I produced an unknown response type: {json.dumps(obj)}. Please try again."
        )

    def _maybe_update_summary(self, *, owner: str, session_id: str, user_turns: int) -> None:
        if not self._memory_summary_enabled:
            return
        if not self._memory_enabled or not self._memory:
            return
        if user_turns % self._memory_summary_every_n_user_turns != 0:
            return

        try:
            from .memory import build_rolling_summary, format_summary_event_content

            kinds = ["user", "tool", "note"]
            events = self._memory.recent(owner=owner, limit=self._memory_summary_max_source_events, kinds=kinds)
            if not events:
                return
            # recent() returns newest->oldest; summarizer expects oldest->newest.
            events = list(reversed(events))
            summary_obj = build_rolling_summary(
                llm=self._llm,
                owner=owner,
                source_events=events,
                max_chars_per_source=self._memory_summary_max_chars_per_source,
            )
            if not summary_obj:
                return
            content = format_summary_event_content(summary_obj=summary_obj)
            self._memory.add_event(
                owner=owner,
                session_id=session_id,
                kind="summary",
                content=content,
                meta={"source": "memory.summary", "schema_version": 1},
            )
            # Invalidate cache for this owner.
            self._summary_cache.pop(owner, None)
        except Exception:
            return

    def summarize_now(self, *, owner: str, session_id: str | None = None):
        """
        Force-generate a rolling summary for this owner and store it as kind=summary.
        Returns the created MemoryEvent or None.
        """
        if not self._memory_enabled or not self._memory:
            return None
        try:
            from .memory import build_rolling_summary, format_summary_event_content

            kinds = ["user", "tool", "note"]
            events = self._memory.recent(owner=owner, limit=self._memory_summary_max_source_events, kinds=kinds)
            if not events:
                return None
            events = list(reversed(events))
            summary_obj = build_rolling_summary(
                llm=self._llm,
                owner=owner,
                source_events=events,
                max_chars_per_source=self._memory_summary_max_chars_per_source,
            )
            if not summary_obj:
                return None
            content = format_summary_event_content(summary_obj=summary_obj)
            ev = self._memory.add_event(
                owner=owner,
                session_id=session_id,
                kind="summary",
                content=content,
                meta={"source": "memory.summary", "schema_version": 1, "forced": True},
            )
            self._summary_cache.pop(owner, None)
            return ev
        except Exception:
            return None

    def execute_tool(self, *, tool_request: ToolRequest, on_progress: Callable[[str], None] | None = None):
        self._auditor.log_event(
            {
                "type": "tool_executing",
                "request_id": tool_request.request_id,
                "tool_id": tool_request.tool_id,
            }
        )
        result = self._tools.execute(tool_request.tool_id, tool_request.inputs, on_progress=on_progress)
        self._auditor.log_event(
            {
                "type": "tool_result",
                "request_id": tool_request.request_id,
                "tool_id": tool_request.tool_id,
                "status": result.status,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "artifacts": result.artifacts,
            }
        )
        return result

    def _validate_tool_inputs(self, *, tool_id: str, inputs: dict[str, Any]) -> None:
        self._tools.validate_inputs(tool_id, inputs)

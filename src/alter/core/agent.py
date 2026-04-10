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
from .memory.embeddings import Embedder
from .memory.state_store import StateStore, extract_state_facts
from .memory.compaction import CompactionWorker
from .tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are Alter, a local-first assistant on Windows.
You have access to tools to interact with the system.

CRITICAL: You must ALWAYS respond with a SINGLE JSON object.
Do NOT write any text before or after the JSON.

Tool Use:
- To use a tool, return: {"type":"tool", "tool_id":"...", "inputs":{...}, "reason":"..."}
- To give a final answer, return: {"type":"final", "content":"..."}
- For web.search/web.surf, if the user asks for latest/recent/new/today, set an explicit time_range (day/week/month/year) and category; do not rely on implicit detection.
- For web.search/web.surf, rewrite the user's request into a concise search query (3-8 words) and pass that as the tool `query`. Preserve named entities and key terms; do not add facts.

Grounding & Memory:
- You may see a "Grounded Memory" section in the prompt. Treat it as the ONLY reliable long-term memory.
- Do NOT invent memories. If you cannot find a needed detail in "Grounded Memory" or recent conversation, say you don't know and use tools to verify.
- VERIFY BEFORE ASSERTING: Never claim a file exists, a package is installed, or a service is running without first checking with a tool (fs.list, fs.read, shell.run, process.list, env.get).
- When a tool returns an error, EXPLAIN the error honestly. Never pretend the operation succeeded.
- If you are uncertain about ANY fact (file path, version, config value, env variable), say "Let me check" and use a tool.
- Never guess about system state (files, installed apps, current time, network results). If it is not in grounded memory or fresh tool output, run the appropriate tool to check.
- If the prompt includes a "User Profile" section, treat it as user preferences. Follow it unless it conflicts with these rules.

Rules:
- VALIDATE: Check the 'artifacts' field in previous tool outputs for results.
- REPORT: If a tool just finished execution, report the result to the user. Do NOT simply say "Hello" unless the user greeted you.
- ACTION: If you have the information, provide the final answer immediately. Do not ask for confirmation if you already have the data.
- SILENCE: Do NOT return a final response like "I will do that" or "Allocating tool". Just send the tool request.
- USE SHELL: For git (commit, push, etc.), npm, pip, and other CLI tools not covered by specific tools, use the `shell.run` tool. Do not hallucinate specific tools for every CLI command.
- TOOL CHAINING: For multi-step tasks, verify each step's output before proceeding to the next. Example: after writing a file, read it back if correctness matters.
- NEVER fabricate file paths, URLs, package names, or command outputs. If unsure, use a tool to look them up.
- When the user asks about the current state of ANYTHING (files, processes, time, git, env), ALWAYS use a tool first. Do not guess from stale history.

Style:
- Default to concise, structured answers (1-3 short sections max).
- Keep a warm, human tone; mild playful humor is OK when it fits.
- When debugging, be diagnostic: what you checked + what to do next.

Error Handling:
- If a tool fails (e.g., "File not found"), READ the error message carefully.
- Do NOT retry the exact same inputs.
- Try a correction (e.g., use absolute path, check file existence with `fs.list`, or use `text.search`).
- After an error, explain: (1) what you tried, (2) what went wrong, (3) what you'll try next or ask for guidance.
- If TWO different approaches fail for the same goal, stop and ask the user for help rather than guessing further.

Delegation:
- You have access to specialized Sub-Agents (e.g., Coder Agent via `coder.task`).
- For complex coding tasks (multi-file, refactoring, exploration), prefer delegating to `coder.task`.
- For simple questions or quick fixes, handle them yourself.
- INTERACTION: If the user says "hi", "hello", or asks a general question like "how are you?" or "what can you do?", do NOT use any tools. Just respond naturally. Use tools ONLY when you need to fetch data or perform an action.
"""


REPAIR_PROMPT = """Your previous output was invalid.

Return ONLY a single raw JSON object (NOT wrapped in markdown code blocks), exactly one of:
- {"type":"final","content":"Your answer text here"}
- {"type":"tool","tool_id":"the.tool.id","inputs":{"param":"value"},"reason":"why"}

IMPORTANT:
- Do NOT wrap in ```json ... ```
- Do NOT include any text before or after the JSON
- The output must start with { and end with }
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


def _looks_like_url(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    tl = t.lower()
    return "://" in t or tl.startswith("www.") or tl.startswith("mailto:")


def _looks_like_windows_abs_path(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Drive-letter paths: C:\... or C:/...
    return len(t) >= 3 and t[1] == ":" and t[2] in {"\\", "/"}


def _looks_like_filename(text: str) -> bool:
    import re

    t = (text or "").strip().strip('"').strip("'")
    if not t or len(t) > 260:
        return False
    if any(ch in t for ch in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']):
        return False
    if " " in t:
        return False
    # Basic "name.ext" check
    return bool(re.match(r"^[^.\s][^\\/:*?\"<>|\s]{0,200}\.[A-Za-z0-9]{1,8}$", t))


def _looks_like_executable_token(text: str) -> bool:
    import re

    t = (text or "").strip().strip('"').strip("'")
    if not t or len(t) > 64:
        return False
    if " " in t:
        return False
    return bool(re.match(r"^[A-Za-z0-9._-]+$", t))


def _looks_like_pathish(text: str) -> bool:
    t = (text or "").strip().strip('"').strip("'")
    if not t:
        return False
    if _looks_like_url(t):
        return True
    if _looks_like_windows_abs_path(t):
        return True
    if "\\" in t or "/" in t:
        return True
    if _looks_like_filename(t):
        return True
    return False


def _extract_latest_artifact_path_from_history(history: list[dict[str, str]]) -> str | None:
    """
    Try to find the most recent tool result that included a file-like artifact path.
    This helps recover cases like: fs.write -> launcher.open (missing target).
    """
    for msg in reversed(history or []):
        if msg.get("role") != "tool":
            continue
        content = str(msg.get("content", "") or "")
        if "artifacts=" not in content:
            continue
        artifacts_line = None
        for line in content.splitlines():
            if line.startswith("artifacts="):
                artifacts_line = line[len("artifacts=") :].strip()
                break
        if not artifacts_line:
            continue
        try:
            artifacts = json.loads(artifacts_line)
        except Exception:
            continue
        if not isinstance(artifacts, dict):
            continue
        for key in ("path", "dst", "src"):
            val = artifacts.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _auto_fill_missing_inputs_from_context(
    *,
    tool_id: str,
    tool: Any,
    inputs: dict[str, Any],
    last_user: str,
    history: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(inputs, dict):
        return None
    try:
        schema = getattr(tool, "spec", None).inputs_schema if getattr(tool, "spec", None) else {}
        required = list(schema.get("required") or [])
        props = schema.get("properties") or {}
        missing = []
        for k in required:
            v = inputs.get(k, None)
            if v is None or (isinstance(v, str) and not v.strip()):
                missing.append(k)
        if len(missing) != 1:
            return None
        key = missing[0]
        prop = props.get(key, {})
        if prop.get("type") != "string":
            return None

        # launcher.open recovery: prefer recent tool artifact paths (fs.write, fs.rename, etc.)
        if tool_id == "launcher.open" and key == "target":
            # If the user literally supplied a plausible target, use it.
            if last_user and (_looks_like_pathish(last_user) or _looks_like_executable_token(last_user)):
                fixed = dict(inputs)
                fixed[key] = str(last_user).strip()
                return fixed

            # Otherwise, try to open the most recently created/mentioned artifact path.
            cand = _extract_latest_artifact_path_from_history(history)
            if cand:
                c = cand.strip().strip('"').strip("'")
                if _looks_like_url(c) or _looks_like_windows_abs_path(c):
                    target = c
                else:
                    p = Path(c).expanduser()
                    if not p.is_absolute():
                        p = (Path.cwd() / p)
                    target = str(p)
                fixed = dict(inputs)
                fixed[key] = target
                return fixed

        return None
    except Exception:
        return None


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
    # Match standalone greetings (with optional trailing words like "there", "alter", punctuation)
    # but NOT greetings followed by actual requests ("hi, can you help me...")
    t = text.strip().lower()
    # Pure greetings or greetings + filler words only
    if re.match(r"^(hi|hello|hey|yo|greetings|good morning|good evening|good afternoon|sup|what'?s up)\s*[!?.]*$", t, re.IGNORECASE):
        return True
    if re.match(r"^(hi|hello|hey|yo)\s+(there|alter|buddy|man|dude|bro)[!?.]*$", t, re.IGNORECASE):
        return True
    if re.match(r"^(how are you|how'?s it going|what'?s good)[!?.]*$", t, re.IGNORECASE):
        return True
    return False



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
    recent_actions: list[str] | None = None,
    system_state: dict[str, str] | None = None,
    history_window: int = 24,
    tool_line_limit: int = 60,
    tool_char_limit: int = 3000,
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
    if recent_actions:
        lines.append("Recent Actions (what you did recently, across sessions):")
        lines.extend(recent_actions)
        lines.append("")
    if system_state:
        lines.append("System State (always-on facts — treat as reliable context):")
        for k, v in system_state.items():
            lines.append(f"  {k} = {v}")
        lines.append("")
    lines.append("Conversation:")
    for m in history[-max(1, int(history_window)):]:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role == "tool":
            # Show enough tool output so the LLM can see the results.
            # Cap tool output to prevent context blow-up.
            tool_lines = (content or "").splitlines()[: max(1, int(tool_line_limit))]
            content = "\n".join(tool_lines)
            if len(content) > tool_char_limit:
                content = content[: tool_char_limit] + "\n...(truncated)..."
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
        on_tool_result: Callable[[ToolRequest, Any], None] | None = None,
        max_steps: int = 12,
    ) -> AgentResult:
        self._loop_guard = {}
        self._history.append({"role": "user", "content": user_message})
        self._agent._mem_write(owner=self._owner, kind="user", session_id=self._session_id, content=user_message, meta={})

        explicit = self._maybe_run_explicit_tool(
            user_message=user_message,
            on_tool_start=on_tool_start,
            on_tool_progress=on_tool_progress,
            on_tool_result=on_tool_result,
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
        out = self._continue(max_steps=max_steps, on_token=on_token, on_tool_start=on_tool_start, on_tool_progress=on_tool_progress, on_tool_result=on_tool_result)
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
        on_tool_result: Callable[[ToolRequest, Any], None] | None = None,
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
            tool_id=tr.tool_id,
            tool_inputs=tr.inputs,
            tool_stdout=getattr(result, "stdout", "") or "",
            tool_stderr=getattr(result, "stderr", "") or "",
            tool_status=getattr(result, "status", "") or "",
        )
        if on_tool_result:
            on_tool_result(tr, result)
        
        return self._continue(max_steps=max_steps, on_token=on_token, on_tool_start=on_tool_start, on_tool_progress=on_tool_progress, on_tool_result=on_tool_result)

    def _continue(
        self,
        *,
        max_steps: int,
        on_token: Callable[[str], None] | None = None,
        on_tool_start: Callable[[ToolRequest], None] | None = None,
        on_tool_progress: Callable[[str], None] | None = None,
        on_tool_result: Callable[[ToolRequest, Any], None] | None = None,
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
            if self._loop_guard[sig] >= 3:
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
            
            if on_tool_result:
                on_tool_result(action, result)

            tool_out = _format_tool_result(action, result)
            self._last_tool_output = tool_out
            self._history.append({"role": "tool", "content": tool_out})
            self._agent._mem_write(
                owner=self._owner,
                kind="tool",
                session_id=self._session_id,
                content=tool_out,
                meta={"tool_id": action.tool_id, "request_id": action.request_id, "status": getattr(result, "status", "")},
                tool_id=action.tool_id,
                tool_inputs=action.inputs,
                tool_stdout=getattr(result, "stdout", "") or "",
                tool_stderr=getattr(result, "stderr", "") or "",
                tool_status=getattr(result, "status", "") or "",
            )

        return FinalResponse(content="Reached max tool steps without a final answer.")

    def _maybe_run_explicit_tool(
        self,
        *,
        user_message: str,
        on_tool_start: Callable[[ToolRequest], None] | None,
        on_tool_progress: Callable[[str], None] | None = None,
        on_tool_result: Callable[[ToolRequest, Any], None] | None = None,
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
            mode_override: str | None = None
            category: str | None = None
            time_range: str | None = None
            prefer_recent = False
            i = 0
            while i < len(toks):
                t = toks[i]
                if t in {"--rendered", "-r"} and tool_id == "web.surf":
                    rendered = True
                    i += 1
                    continue
                if t in {"--fast", "-f"} and tool_id == "web.surf":
                    mode_override = "fast"
                    i += 1
                    continue
                if t in {"--deep", "-d"} and tool_id == "web.surf":
                    mode_override = "deep"
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
                if t in {"--category", "--cat"}:
                    if i + 1 < len(toks):
                        category = toks[i + 1]
                        i += 2
                        continue
                if t in {"--time-range", "--time"}:
                    if i + 1 < len(toks):
                        time_range = toks[i + 1]
                        i += 2
                        continue
                if t in {"--prefer-recent"}:
                    prefer_recent = True
                    i += 1
                    continue
                break
            query = " ".join(toks[i:]).strip()
            if not query:
                return FinalResponse(content=f"Usage: `@{tool_id} <query>`")
            inputs = {"query": query}
            if tool_id == "web.surf":
                if mode_override:
                    inputs["mode"] = mode_override
                if rendered:
                    inputs["rendered"] = True
                if max_pages is not None:
                    inputs["max_pages"] = max_pages
                if category:
                    inputs["category"] = category
                if time_range:
                    inputs["time_range"] = time_range
                if prefer_recent:
                    inputs["prefer_recent"] = True
            if tool_id == "web.search":
                if category:
                    inputs["category"] = category
                if time_range:
                    inputs["time_range"] = time_range
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
            # For explicit tools, we just return the error to the user immediately.
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

        result = self._agent.execute_tool(tool_request=tr, on_progress=on_tool_progress)
        tool_out = _format_tool_result(tr, result)
        self._last_tool_output = tool_out
        self._history.append({"role": "tool", "content": tool_out})
        self._agent._mem_write(
            owner=self._owner,
            kind="tool",
            session_id=self._session_id,
            content=tool_out,
            meta={"tool_id": tr.tool_id, "request_id": tr.request_id, "status": getattr(result, "status", "")},
            tool_id=tr.tool_id,
            tool_inputs=tr.inputs,
            tool_stdout=getattr(result, "stdout", "") or "",
            tool_stderr=getattr(result, "stderr", "") or "",
            tool_status=getattr(result, "status", "") or "",
        )

        if on_tool_result:
            on_tool_result(tr, result)

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
        memory_semantic_search: bool = True,
        state_store: StateStore | None = None,
        compaction_interval_minutes: int = 30,
        compaction_prune_days: int = 30,
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

        # --- Semantic search & state store ---
        self._embedder: Embedder | None = None
        if memory_semantic_search and memory_enabled:
            try:
                self._embedder = Embedder()
            except Exception:
                self._embedder = None

        self._state_store = state_store

        # --- Compaction worker ---
        self._compaction_worker: CompactionWorker | None = None
        if (
            memory_enabled
            and self._memory
            and self._state_store
            and self._embedder
        ):
            try:
                self._compaction_worker = CompactionWorker(
                    store=self._memory,
                    state_store=self._state_store,
                    llm=self._llm,
                    embedder=self._embedder,
                    owner=memory_owner,
                    interval_minutes=compaction_interval_minutes,
                    prune_days=compaction_prune_days,
                )
                self._compaction_worker.start()
            except Exception:
                self._compaction_worker = None

    def new_session(self, *, owner: str | None = None) -> AgentSession:
        o = owner or self._default_memory_owner
        return AgentSession(agent=self, owner=o)

    @staticmethod
    def owner_from_secret(secret: str | None) -> str:
        if not secret:
            return "local"
        return "user:" + sha256(secret.encode("utf-8")).hexdigest()[:12]

    def _mem_write(
        self,
        *,
        owner: str,
        kind: str,
        session_id: str,
        content: str,
        meta: dict[str, Any],
        tool_id: str = "",
        tool_inputs: dict[str, Any] | None = None,
        tool_stdout: str = "",
        tool_stderr: str = "",
        tool_status: str = "",
    ) -> None:
        if not self._memory_enabled or not self._memory:
            return
        if kind == "tool" and not self._memory_store_tool_outputs:
            return
        if kind == "assistant" and not self._memory_store_assistant_outputs:
            return

        # Generate embedding if semantic search is enabled
        embedding: bytes | None = None
        if self._embedder and content:
            try:
                embedding = self._embedder.encode(content[:500])
            except Exception:
                pass

        try:
            self._memory.add_event(
                owner=owner,
                session_id=session_id,
                kind=kind,
                content=content,
                meta=meta,
                embedding=embedding,
            )
        except Exception:
            # Memory should never break the agent loop.
            return

        # Extract state facts from tool results
        if kind == "tool" and self._state_store and tool_id:
            try:
                facts = extract_state_facts(
                    tool_id=tool_id,
                    inputs=tool_inputs or {},
                    stdout=tool_stdout,
                    stderr=tool_stderr,
                    status=tool_status,
                )
                for key, value, source in facts:
                    self._state_store.set(
                        owner=owner, key=key, value=value, source=source
                    )
            except Exception:
                pass

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
        recent_action_lines: list[str] = []
        # Track last user message for tool input recovery.
        last_user = ""
        for m in reversed(history):
            if m.get("role") == "user":
                last_user = str(m.get("content", "")).strip()
                break
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
            if last_user:
                try:
                    # Use hybrid search (FTS + semantic) when embedder is available
                    if self._embedder:
                        items = self._memory.hybrid_search(
                            owner=owner,
                            query=last_user,
                            embedder=self._embedder,
                            limit=self._memory_max_relevant,
                            kinds=self._memory_retrieve_kinds,
                        )
                    else:
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

            # Fetch recent tool actions (across sessions) for continuity.
            try:
                recent_tool_evs = self._memory.recent(owner=owner, limit=5, kinds=["tool"])
                for ev in reversed(recent_tool_evs):  # oldest first
                    # Extract tool_id from meta or content
                    tool_id = ev.meta.get("tool_id", "unknown")
                    status = ev.meta.get("status", "")
                    # Show a compact summary of the action
                    first_line = (ev.content or "").split("\n")[0]
                    recent_action_lines.append(f"- [{ev.ts}] {tool_id} ({status}): {first_line}")
            except Exception:
                recent_action_lines = []

        # Gather system state facts
        state_facts: dict[str, str] = {}
        if self._state_store:
            try:
                state_facts = self._state_store.get_all(owner=owner)
            except Exception:
                state_facts = {}

        def build_prompt(
            *,
            grounded_memory=grounded or None,
            recent_actions=recent_action_lines or None,
            system_state=state_facts or None,
            history_window=24,
            tool_line_limit=60,
            tool_char_limit=3000,
        ) -> str:
            return _format_prompt(
                self.tool_specs_for_prompt(),
                history,
                grounded_memory=grounded_memory,
                user_profile=profile_lines or None,
                context_summary=summary_lines or None,
                recent_actions=recent_actions,
                system_state=system_state,
                history_window=history_window,
                tool_line_limit=tool_line_limit,
                tool_char_limit=tool_char_limit,
            )

        prompt = build_prompt()

        # Guardrail against provider input-size limits (e.g., 8k tokens).
        max_prompt_chars = 24000
        if len(prompt) > max_prompt_chars:
            prompt = build_prompt(
                history_window=16,
                tool_line_limit=30,
                tool_char_limit=1500,
            )
        if len(prompt) > max_prompt_chars:
            prompt = build_prompt(
                grounded_memory=None,
                recent_actions=None,
                system_state=None,
                history_window=12,
                tool_line_limit=20,
                tool_char_limit=1000,
            )
        if len(prompt) > max_prompt_chars:
            # Final fallback: keep the start and the most recent tail.
            head = prompt[:12000]
            tail = prompt[-(max_prompt_chars - 12000) :]
            prompt = head + "\n...(trimmed)...\n" + tail
        
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
                # Attempt generic recovery for any tool: fill one missing required string.
                recovered = False
                fixed_inputs = _auto_fill_missing_inputs_from_context(
                    tool_id=tool_id,
                    tool=tool,
                    inputs=inputs,
                    last_user=last_user,
                    history=history,
                )
                if fixed_inputs is not None:
                    try:
                        self._tools.validate_inputs(tool_id, fixed_inputs)
                        inputs = fixed_inputs
                        recovered = True
                    except Exception:
                        recovered = False

                if not recovered:
                    # One repair attempt: ask the model to return a corrected tool call.
                    try:
                        raw2 = self._llm.generate(
                            system_prompt=self._system_prompt,
                            user_prompt=(
                                f"{REPAIR_PROMPT}\n\n"
                                f"Tool inputs were invalid for {tool_id}: {e}\n"
                                f"Return a corrected tool request.\n\n"
                                f"User message: {last_user}\n\n"
                                f"Previous tool request: {obj}"
                            ),
                        )
                        self._auditor.log_event({"type": "llm_output", "kind": "repair", "text": _trim_for_log(raw2)})
                        obj2 = _parse_first_json_object(raw2)
                        if isinstance(obj2, dict) and obj2.get("type") == "final":
                            return FinalResponse(content=str(obj2.get("content", "")).strip())
                        if isinstance(obj2, dict) and obj2.get("type") in {"tool", tool_id}:
                            if obj2.get("type") == "tool":
                                tool_id = str(obj2.get("tool_id", tool_id)).strip() or tool_id
                                inputs = obj2.get("inputs") or {}
                            else:
                                inputs = obj2.get("inputs") or {}
                            self._tools.validate_inputs(tool_id, inputs)
                            recovered = True
                    except Exception:
                        recovered = False

                if not recovered:
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

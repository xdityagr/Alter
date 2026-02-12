# Architecture

## Goals (MVP)
- Local-first agent runtime with a safe tool surface.
- Two interfaces:
  - CLI for quick local use
  - Local web UI that can be reached from a phone over Tailscale
- Pluggable LLM backend (local-only).
  - Recommended: Ollama backend (uses local Ollama REST API)

## Components
- `src/alter/cli.py`
  - Typer CLI (`alter run`, `alter chat`, `alter tools`, `alter config`).
- `src/alter/config.py`
  - YAML config loader + validation.
- `src/alter/core/agent.py`
  - Orchestrates chat → (optional tool requests) → final response.
  - Enforces “no pretend tool output”: tool results come only from executions.
- `src/alter/core/tools/*`
  - Tool interface, registry, and safe implementations.
- `src/alter/core/llm/*`
  - LLM adapter interface plus backends.
- `src/alter/core/server/app.py`
  - FastAPI app: HTTP API + WebSocket + static UI.
- `src/alter/ui/*`
  - Minimal static web UI served by the server.

## Tool Calling Protocol
The agent asks the LLM for a single JSON object per turn:
- Final:
  - `{"type":"final","content":"..."}`
- Tool request:
  - `{"type":"tool","tool_id":"shell.run","inputs":{...},"reason":"..."}`

If the output cannot be parsed as JSON, Alter treats it as a normal assistant response and does not execute tools.

## Multi-step Loop (MVP)
Alter runs a bounded loop per user turn:
- If the model requests a non-confirm tool, Alter executes it automatically and continues.
- If the model requests a confirmation-gated tool, Alter pauses and waits for the user to allow/deny.
- The loop ends on a final response or max-steps.

## Sessions
- CLI: in-process session (single conversation, with history).
- Web UI: per-WebSocket connection session stored in memory (MVP).
- HTTP API: optional `session_id` for multi-turn state in memory (MVP; not persistent).

## Future Extensibility
We keep “Phase 2+” modules behind stable interfaces:
- Indexing: `core/index/*`
- GUI control: `core/vision/*`
- Reviewer: `core/reviewer/*`

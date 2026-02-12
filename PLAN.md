# PLAN

## Phase 0 — Foundation (This Repo)
- Project scaffolding (Python package, CLI, server, UI).
- Config schema and sample config.
- Tool interface + allowlist + confirmations.
- Docs: architecture + security + roadmap.

## Phase 1 — Core Agent MVP
- `alter run`: starts local HTTP server + web UI.
- `alter chat`: local TTY chat loop (in-process).
- Pluggable local LLM backend:
  - `echo` backend for smoke testing (no model required)
  - `llama_cpp` backend for real usage (requires model file)
- Tool registry:
  - File read/list tools
  - Shell tool (allowlisted + confirmation-gated)
- Auditing:
  - JSONL audit log for tool requests/executions.
- Remote access:
  - Document Tailscale/WireGuard exposure and API key requirement.

## Phase 2 — Exocortex (Selective Indexing)
- Opt-in folder roots.
- Local embedding + vector DB (ChromaDB or SQLite-based store).
- Retrieval with citations to local files.
- Incremental reindex on change.

## Phase 3 — Vision + GUI Control (Bounded)
- Screenshot capture + OCR.
- Mouse/keyboard actions with strict guardrails and confirmation.

## Phase 4 — Reviewer + Documentation Generator
- Pre-commit reviewer (bug/risk/readability).
- Docstring + README updates with explicit approval prompts.

## Phase 5 — Context Teleportation
- Snapshot/restore desktop “workspace state” (Windows-first adapters).


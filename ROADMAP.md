# ROADMAP

This project is intentionally phased so we can ship a safe, useful core before adding higher-risk automation.

## Near Term (Next 2–4 weeks)
- Solidify local-only agent loop (tool calling + confirmations).
- Improve UI session handling and add API key entry to the UI.
- Add a few high-leverage tools (git, search-in-files, project summarizer).

## Mid Term
- Exocortex indexing for opted-in folders (VS Code workspaces + notes).
- “Where did I leave off?” queries: combine git status + recent errors + last edited files.

## Longer Term
- Vision-based GUI control (bounded, confirm-first).
- Context Teleportation across devices (state adapters).
- Reviewer agent integrated with pre-commit + CI.
- Documentation generator integrated with file watchers / editor hooks.


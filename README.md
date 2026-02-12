# Alter Agent

Alter is a Windows-first, local AI agent with:
- CLI (`alter chat`, `alter run`)
- Local web UI (mobile-friendly) + WebSocket API
- Safe, allowlisted tools with confirmation gates
- Pluggable **local** LLM backends (no cloud required), including Ollama
- Multi-step agent loop (auto-runs safe tools; asks confirmation for risky tools)

This repo currently implements Phase 0 + Phase 1 (core MVP scaffolding).

## Quickstart

### 1) Create and activate a venv
```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

### 2) Install
```powershell
pip install -e ".[dev]"
```

### 3) Configure
Edit `config/alter.yaml`.

Default backend is `ollama` (recommended). Make sure Ollama is running:
```powershell
ollama list
```
If `ollama list` can’t connect, start Ollama (Windows app) and try again.

We recommend using one of the following models for best results:
- `gpt-oss:20b` (Balanced performance/speed)
- `deepseek-coder-v2` (Best for coding)
- `qwen2.5-coder` (Excellent all-rounder)


If you want to override the model, set:
- `llm.model: "some-model:tag"`

If you want a model-free smoke test, set:
- `llm.backend: echo`

Optional: llama.cpp backend
```powershell
pip install -e ".[llama-cpp]"
```
Then set:
- `llm.backend: llama_cpp`
- `llm.model_path: "C:/path/to/model.gguf"`

### 4) Run (Web UI)
```powershell
alter run
```
Open `http://127.0.0.1:8080`.

If API key is enabled (default), the UI will prompt for it on first load and store it in `localStorage`.
You can also pass it once via URL:
- `http://127.0.0.1:8080/?key=YOUR_KEY` (the UI will save it and remove it from the URL)

Simple per-user tokens: set `security.api_keys` to a list of allowed keys (any one works). If `api_keys` is non-empty, `security.api_key` is ignored.

UI shortcuts:
- `@tool_id` to explicitly invoke a tool (autocomplete popover)
- `/remember ...` to save a note to grounded memory
- `/mem` to view recent memory (or `/mem query` to search)
- `@web.surf <query>` to search + visit top pages
- `@time.now California` or `@time.now America/Los_Angeles` for current time

### 5) Run (CLI)
```powershell
alter chat
```

## Remote Access (Phone as Terminal)
Recommended: use Tailscale/WireGuard so your phone can reach your PC securely.
See `docs/security.md` for guidance and the minimum hardening required.

Practical tip (Windows-first MVP):
- Start the server bound to all interfaces: `alter run --host 0.0.0.0`
- Then open `http://<your-tailscale-ip>:8080/?key=YOUR_KEY` from your phone

## Web Search / Browsing (OSS)
Out of the box, `web.search` can fall back to DuckDuckGo (via `ddgs`), but for robust OSS results you should run a local **SearXNG** instance and point Alter at it:

- Start SearXNG (Docker, easiest):
  - `pwsh -File docker/searxng/setup.ps1 up`
- Set in `config/alter.yaml`:
  - `web.searxng_base_url: http://127.0.0.1:8088`

For JS-heavy pages (live dashboards, some sports pages), use `web.visit_rendered` (Playwright). Install:
- `pip install playwright`
- `playwright install chromium` (or ensure Google Chrome is installed)

## Memory (Grounded, Persistent)
Alter keeps a small persistent “grounded memory” so long runs don’t rely on the model hallucinating past context.

- Stored at `data/memory.sqlite3` (configurable via `memory.path`).
- Only stores raw user messages + tool results (no LLM-made summaries).
- Each turn injects a few relevant memory excerpts back into the prompt as “Grounded Memory”.

## Docs
- `PLAN.md`
- `ROADMAP.md`
- `docs/architecture.md`
- `docs/security.md`

## Ollama Helpers
- `alter models` prints installed Ollama models and Alter's recommended pick.

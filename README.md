# 🤖 Alter Agent

> **A Windows-first, privacy-focused, local AI agent designed to be your extensible sidekick.**

Alter is built on the philosophy that you should be able to run a powerful AI assistant locally, natively on Windows, without sending your private code or data to the cloud. Whether building code, exploring your file system, or automating tasks, Alter uses pluggable local LLMs (like Ollama or llama.cpp) to securely execute agentic workflows right on your machine.

It features a strict, safe tool execution model: safe operations run automatically, while potentially destructive actions (like executing shell commands) require explicit human confirmation. You can use Alter via its fast Typer-based CLI, or securely access its responsive local Web UI from your phone via Tailscale to have a private AI terminal in your pocket anywhere you go.

## ✨ Key Features

- **🔒 Local-First & Private:** Run powerful LLMs entirely on your machine. No cloud dependencies; your data never leaves your network. Support for Ollama and `llama.cpp`.
- **🛡️ Safe Execution Loop:** A strict multi-step agent architecture. "Read-only" safe tools auto-execute, while "write/execute" tools are strictly confirmation-gated.
- **💻 Dual Interfaces:**
  - **Terminal Native:** Fast, in-process chat loop via Typer CLI (`alter chat`).
  - **Mobile-Friendly Web UI:** A local HTTP/WebSocket API (`alter run`) that supports API-key security for remote Tailscale access. Includes shortcuts for tool invocation and web search.
- **🧠 Grounded Memory:** Persistent local SQLite database that maintains the agent's long-term context across sessions, eliminating hallucinations about past events without relying on LLM-made summaries.
- **🌐 Web Browsing:** Built-in web surfing using DuckDuckGo/SearXNG and Playwright to render JS-heavy dashboards or news sites.

## 🚀 The Vision & Roadmap

Alter is being built in phases to ensure a safe, robust core before adding high-risk automation:
- **Phase 1 (Current):** Core agent loop, secure tools, local web UI, bounded shell access.
- **Phase 2 (Exocortex):** Opt-in folder indexing, integrating with local vector stores for code and notes retrieval.
- **Phase 3+ (Advanced Automations):** Bounded vision-based GUI control, context teleportation across Windows devices, and CI/pre-commit integration.
See `ROADMAP.md` and `PLAN.md` for more details.

---

## 🛠️ Quickstart

### 1) Create and activate a venv
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
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

**Optional: llama.cpp backend**
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

**UI shortcuts:**
- `@tool_id` to explicitly invoke a tool (autocomplete popover)
- `/remember ...` to save a note to grounded memory
- `/mem` to view recent memory (or `/mem query` to search)
- `@web.surf <query>` to search + visit top pages
- `@time.now California` or `@time.now America/Los_Angeles` for current time

### 5) Run (CLI)
```powershell
alter chat
```

## 📱 Remote Access (Phone as Terminal)
Recommended: use **Tailscale** or **WireGuard** so your phone can reach your PC securely.
See `docs/security.md` for guidance and the minimum hardening required.

Practical tip (Windows-first MVP):
- Start the server bound to all interfaces: `alter run --host 0.0.0.0`
- Then open `http://<your-tailscale-ip>:8080/?key=YOUR_KEY` from your phone.

## 🌐 Web Search / Browsing (OSS)
Out of the box, `web.search` can fall back to DuckDuckGo (via `ddgs`), but for robust OSS results you should run a local **SearXNG** instance and point Alter at it:

- Start SearXNG (Docker, easiest):
  - `pwsh -File docker/searxng/setup.ps1 up`
- Set in `config/alter.yaml`:
  - `web.searxng_base_url: http://127.0.0.1:8088`

For JS-heavy pages (live dashboards, some sports pages), use `web.visit_rendered` (Playwright). Install:
- `pip install playwright`
- `playwright install chromium` (or ensure Google Chrome is installed)

## 🧠 Memory (Grounded, Persistent)
Alter keeps a small persistent “grounded memory” so long runs don’t rely on the model hallucinating past context.

- Stored at `data/memory.sqlite3` (configurable via `memory.path`).
- Only stores raw user messages + tool results (no LLM-made summaries).
- Each turn injects a few relevant memory excerpts back into the prompt as “Grounded Memory”.

## 📚 Docs
- [PLAN.md](PLAN.md)
- [ROADMAP.md](ROADMAP.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/security.md](docs/security.md)

## 🦙 Ollama Helpers
- `alter models` prints installed Ollama models and Alter's recommended pick.

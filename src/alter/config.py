from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    backend: Literal["echo", "llama_cpp", "ollama", "openai", "github"] = "echo"
    model_path: str | None = None
    # Ollama settings (used when backend=ollama)
    model: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    timeout_s: int = 120
    # If true, Alter will try to start `ollama serve` when Ollama isn't reachable.
    ollama_autostart: bool = True
    # Thinking mode: "low", "medium", "high", "auto"
    thinking_mode: Literal["low", "medium", "high", "auto"] = "auto"
    
    # OpenAI / GitHub Models settings
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    # Token for GitHub backend (alternative to openai_api_key)
    github_token: str | None = None


class UiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080


class WebConfig(BaseModel):
    # Optional: point to a SearXNG instance for much more reliable OSS search results.
    # Example: http://127.0.0.1:8088 (then Alter calls /search?format=json)
    searxng_base_url: str | None = None
    # Rendered browsing (JS-capable) via Playwright.
    rendered_headless: bool = True
    rendered_timeout_s: float = 20.0
    rendered_wait_ms: int = 1200
    # Try to use the system-installed Chrome first (Playwright "channel"), then fall back.
    rendered_prefer_chrome_channel: bool = True


class SecurityConfig(BaseModel):
    require_api_key: bool = True
    # Optional: allow multiple API keys (simple per-user/per-device tokens).
    # If non-empty, any key in this list is accepted. Otherwise `api_key` is used.
    api_keys: list[str] = Field(default_factory=list)
    api_key: str = "change-me"
    require_confirmation: bool = True
    allowed_commands: list[str] = Field(default_factory=lambda: ["python", "git", "pwsh"])
    # If true, shell commands will not require explicit confirmation (use with caution).
    auto_confirm_shell: bool = False
    # For fs.write tool (confirmation-gated): restrict writes to these roots.
    # Default is current working directory.
    allowed_write_roots: list[str] = Field(default_factory=lambda: ["."])
    # Basic API rate limit for /v1/* (in-memory, per-client). 0 disables.
    max_requests_per_minute: int = 120


class RemoteConfig(BaseModel):
    tailscale_enabled: bool = True


class MemoryConfig(BaseModel):
    enabled: bool = True
    # SQLite DB path for grounded memory events.
    path: str = "data/memory.sqlite3"
    # Attempt to redact common secrets (tokens, passwords, API keys) before writing to disk.
    # This is best-effort and may produce false positives.
    redact_secrets: bool = True
    # How many relevant memory snippets to include in the prompt.
    max_relevant: int = 8
    # Hard cap per memory item when injected into prompt.
    max_chars_per_item: int = 800
    # Store tool outputs in memory (recommended).
    store_tool_outputs: bool = True
    # Storing assistant messages can amplify hallucinations. Keep this off unless
    # you have an explicit "note/summary" pipeline.
    store_assistant_outputs: bool = False
    # Only retrieve grounded kinds into the prompt.
    retrieve_kinds: list[str] = Field(default_factory=lambda: ["user", "tool", "note"])
    # Rolling summaries can keep long runs coherent without stuffing the full transcript.
    # Summaries are NOT treated as ground truth and are excluded from retrieval by default.
    summary_enabled: bool = False
    summary_every_n_user_turns: int = 12
    summary_max_source_events: int = 80
    summary_max_chars_per_source: int = 700


class IndexConfig(BaseModel):
    roots: list[str] = Field(default_factory=list)


class AlterConfig(BaseModel):
    llm: LlmConfig = Field(default_factory=LlmConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    config: AlterConfig
    raw: dict[str, Any]


def load_config(path: str | Path | None = None) -> LoadedConfig:
    """
    Load configuration from YAML.

    Resolution order:
    1) explicit `path`
    2) env var ALTER_CONFIG
    3) `config/alter.yaml` relative to cwd
    """
    if path is None:
        import os

        env_path = os.environ.get("ALTER_CONFIG")
        if env_path:
            path = env_path
        else:
            path = Path("config") / "alter.yaml"

    path = Path(path).expanduser().resolve()
    if not path.exists():
        cfg = AlterConfig()
        return LoadedConfig(path=path, config=cfg, raw={})

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = AlterConfig.model_validate(raw)
    return LoadedConfig(path=path, config=cfg, raw=raw)

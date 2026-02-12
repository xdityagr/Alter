from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.prompt import Confirm

from .config import load_config
from .core.agent import Agent, FinalResponse, ToolRequest
from .core.audit import Auditor
from .core.llm.factory import build_llm
from .core.memory import MemoryStore
from .core.server.app import create_app
from .core.tools.defaults import build_default_registry


app = typer.Typer(add_completion=False, help="Alter: local AI agent (Windows-first).")


@app.command()
def run(
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config YAML."),
    host: Optional[str] = typer.Option(None, help="Override host from config."),
    port: Optional[int] = typer.Option(None, help="Override port from config."),
    reload: bool = typer.Option(False, "--reload", help="Enable hot reloading (dev mode)."),
):
    """
    Start Alter's local server + web UI.
    """
    loaded = load_config(config)
    cfg = loaded.config

    if host:
        cfg.ui.host = host
    if port:
        cfg.ui.port = port

    import uvicorn
    from rich.panel import Panel
    from rich.table import Table
    from rich.console import Console
    from rich.align import Align
    from rich.style import Style

    console = Console()
    console.print()

    # Prepare info for dashboard
    model_name = cfg.llm.model
    if not model_name and cfg.llm.backend == "ollama":
        # If not set, we auto-pick, but here we might not know it yet unless we init logic.
        # But we create_app() next, so we can just say "Auto-detecting..." or query it if easy.
        # Actually create_app calls build_llm internally too. 
        # For display purposes, let's just show what's in config or "Auto".
        model_name = "Auto (Ollama)"
    
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold cyan", justify="right")
    table.add_column("Value", style="white")

    table.add_row("Server", f"http://{cfg.ui.host}:{cfg.ui.port}")
    table.add_row("Config", str(loaded.path))
    table.add_row("Backend", cfg.llm.backend)
    table.add_row("Model", model_name or "Unknown")
    
    if cfg.security.require_api_key:
        table.add_row("Auth", "[yellow]API Key Required[/yellow]")

    content = Align.center(table)

    console.print(Panel(
        content,
        title="[bold blue]Alter Agent[/bold blue]",
        subtitle="[dim]Local AI Server[/dim]",
        border_style="blue",
        padding=(1, 2),
        expand=False
    ))
    console.print()

    if cfg.security.require_api_key:
        console.print("[dim]→ Open the UI with [bold]?key=YOUR_KEY[/bold] to authenticate.[/dim]", justify="center")
        console.print()

    if reload:
        if config:
            import os
            os.environ["ALTER_CONFIG"] = str(config.resolve())
        
        console.print("[yellow]⚡ Hot reload enabled[/yellow]", justify="center")
        uvicorn.run(
            "alter.core.server.app:create_app", 
            host=cfg.ui.host, 
            port=cfg.ui.port, 
            log_level="warning", 
            reload=True, 
            factory=True
        )
    else:
        uvicorn.run(create_app(cfg), host=cfg.ui.host, port=cfg.ui.port, log_level="warning")


@app.command()
def chat(config: Optional[Path] = typer.Option(None, "--config", help="Path to config YAML.")):
    """
    Start a local TTY chat session (in-process).
    """
    import threading

    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.text import Text

    loaded = load_config(config)
    cfg = loaded.config
    llm = build_llm(cfg)
    auditor = Auditor(path=Path("data") / "audit.jsonl")
    tools = build_default_registry(cfg, llm, auditor)
    memory_store = None
    if getattr(cfg, "memory", None) and cfg.memory.enabled:
        memory_store = MemoryStore(path=Path(cfg.memory.path), redact_secrets=getattr(cfg.memory, "redact_secrets", True))
    agent = Agent(
        llm=llm,
        tools=tools,
        auditor=auditor,
        memory_store=memory_store,
        memory_enabled=cfg.memory.enabled,
        memory_max_relevant=cfg.memory.max_relevant,
        memory_max_chars_per_item=cfg.memory.max_chars_per_item,
        memory_store_tool_outputs=cfg.memory.store_tool_outputs,
        memory_store_assistant_outputs=getattr(cfg.memory, "store_assistant_outputs", False),
        memory_retrieve_kinds=getattr(cfg.memory, "retrieve_kinds", ["user", "tool"]),
        memory_summary_enabled=getattr(cfg.memory, "summary_enabled", False),
        memory_summary_every_n_user_turns=getattr(cfg.memory, "summary_every_n_user_turns", 12),
        memory_summary_max_source_events=getattr(cfg.memory, "summary_max_source_events", 80),
        memory_summary_max_chars_per_source=getattr(cfg.memory, "summary_max_chars_per_source", 700),
    )
    session = agent.new_session()

    console = Console()
    model_info = llm.model_info()
    console.print()
    model_name = model_info.model_path or "unknown model"
    console.print(Panel(
        f"[bold white]Alter[/bold white]  ·  [dim]{model_name}[/dim]  ·  [dim]{model_info.backend}[/dim]\n"
        f"[dim]Type [bold]exit[/bold] to quit[/dim]",
        border_style="blue",
        padding=(0, 2),
    ))
    console.print()

    # Shared mutable state for callbacks
    state = {
        "status_text": "Thinking...",
        "tool_id": None,
        "live": None,
    }

    def on_tool_start(tr):
        """Show tool execution with animated status."""
        state["tool_id"] = tr.tool_id
        state["status_text"] = f"Running [bold]{tr.tool_id}[/bold]..."
        live = state.get("live")
        if live:
            live.update(_make_status(state["status_text"]))

    def on_tool_progress(message: str):
        """Update the spinner text with tool progress."""
        tool_id = state.get("tool_id") or "tool"
        state["status_text"] = f"[bold]{tool_id}[/bold] · {message}"
        live = state.get("live")
        if live:
            live.update(_make_status(state["status_text"]))

    while True:
        try:
            user = console.input("[bold cyan]❯ [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            return
        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            console.print("[dim]Goodbye![/dim]")
            return

        # Reset state
        state["tool_id"] = None

        try:
            with Live(_make_status("Thinking..."), console=console, refresh_per_second=12, transient=True) as live:
                state["live"] = live
                result = session.run_turn(
                    user_message=user,
                    on_tool_start=on_tool_start,
                    on_tool_progress=on_tool_progress,
                )
                state["live"] = None

        except Exception as e:
            state["live"] = None
            console.print(f"\n[red]Error:[/red] {e}")
            continue

        # Handle tool confirmation loop
        while True:
            if isinstance(result, FinalResponse):
                console.print()
                console.print(Markdown(result.content))
                console.print()
                break

            # Tool needs confirmation
            console.print()
            console.print(f"  [yellow]⚡ Tool:[/yellow] [bold]{result.tool_id}[/bold]")
            console.print(f"  [dim]Reason:[/dim] {result.reason}")
            if result.inputs:
                for k, v in result.inputs.items():
                    val_str = str(v)
                    if len(val_str) > 80:
                        val_str = val_str[:77] + "..."
                    console.print(f"  [dim]{k}:[/dim] {val_str}")

            ok = True
            if result.confirm_required:
                ok = Confirm.ask("  Allow?", default=False)

            try:
                with Live(_make_status(f"Running [bold]{result.tool_id}[/bold]..."), console=console, refresh_per_second=12, transient=True) as live:
                    state["live"] = live
                    result = session.confirm(
                        request_id=result.request_id,
                        allow=ok,
                        on_tool_start=on_tool_start,
                        on_tool_progress=on_tool_progress,
                    )
                    state["live"] = None
            except Exception as e:
                state["live"] = None
                console.print(f"\n[red]Error:[/red] {e}")
                break


def _make_status(text: str):
    """Create a spinner renderable for Rich Live."""
    from rich.spinner import Spinner
    return Spinner("dots", text=text, style="cyan")


@app.command()
def tools(config: Optional[Path] = typer.Option(None, "--config", help="Path to config YAML.")):
    """
    List tools and schemas.
    """
    loaded = load_config(config)
    cfg = loaded.config
    llm = build_llm(cfg)
    # Dummy auditor for listing tools
    auditor = Auditor(path=Path("data") / "audit.jsonl")
    reg = build_default_registry(cfg, llm, auditor)
    for s in reg.list_specs():
        rprint(f"[bold]{s['id']}[/bold] — {s['name']}")
        rprint(f"  confirm: {s['confirm']}")
        rprint(f"  {s['description']}")


@app.command()
def config(
    path: Optional[Path] = typer.Option(None, "--config", help="Path to config YAML."),
    show_raw: bool = typer.Option(False, "--raw", help="Show raw YAML as loaded."),
):
    """
    Show resolved configuration (and validate).
    """
    loaded = load_config(path)
    rprint(f"[bold]Config path:[/bold] {loaded.path}")
    rprint(f"[bold]Validated config:[/bold] {loaded.config.model_dump()}")
    if show_raw:
        rprint(f"[bold]Raw:[/bold] {loaded.raw}")


@app.command()
def index():
    """
    Placeholder for Phase 2 Exocortex indexing.
    """
    rprint("Indexing is not implemented yet (Phase 2).")


@app.command()
def models(config: Optional[Path] = typer.Option(None, "--config", help="Path to config YAML.")):
    """
    List installed Ollama models and print Alter's recommended pick.
    """
    loaded = load_config(config)
    cfg = loaded.config
    loaded = load_config(config)
    cfg = loaded.config
    
    if cfg.llm.backend == "ollama":
        from .core.llm.ollama import OllamaLlm, choose_best_model
        llm = OllamaLlm(
            base_url=cfg.llm.ollama_base_url,
            # Force no auto-pick here; we just want listing.
            model=cfg.llm.model or "llama3.1:8b",
            timeout_s=cfg.llm.timeout_s,
        )
        tags = llm.list_models()
        rec = choose_best_model(tags)

        rprint(f"[bold]Ollama base_url:[/bold] {cfg.llm.ollama_base_url}")
        rprint("[bold]Installed local models:[/bold]")
        for m in tags:
            size_gb = (m.size or 0) / (1024**3) if m.size else None
            size_txt = f"{size_gb:.1f} GB" if size_gb is not None else "-"
            rprint(f"  - {m.name} ({size_txt})")
        rprint(f"[bold]Recommended:[/bold] {rec or '(none found)'}")

    elif cfg.llm.backend in ("github", "openai"):
        import httpx
        from pathlib import Path
        
        base_url = cfg.llm.openai_base_url
        if cfg.llm.backend == "github" and not base_url:
             base_url = "https://models.inference.ai.azure.com"
        elif not base_url:
             base_url = "https://api.openai.com/v1"

        token = cfg.llm.openai_api_key
        if cfg.llm.backend == "github":
             if cfg.llm.github_token:
                 token = cfg.llm.github_token
             elif not token:
                 tpath = Path("data/github_token.txt")
                 if tpath.exists():
                     token = tpath.read_text("utf-8").strip()
        
        if not token:
            rprint(f"[red]No token found for {cfg.llm.backend}. Run `alter auth github` if using GitHub.[/red]")
            return

        rprint(f"[bold]Backend:[/bold] {cfg.llm.backend}")
        rprint(f"[bold]Endpoint:[/bold] {base_url}")
        
        try:
            # Most OpenAI compatible endpoints support /models
            url = f"{base_url}/models"
            # Azure inference endpoint is weird, sometimes needs strict slash handling
            if url.startswith("https://models.inference.ai.azure.com//"):
                 url = url.replace("//", "/")
            
            headers = {"Authorization": f"Bearer {token}"}
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                
            # Handle list or dict wrap
            if isinstance(data, list):
                items = data
            else:
                items = data.get("data", [])
            
            rprint(f"[bold]Available Models ({len(items)}):[/bold]")
            for m in items:
                name = m.get("name") or m.get("id")
                friendly = m.get("friendly_name")
                if friendly:
                    rprint(f"  - [cyan]{name}[/cyan] ({friendly})")
                else:
                    rprint(f"  - [cyan]{name}[/cyan]")
                    
        except Exception as e:
            rprint(f"[red]Failed to list models:[/red] {e}")

    else:
        rprint(f"Model listing not supported for backend: {cfg.llm.backend}")


@app.command()
def auth(provider: str = typer.Argument("github", help="Auth provider (default: github)")):
    """
    Authenticate with a provider (e.g., GitHub) to get an access token.
    """
    if provider.lower() != "github":
        rprint(f"[red]Unknown provider:[/red] {provider}. Only 'github' is supported.")
        return

    from .core.llm.github_auth import authenticate_device_flow
    
    try:
        token = authenticate_device_flow()
        
        # Save token to data/github_token.txt
        data_dir = Path("data")
        data_dir.mkdir(exist_ok=True)
        token_file = data_dir / "github_token.txt"
        token_file.write_text(token, encoding="utf-8")
        
        rprint("[green]Token received and saved![/green]")
        rprint(f"Token saved to: {token_file}")
        rprint("\n[bold]Next Steps:[/bold]")
        rprint("1. Ensure `config/alter.yaml` has `llm.backend: github`")
        rprint("2. Run `alter run` or `alter chat`")
        rprint("(No need to manually edit config for the token now!)")
        
    except Exception as e:
        rprint(f"[red]Auth failed:[/red] {e}")


def _print_tool_request(tr: ToolRequest) -> None:
    rprint("[yellow]Tool requested[/yellow]")
    rprint(f"  id: {tr.tool_id}")
    rprint(f"  reason: {tr.reason}")
    rprint(f"  inputs: {tr.inputs}")

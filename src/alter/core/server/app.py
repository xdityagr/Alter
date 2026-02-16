from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, Response

from ...config import AlterConfig
from ..agent import Agent as AlterAgent
from ..agent import AgentSession, FinalResponse, ToolRequest
from ..audit import Auditor
from ..llm.factory import build_llm
from ..memory import MemoryStore
from ..memory.state_store import StateStore
from ..tools.defaults import build_default_registry
from .auth import is_valid_api_key, require_api_key
from .models import (
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    MemoryEventOut,
    MemoryListResponse,
    MemoryRememberRequest,
    MemoryRememberResponse,
    MemorySummarizeResponse,
    ProfileResponse,
    ToolExecuteRequest,
    ToolExecuteResponse,
    SetModelRequest,
)
from .ratelimit import RateLimiter
from .json_parser import StreamingJsonParser
import httpx


def create_app(cfg: AlterConfig | None = None) -> FastAPI:
    if cfg is None:
        from ...config import load_config
        cfg = load_config(None).config

    app = FastAPI(title="Alter", version="0.1.0")

    @app.on_event("startup")
    async def on_startup():
        print("\n\033[1;36m=== MEMORY SYSTEM REPORT ===\033[0m")
        if memory_store:
            try:
                s = memory_store.stats()
                print(f" • Status: \033[32mActive\033[0m")
                print(f" • Path:   {cfg.memory.path}")
                print(f" • Stats:  {s['events']} events, {s['owners']} identities")
            except Exception as e:
                 print(f" • Status: Error ({e})")
        else:
            print(f" • Status: \033[31mDisabled\033[0m (Enable in config)")
        
        # Auto-launch Docker + SearXNG (non-blocking background thread)
        import subprocess, threading, time, shutil, sys, os
        def _ensure_docker_and_searxng():
            try:
                # 1. Check if Docker daemon is already running
                r = subprocess.run(
                    ["docker", "info"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    timeout=5,
                )
                docker_ready = r.returncode == 0

                # 2. If not running, try to start Docker Desktop (Windows)
                if not docker_ready and sys.platform == "win32":
                    # Common Docker Desktop paths
                    dd_paths = [
                        Path(os.environ.get("ProgramFiles", "")) / "Docker" / "Docker" / "Docker Desktop.exe",
                        Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker Desktop.exe",
                    ]
                    dd_exe = None
                    for p in dd_paths:
                        if p.exists():
                            dd_exe = str(p)
                            break
                    if not dd_exe:
                        dd_exe = shutil.which("Docker Desktop")

                    if dd_exe:
                        print(" • Docker: \033[33mStarting Docker Desktop...\033[0m")
                        subprocess.Popen(
                            [dd_exe],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                        )
                        # Wait for Docker daemon to become ready (up to 45s)
                        for _ in range(23):
                            time.sleep(2)
                            chk = subprocess.run(
                                ["docker", "info"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                                timeout=5,
                            )
                            if chk.returncode == 0:
                                docker_ready = True
                                break
                    if not docker_ready:
                        return  # Docker not available, give up silently

                # 3. Start the SearXNG container
                subprocess.run(
                    ["docker", "start", "searxng"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    timeout=10,
                )
                print(" • Service: \033[32mSearXNG (Auto-started)\033[0m")
            except Exception:
                pass  # Silently fail — search will use DuckDuckGo fallback

        threading.Thread(target=_ensure_docker_and_searxng, daemon=True).start()

        print("============================\n")

    llm = build_llm(cfg)
    auditor = Auditor(path=Path("data") / "audit.jsonl")
    tools = build_default_registry(cfg, llm, auditor)
    memory_store = None
    state_store = None
    if getattr(cfg, "memory", None) and cfg.memory.enabled:
        memory_store = MemoryStore(path=Path(cfg.memory.path), redact_secrets=getattr(cfg.memory, "redact_secrets", True))
        state_store = StateStore(path=Path(getattr(cfg.memory, "state_store_path", "data/state.sqlite3")))
    agent = AlterAgent(
        llm=llm,
        tools=tools,
        auditor=auditor,
        thinking_mode=cfg.llm.thinking_mode,
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
        memory_semantic_search=getattr(cfg.memory, "semantic_search", True),
        state_store=state_store,
        compaction_interval_minutes=getattr(cfg.memory, "compaction_interval_minutes", 30),
        compaction_prune_days=getattr(cfg.memory, "compaction_prune_days", 30),
    )


    sessions: dict[str, AgentSession] = {}
    auth = require_api_key(cfg)
    limiter = RateLimiter(max_per_minute=cfg.security.max_requests_per_minute)

    # In-memory cache for model lists: (timestamp, models)
    model_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
    CACHE_TTL = 300  # 5 minutes

    async def rate_limit(request: Request) -> None:
        host = request.client.host if request.client else "unknown"
        if not limiter.allow(host):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    rate = Depends(rate_limit)

    @app.get("/", response_class=HTMLResponse)
    async def root():
        # UI is public; API + websocket are protected.
        return HTMLResponse(content=_read_ui_file("index.html"))

    @app.get("/assets/{asset_path:path}")
    async def assets(asset_path: str):
        content, media = _read_ui_asset(asset_path)
        return Response(content=content, media_type=media)

    @app.get("/v1/system/status")
    async def status(_: Any = auth, __: Any = rate):
        return {
            "ok": True, 
            "model": agent._llm.model_info().__dict__,
            "config": {
                "thinking_mode": cfg.llm.thinking_mode
            }
        }
    
    @app.get("/v1/system/welcome")
    async def welcome(request: Request, _: Any = auth, __: Any = rate):
        """
        Returns personalized welcome content (Title + Prompts).
        No caching, generates fresh on every load.
        """
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate) or "User"
        
        # 1. Analyze History
        history_summary = "No recent history."
        try:
             # Use Auditor.read_recent
             events = agent._auditor.read_recent(30)
             if events:
                 summary = []
                 for e in events:
                     if e.get("type") == "tool_execution":
                         summary.append(f"Ran tool {e.get('tool_id')}")
                     if e.get("type") == "llm_output" and e.get("kind") == "plan":
                         pass 
                 if summary:
                    # Filter unique
                    unique = list(dict.fromkeys(summary))
                    history_summary = "Recent User Activity:\n" + "\n".join(unique[-8:])
        except Exception as e:
            print(f"History usage error: {e}")

        # 2. Get User Profile from Memory
        profile_context = ""
        display_name = "Operator" # Fallback
        
        if memory_store:
            try:
                # A. Structured Onboarding
                notes = memory_store.recent(owner=owner, kinds=["note"], limit=50)
                profile_items = []
                found_name = None

                for n in notes:
                    meta = n.meta or {}
                    if meta.get("source") == "onboard":
                        key = meta.get("profile_key", "")
                        ans = n.content
                        if key and ans:
                             profile_items.append(f"{key}: {ans}")
                             if key.lower() == "name":
                                 found_name = ans
                
                if profile_items:
                     profile_context = "User Context & Preferences:\n" 
                     profile_context += "ONBOARDING:\n" + "\n".join(profile_items) + "\n"

                # Attempt to use structured name
                if found_name:
                    display_name = found_name
                elif owner.startswith("user:") or (len(owner) > 15 and any(c.isdigit() for c in owner)):
                    pass # Keep "Operator"
                else:
                    display_name = owner # It's a clean string?

            except Exception as e:
                print(f"Error fetching profile: {e}")

        # 3. Generate with LLM
        prompt = f"""
        You are configuring the "Alter" AI agent for the user "{display_name}". 
        
        USER HISTORY (Recent Activity):
        {history_summary}

        {profile_context}
        
        Generate a personalized dashboard configuration in valid JSON format.
        
        Requirements:
        1. "titles": A list of 3-5 creative, personalized, and cool system identities. Max 3-4 words each.
           - Vibe: "Chill but serious", "High competence".
           - Examples: ["{display_name}'s Alter Ego", "{display_name}'s Clone", "The Architect", "Dev HQ", "Alter Ego", "Neural Link"].
           - If identity is unknown, use ["OPERATOR CONSOLE", "SYSTEM ONLINE"].
           - If User Profile is available, use it to make titles hyper-personalized (e.g. "{display_name}'s Console").
           
        2. "prompts": A list of 4 prompts:
           - 2 MUST be based on the User History above. Do not add things that do not make sense as a task one can ask an LLM to do. 
           - 2 MUST be seeded general developer commands.
           - Use User Context to style them (e.g. if 'verbosity' is low, keep them short).
           
        Response format:
        {{
            "titles": ["STR", "STR", "STR"],
            "prompts": ["STR", "STR", "STR", "STR"]
        }}
        Only return the JSON.
        """
        
        try:
            # We use the agent's LLM
            raw = agent._llm.generate(
                system_prompt="You are a quirky & creative configuration assistant. Output JSON only.", 
                user_prompt=prompt
            )
            
            # extract json
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                json_str = raw[start:end+1]
                content = json.loads(json_str)
            else:
                # Fallback
                content = {
                    "titles": ["LOCAL INTELLIGENCE", "SYSTEM ONLINE"],
                    "prompts": ["Check system status", "Search the web for news", "Summarize recent logs", "Configure models"]
                }
            
            # Validate fields
            if "titles" not in content or not isinstance(content["titles"], list): content["titles"] = ["LOCAL INTELLIGENCE"]
            if "prompts" not in content or not isinstance(content["prompts"], list):
                content["prompts"] = ["Check system status", "Search the web for news", "Summarize recent logs", "Configure models"]
            
            if cfg.ui.skip_setup:
                content["has_identity"] = True
            else:
                content["has_identity"] = bool(profile_items)
            return content
            
        except Exception as e:
            print(f"Error generating welcome: {e}")
            return {
                "titles": ["LOCAL INTELLIGENCE"],
                "prompts": ["Check system status", "Search the web for news", "Summarize recent logs", "Configure models"],
                "has_identity": bool(profile_items) if 'profile_items' in dir() else False
            }

    @app.post("/v1/system/snapshot", response_model=MemoryRememberResponse)
    async def system_snapshot(request: Request, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)

        try:
            tools.validate_inputs("system.snapshot", {})
            result = tools.execute("system.snapshot", {})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Snapshot failed: {e}")

        # Store in memory in a tool-like format so the agent can reuse it as grounded evidence.
        def trim(s: str, n: int = 4000) -> str:
            s = s or ""
            return s if len(s) <= n else s[:n] + "\n...(truncated)..."

        content = f"tool_id=system.snapshot\nstatus={getattr(result, 'status', 'ok')}"
        if getattr(result, "stdout", ""):
            content += f"\nstdout={trim(result.stdout)}"
        if getattr(result, "artifacts", None):
            try:
                content += f"\nartifacts={json.dumps(result.artifacts, ensure_ascii=True)}"
            except Exception:
                pass

        ev = memory_store.add_event(
            owner=owner,
            session_id=None,
            kind="tool",
            content=content,
            meta={"tool_id": "system.snapshot", "source": "system_snapshot_http"},
        )
        auditor.log_event({"type": "system_snapshot", "owner": owner, "mem_id": ev.id})
        return MemoryRememberResponse(mem_id=ev.id, ts=ev.ts)

    @app.get("/v1/profile", response_model=ProfileResponse)
    async def profile(request: Request, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)
        from ..memory import build_profile

        prof = build_profile(memory=memory_store, owner=owner)
        return ProfileResponse(owner=owner, lines=prof.lines, evidence=prof.evidence)

    @app.post("/v1/memory/remember", response_model=MemoryRememberResponse)
    async def remember(req: MemoryRememberRequest, request: Request, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)

        # Onboard upsert: delete existing entry with same profile_key before inserting
        meta = req.meta or {"source": "remember"}
        if meta.get("source") == "onboard" and meta.get("profile_key"):
            try:
                memory_store.delete_by_meta(
                    owner=owner,
                    source="onboard",
                    profile_key=meta["profile_key"],
                )
            except Exception:
                pass  # best-effort

        ev = memory_store.add_event(
            owner=owner,
            session_id=None,
            kind="note",
            content=req.content,
            meta=meta,
        )
        auditor.log_event({"type": "memory_remembered", "owner": owner, "mem_id": ev.id, "kind": ev.kind})
        return MemoryRememberResponse(mem_id=ev.id, ts=ev.ts)

    @app.delete("/v1/memory/reset")
    async def reset_memory(request: Request, _: Any = auth, __: Any = rate):
        """Delete ALL memory events for the authenticated owner."""
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)
        deleted = memory_store.clear_owner(owner=owner)
        # Also clear state store facts
        if state_store:
            try:
                state_store.clear(owner=owner)
            except Exception:
                pass
        auditor.log_event({"type": "memory_reset", "owner": owner, "deleted": deleted})
        return {"ok": True, "deleted": deleted}

    @app.post("/v1/memory/summarize", response_model=MemorySummarizeResponse)
    async def memory_summarize(request: Request, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)
        ev = agent.summarize_now(owner=owner, session_id=None)
        if not ev:
            raise HTTPException(status_code=400, detail="Summary failed or no events to summarize")
        return MemorySummarizeResponse(mem_id=ev.id, ts=ev.ts, content=ev.content)

    @app.get("/v1/memory/recent", response_model=MemoryListResponse)
    async def memory_recent(request: Request, limit: int = 20, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)
        lim = max(1, min(int(limit), 50))
        events = memory_store.recent(owner=owner, limit=lim)
        return MemoryListResponse(
            events=[
                MemoryEventOut(
                    id=e.id,
                    ts=e.ts,
                    kind=e.kind,
                    content=e.content,
                    session_id=e.session_id,
                    meta=e.meta or None,
                )
                for e in events
            ]
        )

    @app.get("/v1/memory/search", response_model=MemoryListResponse)
    async def memory_search(request: Request, q: str, limit: int = 8, _: Any = auth, __: Any = rate):
        if not memory_store:
            raise HTTPException(status_code=400, detail="Memory is disabled")
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)
        lim = max(1, min(int(limit), 20))
        events = memory_store.search(owner=owner, query=q, limit=lim)
        return MemoryListResponse(
            events=[
                MemoryEventOut(
                    id=e.id,
                    ts=e.ts,
                    kind=e.kind,
                    content=e.content,
                    session_id=e.session_id,
                    meta=e.meta or None,
                )
                for e in events
            ]
        )

    @app.get("/v1/tools")
    async def list_tools(_: Any = auth, __: Any = rate):
        return {"tools": tools.list_specs()}

    @app.get("/v1/models")
    async def list_models(backend: str | None = None, _: Any = auth, __: Any = rate):
        """
        List available models based on current or requested backend.
        We return a unified list format.
        """
        # Allow UI to peek at models for a different backend before switching
        target_backend = backend or cfg.llm.backend
        models = []

        import time
        now = time.time()
        if target_backend in model_cache:
            ts, cached_models = model_cache[target_backend]
            if now - ts < CACHE_TTL:
                return {"models": cached_models, "backend": target_backend}

        if target_backend == "ollama":
            try:
                # Reuse logic or call strictly
                # We can't easily reuse cli logic without refactoring.
                # Just call Ollama API directly.
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{cfg.llm.ollama_base_url}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        for m in data.get("models", []):
                            models.append({"id": m["name"], "name": m["name"]})
            except Exception as e:
                print(f"[list_models] Ollama Error: {e}")
                pass
        
        elif target_backend in ("github", "openai"):
            base_url = cfg.llm.openai_base_url
            if target_backend == "github" and not base_url:
                base_url = "https://models.inference.ai.azure.com"
            elif not base_url:
                base_url = "https://api.openai.com/v1"

            token = cfg.llm.openai_api_key
            if target_backend == "github":
                if cfg.llm.github_token:
                     token = cfg.llm.github_token
                elif not token:
                     # Attempt load
                     try:
                        token = (Path("data") / "github_token.txt").read_text("utf-8").strip()
                     except Exception:
                        pass
            
            if token:
                try:
                    url = f"{base_url}/models"
                    if url.startswith("https://models.inference.ai.azure.com//"):
                         url = url.replace("//", "/")
                    
                    headers = {"Authorization": f"Bearer {token}"}
                    async with httpx.AsyncClient(timeout=5) as client:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            data = resp.json()
                            items = data if isinstance(data, list) else data.get("data", [])
                            for m in items:
                                # Start with name
                                name = m.get("name") or m.get("id")
                                # If name is mixed case, keep it. 
                                # The API returns mixed case names (Meta-Llama...)
                                # If the server expects lowercase, we might have issues, but short name is safer than URI.
                                
                                friendly = m.get("friendly_name")
                                label = f"{name} ({friendly})" if friendly else name
                                models.append({"id": name, "name": label})
                except Exception as e:
                    print(f"[list_models] Provider Error: {e}")
                    pass

        if models:
            model_cache[target_backend] = (time.time(), models)

        return {"models": models, "backend": target_backend}

    @app.post("/v1/system/model")
    async def set_model(req: SetModelRequest, _: Any = auth, __: Any = rate):
        # Update config object
        cfg.llm.backend = req.backend
        cfg.llm.model = req.model
        
        # Persist to file
        try:
            import yaml
            config_path = Path("config/alter.yaml")
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                
                # Ensure structure
                if "llm" not in data: data["llm"] = {}
                data["llm"]["backend"] = req.backend
                data["llm"]["model"] = req.model

                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, default_flow_style=False)
        except Exception as e:
            print(f"Failed to save config: {e}")
        
        # Rebuild LLM and update Agent
        try:
            new_llm = build_llm(cfg)
            # This is a bit hacky but works for local single-instance
            agent._llm = new_llm
            print(f"[Alter] Switched Model: {req.model} (Backend: {req.backend})")
            return {"ok": True, "model": req.model, "backend": req.backend}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/v1/system/auto_confirm")
    async def set_auto_confirm(request: Request, _: Any = auth, __: Any = rate):
        """Toggle auto-confirm for all tools at runtime."""
        body = await request.json()
        enabled = bool(body.get("enabled", False))

        # Update in-memory config
        cfg.security.auto_confirm_tools = enabled

        # Rebuild tool registry so tool.spec.confirm reflects the new value
        nonlocal tools
        new_tools = build_default_registry(cfg, agent._llm, auditor)
        tools = new_tools
        agent._tools = new_tools

        state = "ON (tools will auto-execute)" if enabled else "OFF (tools require confirmation)"
        print(f"[Alter] Auto-confirm: {state}")
        return {"ok": True, "auto_confirm_tools": enabled}

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, request: Request, _: Any = auth, __: Any = rate):
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)

        session_id = req.session_id or uuid.uuid4().hex
        session_key = f"{owner}:{session_id}"
        session = sessions.get(session_key)
        if not session:
            session = agent.new_session(owner=owner)
            sessions[session_key] = session

        try:
            result = session.run_turn(user_message=req.message)
        except Exception as e:
            return ChatResponse(reply=f"LLM/tooling error: {e}", session_id=session_id)
        if isinstance(result, FinalResponse):
            return ChatResponse(reply=result.content, session_id=session_id)

        return ChatResponse(
            reply=(
                f"Tool requested: {result.tool_id}\nReason: {result.reason}\n"
                f"Confirmation required: {result.confirm_required}\n"
                f"request_id: {result.request_id}"
            ),
            session_id=session_id,
            tool_request={
                "request_id": result.request_id,
                "tool_id": result.tool_id,
                "inputs": result.inputs,
                "reason": result.reason,
                "confirm_required": result.confirm_required,
            },
        )

    @app.post("/v1/tools/confirm", response_model=ChatResponse)
    async def confirm(req: ConfirmRequest, request: Request, _: Any = auth, __: Any = rate):
        candidate = request.headers.get("x-alter-key") or request.query_params.get("key")
        owner = AlterAgent.owner_from_secret(candidate)

        if not req.session_id:
            return ChatResponse(reply="Missing or invalid session_id.")
        session_key = f"{owner}:{req.session_id}"
        if session_key not in sessions:
            return ChatResponse(reply="Missing or invalid session_id.")
        session = sessions[session_key]
        try:
            out = session.confirm(request_id=req.request_id, allow=req.allow)
        except Exception as e:
            return ChatResponse(reply=f"LLM/tooling error: {e}", session_id=req.session_id)
        if isinstance(out, FinalResponse):
            return ChatResponse(reply=out.content, session_id=req.session_id)
        return ChatResponse(
            reply=(
                f"Tool requested: {out.tool_id}\nReason: {out.reason}\n"
                f"Confirmation required: {out.confirm_required}\n"
                f"request_id: {out.request_id}"
            ),
            session_id=req.session_id,
            tool_request={
                "request_id": out.request_id,
                "tool_id": out.tool_id,
                "inputs": out.inputs,
                "reason": out.reason,
                "confirm_required": out.confirm_required,
            },
        )

    @app.post("/v1/tools/execute", response_model=ToolExecuteResponse)
    async def tool_execute(req: ToolExecuteRequest, _: Any = auth, __: Any = rate):
        try:
            tool = tools.get(req.tool_id)
        except KeyError:
            return ToolExecuteResponse(status="error", stderr=f"Unknown tool: {req.tool_id}")

        # Validate inputs early.
        try:
            tools.validate_inputs(req.tool_id, req.inputs)
        except Exception as e:
            return ToolExecuteResponse(status="error", stderr=str(e))

        if tool.spec.confirm and not req.confirmed:
            request_id = uuid.uuid4().hex
            return ToolExecuteResponse(
                status="error",
                stderr="Confirmation required",
                confirmation_required=True,
                request_id=request_id,
            )

        exec_id = uuid.uuid4().hex
        auditor.log_event({"type": "tool_executing", "request_id": exec_id, "tool_id": req.tool_id})
        result = tools.execute(req.tool_id, req.inputs)
        auditor.log_event(
            {
                "type": "tool_result",
                "request_id": exec_id,
                "tool_id": req.tool_id,
                "status": result.status,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "artifacts": result.artifacts,
            }
        )
        return ToolExecuteResponse(
            status=result.status,
            stdout=result.stdout,
            stderr=result.stderr,
            artifacts=result.artifacts,
        )

    @app.websocket("/v1/events")
    async def events(ws: WebSocket):
        import asyncio
        from functools import partial

        # Browser-friendly websocket auth: query param `?key=...`.
        key = ws.query_params.get("key")
        if not is_valid_api_key(cfg, key):
            await ws.close(code=4401)
            return

        await ws.accept()
        owner = AlterAgent.owner_from_secret(key)
        session = agent.new_session(owner=owner)
        loop = asyncio.get_running_loop()

        # We need a way to maintain parser state across the sync callback.
        # Since on_token_sync is called by the thread, we can use a closure.
        # BUT: session.run_turn is called multiple times in a loop (potentially). 
        # We need a new parser for each run_turn? 
        # Actually, run_turn calls _plan_from_history which generates ONE response.
        # So we should reset the parser before calling run_turn.
        
        parser_ref = {"p": StreamingJsonParser()}

        def on_token_sync(token: str):
            # Parse token to extract content string only
            content = parser_ref["p"].consume(token)
            if content:
                coro = ws.send_json({"type": "token", "content": content})
                asyncio.run_coroutine_threadsafe(coro, loop)

        def on_tool_start_sync(tr: ToolRequest):
            coro = ws.send_json({
                "type": "tool_executing",
                "tool_id": tr.tool_id,
                "request_id": tr.request_id
            })
            asyncio.run_coroutine_threadsafe(coro, loop)

        def on_tool_progress_sync(message: str):
            coro = ws.send_json({
                "type": "tool_progress",
                "message": message
            })
            asyncio.run_coroutine_threadsafe(coro, loop)

        def on_tool_result_sync(tr: ToolRequest, result: Any):
            # result is ToolResult object (status, stdout, stderr, etc.)
            command_display = ""
            if tr.tool_id == "shell.run":
                prog = str(tr.inputs.get("program", ""))
                args = tr.inputs.get("args", [])
                if isinstance(args, list):
                    command_display = f"{prog} {' '.join(str(a) for a in args)}"
                else:
                    command_display = f"{prog}"

            # Build a displayable result string for non-shell tools
            result_text = ""
            raw_stdout = getattr(result, "stdout", "") or ""
            raw_stderr = getattr(result, "stderr", "") or ""
            artifacts = getattr(result, "artifacts", None)
            if raw_stdout.strip():
                result_text = raw_stdout
            elif artifacts:
                try:
                    result_text = json.dumps(artifacts, indent=2, default=str)
                except Exception:
                    result_text = str(artifacts)

            coro = ws.send_json({
                "type": "tool_result",
                "request_id": tr.request_id,
                "tool_id": tr.tool_id,
                "status": getattr(result, "status", "unknown"),
                "stdout": raw_stdout,
                "stderr": raw_stderr,
                "command": command_display,
                "result": result_text,
                "inputs": tr.inputs,
                "artifacts": artifacts,
            })
            asyncio.run_coroutine_threadsafe(coro, loop)

        try:
            while True:
                msg = await ws.receive_text()
                try:
                    data = json.loads(msg)
                except Exception:
                    await ws.send_json({"type": "error", "message": "Invalid JSON."})
                    continue

                mtype = data.get("type")
                if mtype == "chat":
                    user_message = str(data.get("message", "")).strip()
                    if not user_message:
                        await ws.send_json({"type": "error", "message": "Empty message."})
                        continue

                    try:
                        # Reset parser for new turn
                        parser_ref["p"] = StreamingJsonParser()
                        # Run blocking agent in threadpool
                        func = partial(
                            session.run_turn, 
                            user_message=user_message, 
                            on_token=on_token_sync,
                            on_tool_start=on_tool_start_sync,
                            on_tool_progress=on_tool_progress_sync,
                            on_tool_result=on_tool_result_sync
                        )
                        result = await loop.run_in_executor(None, func)
                    except Exception as e:
                        await ws.send_json(
                            {
                                "type": "error",
                                "message": f"LLM/tooling error: {e}",
                            }
                        )
                        continue
                    if isinstance(result, FinalResponse):
                        await ws.send_json({"type": "assistant", "content": result.content, "final": True})
                        continue

                    await ws.send_json(
                        {
                            "type": "tool_request",
                            "request_id": result.request_id,
                            "tool_id": result.tool_id,
                            "inputs": result.inputs,
                            "reason": result.reason,
                            "confirm_required": result.confirm_required,
                        }
                    )
                    continue

                if mtype == "confirm":
                    request_id = str(data.get("request_id", "")).strip()
                    allow = bool(data.get("allow", False))
                    
                    try:
                        func = partial(
                            session.confirm, 
                            request_id=request_id, 
                            allow=allow, 
                            on_token=on_token_sync,
                            on_tool_start=on_tool_start_sync,
                            on_tool_progress=on_tool_progress_sync,
                            on_tool_result=on_tool_result_sync
                        )
                        out = await loop.run_in_executor(None, func)
                    except Exception as e:
                        await ws.send_json({"type": "error", "message": f"LLM/tooling error: {e}"})
                        continue
                    if isinstance(out, FinalResponse):
                        await ws.send_json({"type": "assistant", "content": out.content, "final": True})
                    else:
                        await ws.send_json(
                            {
                                "type": "tool_request",
                                "request_id": out.request_id,
                                "tool_id": out.tool_id,
                                "inputs": out.inputs,
                                "reason": out.reason,
                                "confirm_required": out.confirm_required,
                            }
                        )
                    continue

                await ws.send_json({"type": "error", "message": f"Unknown message type: {mtype}"})

        except WebSocketDisconnect:
            return

    return app


def _read_ui_file(name: str) -> str:
    base = Path(__file__).resolve().parents[2] / "ui"
    return (base / name).read_text(encoding="utf-8")


def _read_ui_asset(asset_path: str) -> tuple[bytes, str]:
    base = Path(__file__).resolve().parents[2] / "ui"
    p = (base / asset_path).resolve()
    if base not in p.parents and p != base:
        return b"Not found", "text/plain"
    if not p.exists():
        return b"Not found", "text/plain"

    media = "application/octet-stream"
    if p.suffix == ".js":
        media = "text/javascript"
    elif p.suffix == ".css":
        media = "text/css"
    elif p.suffix == ".html":
        media = "text/html"
    return p.read_bytes(), media

from __future__ import annotations

from ...config import AlterConfig
from .base import Llm
from .echo import EchoLlm
from .llama_cpp import LlamaCppLlm
from .ollama import OllamaLlm


def build_llm(cfg: AlterConfig) -> Llm:
    backend = cfg.llm.backend
    if backend == "echo":
        return EchoLlm()
    if backend == "llama_cpp":
        if not cfg.llm.model_path:
            raise ValueError("llm.model_path must be set when llm.backend=llama_cpp")
        return LlamaCppLlm(model_path=cfg.llm.model_path)
    if backend == "ollama":
        return OllamaLlm(
            base_url=cfg.llm.ollama_base_url,
            model=cfg.llm.model,
            thinking_mode=cfg.llm.thinking_mode,
            timeout_s=cfg.llm.timeout_s,
            autostart=cfg.llm.ollama_autostart,
        )
    if backend == "openai" or backend == "github":
        # For GitHub Models, the generic endpoint is often: https://models.inference.ai.azure.com
        # But users can override it if they want.
        default_base_url = "https://api.openai.com/v1"
        if backend == "github":
            default_base_url = "https://models.inference.ai.azure.com"

        from .openai import OpenAILlm
        
        api_key = cfg.llm.openai_api_key
        if backend == "github":
            default_base_url = "https://models.inference.ai.azure.com"
            # Priority: 1. config.github_token, 2. data/github_token.txt, 3. config.openai_api_key
            if cfg.llm.github_token:
                api_key = cfg.llm.github_token
            elif not api_key:
                # Try loading from file
                try:
                    from pathlib import Path
                    token_path = Path("data") / "github_token.txt"
                    if token_path.exists():
                        api_key = token_path.read_text("utf-8").strip()
                except Exception:
                    pass

            if not api_key:
                 raise ValueError(
                    "GitHub backend requires a token. "
                    "Run `alter auth github` to authenticate, or set `llm.github_token` in config."
                )
        else:
             if not api_key:
                raise ValueError(f"llm.openai_api_key must be set when llm.backend={backend}")

        base_url = (cfg.llm.openai_base_url or default_base_url).rstrip("/")
        
        return OpenAILlm(
            api_key=api_key,
            model=cfg.llm.model or ("gpt-4o" if backend == "github" else "gpt-3.5-turbo"),
            base_url=base_url,
            timeout_s=cfg.llm.timeout_s,
            backend_name=backend,
        )
    raise ValueError(f"Unknown llm.backend: {backend}")

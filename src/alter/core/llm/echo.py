from __future__ import annotations

from .base import Llm, ModelInfo


class EchoLlm(Llm):
    def model_info(self) -> ModelInfo:
        return ModelInfo(backend="echo", model_path=None)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        # Deterministic, offline-safe backend for smoke tests.
        # It does NOT do tool calling; it just responds plainly.
        return (
            "Echo backend (no model configured).\n\n"
            "Configure a real local model (llama.cpp) to enable tool calling.\n\n"
            f"You said:\n{user_prompt}"
        )


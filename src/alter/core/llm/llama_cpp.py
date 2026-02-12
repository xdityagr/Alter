from __future__ import annotations

from .base import Llm, ModelInfo


class LlamaCppLlm(Llm):
    def __init__(self, *, model_path: str):
        if not model_path:
            raise ValueError("model_path is required for llama_cpp backend")

        try:
            from llama_cpp import Llama  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "llama-cpp-python is not installed. Install extras: `pip install -e '.[llama-cpp]'`"
            ) from e

        self._model_path = model_path
        self._llm = Llama(model_path=model_path, n_ctx=4096)

    def model_info(self) -> ModelInfo:
        return ModelInfo(backend="llama_cpp", model_path=self._model_path)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        prompt = f"{system_prompt}\n\n{user_prompt}"
        out = self._llm(prompt, max_tokens=512, temperature=0.2)
        return (out["choices"][0]["text"] or "").strip()


from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from .base import Llm, ModelInfo


@dataclass(frozen=True)
class OllamaModel:
    name: str
    size: int | None = None  # bytes


def choose_best_model(models: list[OllamaModel]) -> str | None:
    """
    Heuristic chooser for a good general-purpose *local* model.

    Notes:
    - Filters out obvious cloud variants (":cloud" or "-cloud") and models with unknown size.
    - Prefers stronger instruction/general models; uses size as a tie-breaker.
    """
    candidates: list[OllamaModel] = []
    for m in models:
        n = m.name.lower()
        if ":cloud" in n or n.endswith("-cloud") or "-cloud" in n:
            continue
        if m.size is None:
            continue
        candidates.append(m)

    if not candidates:
        return None

    def weight(name: str) -> int:
        n = name.lower()
        # Rough ordering for agent-style usage.
        if "deepseek-coder-v2" in n:
            return 130
        if "deepseek-coder" in n:
            return 125
        if "deepseek-r1" in n:
            return 115
        if "qwen2.5-coder" in n:
            return 114
        if n.startswith("qwen2.5:"):
            return 112
        if n.startswith("gpt-oss:"):
            return 110
        if n.startswith("llama3.1:") or n.startswith("llama3.2:") or n.startswith("llama3:"):
            return 108
        if n.startswith("gemma3:") or n.startswith("gemma:"):
            return 98
        if n.startswith("mistral:") or n.startswith("mixtral:"):
            return 95
        return 80

    def score(m: OllamaModel) -> float:
        size_gb = (m.size or 0) / (1024**3)
        # Keep the formula simple and stable; size is only a tie-breaker.
        return weight(m.name) * 10.0 + min(size_gb, 40.0)

    best = max(candidates, key=score)
    return best.name


class OllamaLlm(Llm):
    def __init__(
        self,
        *,
        base_url: str,
        model: str | None,
        thinking_mode: str = "auto",
        timeout_s: int = 120,
        autostart: bool = True,
    ):
        self._base_url = base_url.rstrip("/")
        self._thinking_mode = thinking_mode
        self._timeout_s = timeout_s
        self._autostart = autostart
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s))

        if model:
            self._model = model
        else:
            self._model = self._auto_pick_model()
            if not self._model:
                raise RuntimeError(
                    "No local Ollama models detected. Run `ollama pull <model>` (e.g., `ollama pull llama3.1:8b`)."
                )

    def _ping(self) -> None:
        resp = self._client.get(f"{self._base_url}/api/version")
        resp.raise_for_status()

    def _ensure_running(self) -> None:
        try:
            self._ping()
            return
        except Exception:
            pass

        if not self._autostart:
            raise RuntimeError(
                f"Ollama is not reachable at {self._base_url}. Start Ollama (Windows app) or run `ollama serve`."
            )

        self._try_start_ollama()
        # Retry a few times while it boots.
        last_err: Exception | None = None
        # Increase wait to ~15 seconds (30 * 0.5s) as Windows startup can be slow
        for _ in range(30):
            try:
                self._ping()
                return
            except Exception as e:
                last_err = e
                import time

                time.sleep(0.5)

        raise RuntimeError(
            f"Ollama autostart attempted but still not reachable at {self._base_url}. Error: {last_err}"
        )

    def _try_start_ollama(self) -> None:
        import shutil
        import subprocess

        exe = shutil.which("ollama")
        if not exe:
            raise RuntimeError(
                "Ollama autostart is enabled but `ollama` executable was not found on PATH. "
                "Install Ollama or add it to PATH."
            )

        # Best-effort. If Ollama is already running, this may fail harmlessly.
        creationflags = 0
        try:
            # Windows detach flags, if available
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        except Exception:
            creationflags = 0
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)

    def _auto_pick_model(self) -> str | None:
        tags = self.list_models()
        return choose_best_model(tags)

    def list_models(self) -> list[OllamaModel]:
        self._ensure_running()
        try:
            resp = self._client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise RuntimeError(
                "Could not reach Ollama. Make sure the Ollama app/service is running and reachable at "
                f"{self._base_url}. Error: {e}"
            ) from e

        out: list[OllamaModel] = []
        for m in (data.get("models") or []):
            name = m.get("name")
            if not name:
                continue
            out.append(OllamaModel(name=str(name), size=m.get("size")))
        return out

    def model_info(self) -> ModelInfo:
        return ModelInfo(backend="ollama", model_path=self._model)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self._ensure_running()
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "num_ctx": 8192,
            },
        }

        try:
            resp = self._client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Ollama request failed for model {self._model}: {e}") from e

        msg = (data.get("message") or {}).get("content")
        if not msg:
            return ""
        return str(msg).strip()

    def generate_stream(self, *, system_prompt: str, user_prompt: str) -> Iterator[str]:
        import json

        self._ensure_running()
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "num_ctx": 8192,
            },
        }

        if self._thinking_mode in ("low", "medium", "high"):
            payload["options"]["think"] = self._thinking_mode

        try:
            with self._client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        chunk = (obj.get("message") or {}).get("content")
                        if chunk:
                            yield chunk
                    except Exception:
                        pass
        except Exception as e:
            raise RuntimeError(f"Ollama stream failed for model {self._model}: {e}") from e

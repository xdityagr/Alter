from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from .base import Llm, ModelInfo


@dataclass(frozen=True)
class OpenAILlm(Llm):
    """
    LLM backend using OpenAI-compatible API (ChatGPT, GitHub Models, etc.).
    """
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_s: int = 120
    backend_name: str = "openai"

    def __post_init__(self):
        # We use a client created on demand or cached? 
        # Since dataclass is frozen, we can't easily store the client if we want immutability.
        # But for Llm protocol, we can just create it.
        # Actually, let's just make it a normal class if we need state, but Llm impls are classes.
        # But dataclass is convenient.
        pass

    @property
    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(self.timeout_s),
            http2=False,
        )

    def model_info(self) -> ModelInfo:
        return ModelInfo(backend=self.backend_name, model_path=self.model)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }

        import time
        retries = 3
        backoff = 2.0

        for attempt in range(retries + 1):
            try:
                with self._client as client:
                    resp = client.post("/chat/completions", json=payload)
                    if resp.status_code == 429:
                        if attempt < retries:
                            print(f"[OpenAI] Rate limit hit (429). Retrying in {backoff}s...")
                            time.sleep(backoff)
                            backoff *= 2
                            continue
                        else:
                            raise RuntimeError("Rate limit exceeded (429) after retries.")
                    
                    if resp.is_error:
                        print(f"DEBUG: API Error {resp.status_code}: {resp.text}")
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return content or ""
            except Exception as e:
                # If it's a 429 that raised an exception (not caught above), handle it?
                # logic above handles status_code 429 explicit check.
                # If network error, maybe retry too? For now, just 429.
                if attempt == retries:
                     raise RuntimeError(f"OpenAI/GitHub API request failed: {e}") from e
                # Fallthrough to retry?? No, only specific errors safe to retry.
                # Assuming simple 429 handling is enough.
                raise

    def generate_stream(self, *, system_prompt: str, user_prompt: str) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 4096,
            "stream": True,
        }

    def generate_stream(self, *, system_prompt: str, user_prompt: str) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 4096,
            "stream": True,
        }

        import time
        retries = 3
        backoff = 2.0

        for attempt in range(retries + 1):
            try:
                with self._client as client:
                    # Context manager for stream
                    with client.stream("POST", "/chat/completions", json=payload) as resp:
                        if resp.status_code == 429:
                            if attempt < retries:
                                print(f"[OpenAI] Stream Rate limit hit (429). Retrying in {backoff}s...")
                                time.sleep(backoff)
                                backoff *= 2
                                continue
                            else:
                                raise RuntimeError("Rate limit exceeded (429) after retries.")

                        if resp.is_error:
                             # Read the response to see why
                             err_text = resp.read().decode("utf-8")
                             print(f"DEBUG: Stream API Error {resp.status_code}: {err_text}")
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            # OpenAI stream format: "data: {...}"
                            if line.startswith("data:"):
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk_obj = json.loads(data_str)
                                    choices = chunk_obj.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content")
                                        finish_reason = choices[0].get("finish_reason")
                                        if finish_reason and finish_reason != "stop":
                                            # print(f"DEBUG: Stream finished with reason: {finish_reason}")
                                            pass
                                        
                                        if content:
                                            yield content
                                except Exception:
                                    pass
                        return # Success
            except Exception as e:
                # If we yielded content, we can't retry easily without duplication.
                # But typically 429 happens at the start of the stream.
                if attempt == retries:
                    raise RuntimeError(f"OpenAI/GitHub API stream failed: {e}") from e
                # Only retry if we haven't yielded anything yet? 
                # This simple loop assumes exception happens during connection init or headers.
                # If iter_lines fails mid-stream, retrying the whole thing might duplicate.
                # But since we use 'yield', we can't easily restart unless we buffer. 
                # For 429, it usually fails immediately.
                if "429" in str(e):
                     if attempt < retries:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                raise

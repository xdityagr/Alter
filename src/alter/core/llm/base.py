from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass(frozen=True)
class ModelInfo:
    backend: str
    model_path: str | None = None


class Llm(Protocol):
    def model_info(self) -> ModelInfo: ...

    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...

    def generate_stream(self, *, system_prompt: str, user_prompt: str) -> Iterator[str]: ...


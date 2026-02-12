from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str | None = None
    tool_request: dict | None = None


class ConfirmRequest(BaseModel):
    request_id: str
    allow: bool
    session_id: str | None = None


class ToolExecuteRequest(BaseModel):
    tool_id: str = Field(min_length=1)
    inputs: dict = Field(default_factory=dict)
    # For confirmation-gated tools, this must be true.
    confirmed: bool = False


class ToolExecuteResponse(BaseModel):
    status: str
    stdout: str = ""
    stderr: str = ""
    artifacts: dict | None = None
    confirmation_required: bool = False
    request_id: str | None = None


class SetModelRequest(BaseModel):
    backend: str
    model: str


class MemoryRememberRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    meta: dict | None = None


class MemoryRememberResponse(BaseModel):
    ok: bool = True
    mem_id: str
    ts: str


class MemorySummarizeResponse(BaseModel):
    ok: bool = True
    mem_id: str
    ts: str
    content: str


class MemoryEventOut(BaseModel):
    id: str
    ts: str
    kind: str
    content: str
    session_id: str | None = None
    meta: dict | None = None


class MemoryListResponse(BaseModel):
    events: list[MemoryEventOut]


class ProfileResponse(BaseModel):
    owner: str
    lines: list[str]
    evidence: dict

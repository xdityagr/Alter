from __future__ import annotations

from dataclasses import dataclass

from alter.core.agent import Agent, FinalResponse, ToolRequest
from alter.core.audit import Auditor
from alter.core.llm.base import Llm, ModelInfo
from alter.core.tools.base import Tool, ToolResult, ToolSpec
from alter.core.tools.registry import ToolRegistry


@dataclass
class FakeLlm(Llm):
    outputs: list[str]
    i: int = 0

    def model_info(self) -> ModelInfo:
        return ModelInfo(backend="fake", model_path=None)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        out = self.outputs[min(self.i, len(self.outputs) - 1)]
        self.i += 1
        return out


def test_session_auto_executes_non_confirm_tool(tmp_path):
    reg = ToolRegistry()
    reg.register(
        Tool(
            spec=ToolSpec(
                id="demo.ok",
                name="Demo OK",
                description="returns ok",
                inputs_schema={"type": "object", "properties": {}, "additionalProperties": False},
                confirm=False,
            ),
            action=lambda _: ToolResult(status="ok", stdout="hi"),
        )
    )
    llm = FakeLlm(
        outputs=[
            '{"type":"tool","tool_id":"demo.ok","inputs":{},"reason":"need it"}',
            '{"type":"final","content":"done"}',
        ]
    )
    agent = Agent(llm=llm, tools=reg, auditor=Auditor(path=tmp_path / "audit.jsonl"))
    session = agent.new_session()
    out = session.run_turn(user_message="do thing")
    assert isinstance(out, FinalResponse)
    assert out.content == "done"


def test_session_returns_confirm_tool_request(tmp_path):
    reg = ToolRegistry()
    reg.register(
        Tool(
            spec=ToolSpec(
                id="demo.danger",
                name="Demo Danger",
                description="confirm required",
                inputs_schema={"type": "object", "properties": {}, "additionalProperties": False},
                confirm=True,
            ),
            action=lambda _: ToolResult(status="ok", stdout="danger"),
        )
    )
    llm = FakeLlm(outputs=['{"type":"tool","tool_id":"demo.danger","inputs":{},"reason":"need it"}'])
    agent = Agent(llm=llm, tools=reg, auditor=Auditor(path=tmp_path / "audit.jsonl"))
    session = agent.new_session()
    out = session.run_turn(user_message="do risky")
    assert isinstance(out, ToolRequest)
    assert out.tool_id == "demo.danger"


def test_launcher_open_missing_target_does_not_autofill_from_last_user(tmp_path):
    reg = ToolRegistry()
    reg.register(
        Tool(
            spec=ToolSpec(
                id="launcher.open",
                name="Launch App/File",
                description="Open a file/app",
                inputs_schema={
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                    "additionalProperties": False,
                },
                confirm=False,
            ),
            action=lambda _: (_ for _ in ()).throw(AssertionError("launcher.open should not execute")),
        )
    )
    llm = FakeLlm(
        outputs=[
            '{"type":"tool","tool_id":"launcher.open","inputs":{},"reason":"open"}',
            '{"type":"final","content":"repaired"}',
        ]
    )
    agent = Agent(llm=llm, tools=reg, auditor=Auditor(path=tmp_path / "audit.jsonl"))
    session = agent.new_session()
    out = session.run_turn(user_message="Yes please go on?")
    assert isinstance(out, FinalResponse)
    assert out.content == "repaired"


def test_launcher_open_missing_target_recovers_from_recent_artifact_path(tmp_path):
    reg = ToolRegistry()

    reg.register(
        Tool(
            spec=ToolSpec(
                id="fs.write",
                name="Write File",
                description="write",
                inputs_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                confirm=False,
            ),
            action=lambda inputs: ToolResult(status="ok", artifacts={"path": inputs["path"]}),
        )
    )

    opened: list[str] = []

    def _open(inputs):
        opened.append(str(inputs["target"]))
        return ToolResult(status="ok", stdout="opened")

    reg.register(
        Tool(
            spec=ToolSpec(
                id="launcher.open",
                name="Launch App/File",
                description="Open a file/app",
                inputs_schema={
                    "type": "object",
                    "properties": {"target": {"type": "string"}},
                    "required": ["target"],
                    "additionalProperties": False,
                },
                confirm=False,
            ),
            action=_open,
        )
    )

    llm = FakeLlm(
        outputs=[
            '{"type":"tool","tool_id":"fs.write","inputs":{"path":"leave_application.docx","content":"x"},"reason":"write file"}',
            '{"type":"tool","tool_id":"launcher.open","inputs":{},"reason":"open it"}',
            '{"type":"final","content":"done"}',
        ]
    )
    agent = Agent(llm=llm, tools=reg, auditor=Auditor(path=tmp_path / "audit.jsonl"))
    session = agent.new_session()
    out = session.run_turn(user_message="write and open")
    assert isinstance(out, FinalResponse)
    assert out.content == "done"
    assert opened
    assert opened[-1].lower().endswith("leave_application.docx")

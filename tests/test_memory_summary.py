import json
from dataclasses import dataclass

from alter.core.llm.base import ModelInfo
from alter.core.memory import MemoryEvent, build_rolling_summary


@dataclass(frozen=True)
class FakeLlm:
    reply: str

    def model_info(self) -> ModelInfo:
        return ModelInfo(backend="fake", model_path=None)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return self.reply

    def generate_stream(self, *, system_prompt: str, user_prompt: str):
        yield self.reply


def test_build_rolling_summary_requires_valid_evidence_ids():
    events = [
        MemoryEvent(id="a1", ts="t1", owner="o", session_id=None, kind="user", content="hello", meta={}),
        MemoryEvent(id="b2", ts="t2", owner="o", session_id=None, kind="tool", content="stdout=ok", meta={}),
    ]
    llm = FakeLlm(
        reply=json.dumps(
            {
                "summary": [
                    {"text": "valid line", "evidence": ["a1"]},
                    {"text": "invalid line", "evidence": ["does-not-exist"]},
                ],
                "open_questions": [{"text": "q", "evidence": ["b2"]}],
                "next_actions": [],
            }
        )
    )
    out = build_rolling_summary(llm=llm, owner="o", source_events=events)
    assert out is not None
    assert [x["text"] for x in out["summary"]] == ["valid line"]
    assert out["open_questions"][0]["evidence"] == ["b2"]


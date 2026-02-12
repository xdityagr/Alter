from alter.config import AlterConfig
from alter.core.tools.defaults import build_default_registry


def test_tool_registry_lists_defaults():
    reg = build_default_registry(AlterConfig())
    specs = reg.list_specs()
    tool_ids = {s["id"] for s in specs}
    assert "fs.read" in tool_ids
    assert "fs.rename" in tool_ids
    assert "shell.run" in tool_ids

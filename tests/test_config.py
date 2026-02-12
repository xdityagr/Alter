from alter.config import load_config


def test_load_config_defaults_when_missing(tmp_path):
    loaded = load_config(tmp_path / "missing.yaml")
    assert loaded.config.ui.port == 8080
    assert loaded.config.llm.backend in {"echo", "llama_cpp"}


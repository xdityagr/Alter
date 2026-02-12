from alter.config import AlterConfig
from alter.core.server.auth import is_valid_api_key


def test_is_valid_api_key_disabled_allows_anything():
    cfg = AlterConfig()
    cfg.security.require_api_key = False
    assert is_valid_api_key(cfg, None) is True
    assert is_valid_api_key(cfg, "anything") is True


def test_is_valid_api_key_single_key():
    cfg = AlterConfig()
    cfg.security.require_api_key = True
    cfg.security.api_key = "one"
    cfg.security.api_keys = []
    assert is_valid_api_key(cfg, "one") is True
    assert is_valid_api_key(cfg, "two") is False
    assert is_valid_api_key(cfg, None) is False


def test_is_valid_api_key_multi_keys_ignores_single_key():
    cfg = AlterConfig()
    cfg.security.require_api_key = True
    cfg.security.api_key = "one"
    cfg.security.api_keys = ["a", "b"]
    assert is_valid_api_key(cfg, "a") is True
    assert is_valid_api_key(cfg, "b") is True
    assert is_valid_api_key(cfg, "one") is False


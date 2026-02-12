from __future__ import annotations

from fastapi import Depends, HTTPException, Query, status
from fastapi.params import Header

from ...config import AlterConfig


def is_valid_api_key(cfg: AlterConfig, candidate: str | None) -> bool:
    if not cfg.security.require_api_key:
        return True
    if not candidate:
        return False
    keys = [k for k in (cfg.security.api_keys or []) if k]
    if keys:
        return candidate in keys
    return candidate == cfg.security.api_key


def require_api_key(cfg: AlterConfig):
    """
    Browser-friendly auth: accept either:
    - header: X-Alter-Key
    - query:  ?key=

    WebSockets cannot set custom headers in browsers, so we also accept `?key=`.
    """

    async def _dep(
        x_alter_key: str | None = Header(default=None),
        key: str | None = Query(default=None),
    ) -> None:
        candidate = x_alter_key or key
        if not is_valid_api_key(cfg, candidate):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key",
            )

    return Depends(_dep)

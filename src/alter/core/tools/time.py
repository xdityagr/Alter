from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from .base import Tool, ToolResult, ToolSpec


@dataclass(frozen=True)
class _TimeResult:
    iso: str
    tz: str
    utc_offset: str
    unix: int


def _parse_utc_offset(s: str) -> timezone | None:
    s = (s or "").strip().upper()
    if not s:
        return None

    # Accept: "UTC+05:30", "UTC-8", "+05:30", "-0800"
    if s.startswith("UTC"):
        s = s[3:].strip()
    if s in {"Z", "+0", "+00", "+00:00", "-0", "-00", "-00:00", ""}:
        return timezone.utc

    sign = 1
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        sign = -1
        s = s[1:]

    s = s.replace(":", "")
    if not s.isdigit():
        return None

    if len(s) <= 2:
        hh = int(s)
        mm = 0
    elif len(s) == 4:
        hh = int(s[:2])
        mm = int(s[2:])
    else:
        return None

    if hh > 23 or mm > 59:
        return None
    return timezone(sign * timedelta(hours=hh, minutes=mm))


def _resolve_tz(*, tz: str | None, place: str | None, utc_offset: str | None) -> tuple[timezone | Any, str]:
    if utc_offset:
        z = _parse_utc_offset(utc_offset)
        if z is not None:
            return z, f"UTC{utc_offset}"

    if tz:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(tz), tz
        except Exception:
            pass

    p = (place or "").strip().lower()
    if p:
        aliases = {
            "california": "America/Los_Angeles",
            "los angeles": "America/Los_Angeles",
            "la": "America/Los_Angeles",
            "pacific": "America/Los_Angeles",
            "pst": "America/Los_Angeles",
            "pdt": "America/Los_Angeles",
            "new york": "America/New_York",
            "ny": "America/New_York",
            "eastern": "America/New_York",
            "est": "America/New_York",
            "edt": "America/New_York",
            "india": "Asia/Kolkata",
            "ist": "Asia/Kolkata",
            "uk": "Europe/London",
            "london": "Europe/London",
            "utc": "UTC",
            "gmt": "UTC",
        }
        if p in aliases:
            target = aliases[p]
            if target == "UTC":
                return timezone.utc, "UTC"
            try:
                from zoneinfo import ZoneInfo

                return ZoneInfo(target), target
            except Exception:
                pass

        # Try treating it as an offset like "UTC+5:30"
        z = _parse_utc_offset(p)
        if z is not None:
            return z, f"UTC{p}"

        # Try IANA as-is (capitalization matters; use original place)
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(place.strip()), place.strip()
        except Exception:
            pass

    # Local timezone
    return datetime.now().astimezone().tzinfo, "local"


def make_time_now_tool() -> Tool:
    spec = ToolSpec(
        id="time.now",
        name="Current Time",
        description="Get the current time (optionally in a given timezone/place).",
        inputs_schema={
            "type": "object",
            "properties": {
                "tz": {"type": "string", "description": "IANA timezone, e.g. America/Los_Angeles"},
                "place": {"type": "string", "description": "Place/alias like 'California', 'IST', 'UTC+05:30'"},
                "utc_offset": {"type": "string", "description": "UTC offset like '+05:30' or '-0800'"},
            },
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        tz = inputs.get("tz")
        place = inputs.get("place")
        utc_offset = inputs.get("utc_offset")

        resolved_tz, label = _resolve_tz(tz=tz, place=place, utc_offset=utc_offset)
        now = datetime.now(resolved_tz).astimezone(resolved_tz)
        unix = int(now.timestamp())

        offset = now.strftime("%z")
        offset = offset[:3] + ":" + offset[3:] if len(offset) == 5 else offset
        tzname = getattr(resolved_tz, "key", None) or str(now.tzname() or label)

        out = _TimeResult(
            iso=now.isoformat(timespec="seconds"),
            tz=tzname,
            utc_offset=offset,
            unix=unix,
        )

        return ToolResult(
            status="ok",
            stdout=f"{out.iso} ({out.tz}, UTC{out.utc_offset})",
            artifacts={"iso": out.iso, "tz": out.tz, "utc_offset": out.utc_offset, "unix": out.unix},
        )

    return Tool(spec=spec, action=action)


"""Ticket 07: best-effort ops observability (sanitized JSONL events + tail reader).

All writes are best-effort and fail-safe: unknown event kinds no-op, and any
failure (missing home, disk error, permissions) is swallowed so ops events can
never break callers.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: §19 event family (20 kinds). Emitting any other kind is a no-op.
OPS_EVENT_KINDS: tuple[str, ...] = (
    "profile_loaded",
    "profile_validation_failed",
    "runtime_created",
    "cache_hit",
    "cache_miss",
    "skills_resolved",
    "tools_resolved",
    "memory_recall",
    "memory_candidate_created",
    "memory_candidate_promoted",
    "memory_candidate_rejected",
    "tool_permission_denied",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "worker_started",
    "worker_completed",
    "worker_failed",
    "worker_cancelled",
    "checkpoint_resumed",
)

# Key names (case-folded) containing any of these hints get their value
# redacted — keeps credential/memory-content/prompt/args-style fields out of
# the JSONL no matter what fields an emitter passes.
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "credential",
    "content",
    "prompt",
    "text",
    "args",
)

_MAX_STRING_CHARS = 200
_MAX_EVENT_LINE_BYTES = 4096
_LINE_CAP_ATTEMPTS = 12
_READ_WINDOW_BYTES = 256 * 1024
_META_KEYS = ("ts", "kind")

_LOCK = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _events_path(user_home: Path | str | None = None) -> Path:
    if user_home is None:
        from src.project_paths import user_home as _default_home

        user_home = _default_home()
    return Path(user_home) / "ops" / "events.jsonl"


def _is_secret_key(key: Any) -> bool:
    k = str(key).casefold()
    return any(hint in k for hint in _SECRET_KEY_HINTS)


def _sanitize_node(value: Any) -> Any:
    """Redact secret-looking keys; truncate long strings. Recursive."""
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            out[k] = "<redacted>" if _is_secret_key(k) else _sanitize_node(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_node(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STRING_CHARS:
        return value[:_MAX_STRING_CHARS] + f"…(+{len(value) - _MAX_STRING_CHARS} chars)"
    return value


def _halve_once(record: dict) -> int:
    """Halve every non-meta string value longer than 1 char (any depth).

    Returns the number of strings changed (0 = nothing left to shrink).
    """
    changed: list[int] = [0]

    def walk(obj: Any, top_level: bool) -> None:
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                v = obj[k]
                if top_level and str(k) in _META_KEYS:
                    continue
                if isinstance(v, str):
                    if len(v) > 1:
                        obj[k] = v[: max(1, len(v) // 2)]
                        changed[0] += 1
                elif isinstance(v, (dict, list)):
                    walk(v, False)
        elif isinstance(obj, list):
            for i in range(len(obj)):
                v = obj[i]
                if isinstance(v, str):
                    if len(v) > 1:
                        obj[i] = v[: max(1, len(v) // 2)]
                        changed[0] += 1
                elif isinstance(v, (dict, list)):
                    walk(v, False)

    walk(record, True)
    return changed[0]


def _enforce_line_cap(record: dict) -> dict:
    """Bounded shrink: halve all long strings per round until the encoded
    line fits _MAX_EVENT_LINE_BYTES."""
    for _ in range(_LINE_CAP_ATTEMPTS):
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        if len(line.encode("utf-8")) <= _MAX_EVENT_LINE_BYTES:
            break
        if _halve_once(record) == 0:
            break
    return record


def ops_event(kind: str, **fields: Any) -> None:
    """Append one ops event to <JARVIS_HOME>/ops/events.jsonl.

    Best-effort by design: unknown kind is a no-op and every failure is
    swallowed, so this always returns None and never raises.
    """
    try:
        if kind not in OPS_EVENT_KINDS:
            return
        record: dict = {"ts": _utc_now_iso(), "kind": kind, **fields}
        record = _enforce_line_cap(_sanitize_node(record))
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        pass


def read_ops_events(
    user_home: Path | str | None = None, limit: int = 50
) -> list[dict]:
    """Tail-read ops events; last `limit` records, chronological order.

    Reads at most the last 256 KB of the file; when the file is bigger the
    first in-window line is dropped (it may be truncated). Bad JSON lines
    are skipped. Absent home/file returns []. Never raises.
    """
    try:
        path = _events_path(user_home)
        if not path.is_file():
            return []
        data = path.read_bytes()
        window = data[-_READ_WINDOW_BYTES:]
        lines = window.decode("utf-8", "replace").splitlines()
        if len(data) > _READ_WINDOW_BYTES and lines:
            lines = lines[1:]
        events: list[dict] = []
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events if limit is None else events[-limit:]
    except Exception:
        return []
"""Permission hooks（对标 Codex hook_runtime，Hooks → permissions → Modal）。

javis.json hooks.permission 配置外部命令；stdin 收 JSON，stdout 返 decision。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.permissions import GATED_TOOLS
from src.tool_call import arg_value, command

VALID_HOOK_DECISIONS = frozenset({"allow", "deny", "ask"})


@dataclass(frozen=True)
class PermissionHookRule:
    match: str
    command: tuple[str, ...]
    timeout: float = 10.0
    cwd: str | None = None


def parse_permission_hooks(hooks_cfg: object, *, project_root: Path | None = None) -> list[PermissionHookRule]:
    """解析 javis.json hooks.permission 列表。"""
    if not isinstance(hooks_cfg, dict):
        return []
    raw = hooks_cfg.get("permission")
    if not isinstance(raw, list):
        return []
    rules: list[PermissionHookRule] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        match = str(item.get("match", "")).strip()
        cmd = item.get("command")
        if not match or not isinstance(cmd, list) or not cmd:
            continue
        timeout = item.get("timeout", 10.0)
        try:
            timeout_f = float(timeout)
        except (TypeError, ValueError):
            timeout_f = 10.0
        cwd = item.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            cwd_path = Path(cwd)
            if not cwd_path.is_absolute() and project_root:
                cwd_path = (project_root / cwd).resolve()
            cwd_s = str(cwd_path)
        else:
            cwd_s = str(project_root) if project_root else None
        rules.append(
            PermissionHookRule(
                match=match,
                command=tuple(str(c) for c in cmd),
                timeout=timeout_f,
                cwd=cwd_s,
            )
        )
    return rules


def hook_match_value(tool: str, args: dict) -> str:
    """构造 hook 匹配用的 value（与 permissions 规则集同形）。"""
    if tool == "execute":
        return command(args)
    return arg_value(args, "file_path", "path", "pattern", "command")


def hook_matches(rule: PermissionHookRule, tool: str, value: str) -> bool:
    """匹配 hook 规则：'execute:git push*' / 'execute git push*' / 'write_file:/vault/*' / '*'。"""
    pattern = rule.match.strip()
    if ":" in pattern:
        tool_part, _, value_part = pattern.partition(":")
        tool_part = tool_part.strip()
        value_part = value_part.strip() or "*"
        if tool_part != "*" and tool_part != tool:
            return False
        return _fnmatch(value_part, value)
    parts = pattern.split(None, 1)
    if len(parts) == 2 and parts[0] in GATED_TOOLS:
        if parts[0] != tool:
            return False
        return _fnmatch(parts[1], value)
    if pattern in GATED_TOOLS:
        return pattern == tool
    if pattern == "*":
        return tool in GATED_TOOLS
    return _fnmatch(pattern, value)


def _fnmatch(pattern: str, value: str) -> bool:
    from fnmatch import fnmatch

    return fnmatch(value, pattern)


def build_hook_payload(
    *,
    tool: str,
    args: dict,
    thread_id: str = "",
    project_root: str | None = None,
) -> dict:
    return {
        "tool": tool,
        "args": args or {},
        "path": hook_match_value(tool, args or {}),
        "thread_id": thread_id,
        "project_root": project_root,
    }


def run_permission_hook(rule: PermissionHookRule, payload: dict) -> tuple[str, str]:
    """执行 hook 命令，返回 (decision, message)。失败回落 ask。"""
    try:
        proc = subprocess.run(
            list(rule.command),
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=rule.timeout,
            cwd=rule.cwd,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "ask", f"permission hook 失败（{exc}），回落 ask"

    raw = (proc.stdout or "").strip()
    if not raw:
        return "ask", "permission hook 无输出，回落 ask"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "ask", f"permission hook 输出非 JSON：{raw[:120]}"
    decision = str(data.get("decision", "ask")).lower()
    if decision not in VALID_HOOK_DECISIONS:
        return "ask", f"permission hook decision 无效：{decision}"
    message = str(data.get("message") or data.get("reason") or "")
    return decision, message


def resolve_permission_hook(
    rules: list[PermissionHookRule],
    tool: str,
    args: dict,
    *,
    thread_id: str = "",
    project_root: Path | None = None,
) -> tuple[str, str] | None:
    """按配置顺序匹配第一条 hook；无匹配返回 None。"""
    if tool not in GATED_TOOLS or not rules:
        return None
    value = hook_match_value(tool, args or {})
    root_s = str(project_root) if project_root else None
    payload = build_hook_payload(
        tool=tool,
        args=args or {},
        thread_id=thread_id,
        project_root=root_s,
    )
    matched: PermissionHookRule | None = None
    for rule in rules:
        if hook_matches(rule, tool, value):
            matched = rule
            break
    if matched is None:
        return None
    decision, message = run_permission_hook(matched, payload)
    return decision, message


def summarize_permission_hooks(rules: list[PermissionHookRule]) -> str:
    if not rules:
        return "permission hooks: 0"
    lines = [f"permission hooks: {len(rules)}"]
    for i, rule in enumerate(rules, 1):
        cmd = " ".join(rule.command)
        lines.append(f"  [{i}] match={rule.match!r} cmd={cmd!r}")
    return "\n".join(lines)

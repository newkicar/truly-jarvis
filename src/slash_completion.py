"""Slash 命令补全。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    name: str
    usage: str
    summary: str


SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "/help", "显示完整命令帮助"),
    SlashCommand("/exit", "/exit", "退出 JARVIS"),
    SlashCommand("/sessions", "/sessions", "列出历史会话"),
    SlashCommand("/delete-session", "/delete-session [id]", "删除历史会话（可写序号）"),
    SlashCommand("/copy-session", "/copy-session", "复制当前会话 ID"),
    SlashCommand("/history", "/history", "当前会话边界点时间线"),
    SlashCommand("/replay", "/replay <id>", "从 checkpoint 重跑"),
    SlashCommand("/fork", "/fork <id>", "从 checkpoint 分叉新会话"),
    SlashCommand("/snapshot", "/snapshot", "记录项目 git 文件快照"),
    SlashCommand("/snapshots", "/snapshots", "列出 git 文件快照"),
    SlashCommand("/rollback", "/rollback <id>", "回退项目文件并还原 Inbox"),
    SlashCommand("/reload-schedules", "/reload-schedules", "热重载定时任务配置"),
)


def slash_query(value: str, cursor: int | None = None) -> tuple[int, str] | None:
    """行首 / 命令补全：返回 (slash_index, query)。"""
    pos = len(value) if cursor is None else cursor
    text = value[:pos]
    if not text.startswith("/"):
        return None
    if " " in text:
        return None
    return 0, text[1:]


def filter_commands(
    commands: tuple[SlashCommand, ...] | None = None,
    query: str = "",
    *,
    limit: int = 20,
) -> list[SlashCommand]:
    pool = list(commands or SLASH_COMMANDS)
    q = query.casefold()
    if not q:
        return pool[:limit]
    matched = [c for c in pool if q in c.name[1:].casefold() or q in c.usage.casefold()]
    return matched[:limit]

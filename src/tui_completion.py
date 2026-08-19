"""TUI 输入补全状态（@ 路径 + / 命令）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.path_completion import PathSuggestion, at_query, collect_completion_paths
from src.slash_completion import SlashCommand, filter_commands, slash_query


@dataclass(frozen=True)
class SuggestionItem:
    insert: str
    label: str
    hint: str


@dataclass(frozen=True)
class OverlayState:
    kind: Literal["path", "slash", "none"]
    at_index: int
    items: tuple[SuggestionItem, ...]

    @property
    def active(self) -> bool:
        return self.kind != "none" and bool(self.items)


def resolve_overlay_state(
    value: str,
    cursor: int,
    *,
    vault_path,
    workspace_root,
    memories_root,
) -> OverlayState:
    slash = slash_query(value, cursor)
    if slash is not None and (cursor == len(value) or value[:cursor].strip() == value[:cursor]):
        _idx, query = slash
        commands = filter_commands(query=query)
        items = tuple(
            SuggestionItem(insert=c.usage, label=c.usage, hint=c.summary) for c in commands
        )
        return OverlayState(kind="slash", at_index=0, items=items)

    at_ctx = at_query(value, cursor)
    if at_ctx is not None:
        at_index, query = at_ctx
        suggestions = collect_completion_paths(
            vault_path,
            workspace_root,
            memories_root,
            query=query,
        )
        items = tuple(
            SuggestionItem(insert=s.path, label=s.path, hint=s.hint) for s in suggestions
        )
        return OverlayState(kind="path", at_index=at_index, items=items)

    return OverlayState(kind="none", at_index=0, items=())


def apply_suggestion(value: str, at_index: int, cursor: int, insert: str) -> tuple[str, int]:
    replacement = insert if insert.endswith(" ") else f"{insert} "
    new_value = value[:at_index] + replacement + value[cursor:]
    new_cursor = at_index + len(replacement)
    return new_value, new_cursor

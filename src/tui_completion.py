"""TUI 输入补全状态（@ 路径 + / 命令）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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


def _real_path_for(item_path: str, path_mapping: dict[str, str] | None) -> str | None:
    """item_path 为虚拟前缀形式（/workspace/x、/vault/x …）时返回映射后的真实路径。

    前缀按长度倒序匹配；非虚拟路径或 mapping 未覆盖时返回 None。
    """
    if not path_mapping:
        return None
    for prefix in sorted(
        (p for p in path_mapping if p.startswith("/")), key=len, reverse=True
    ):
        if item_path.startswith(prefix):
            root = path_mapping[prefix]
            rel = item_path[len(prefix) :]
            return str(Path(root) / rel) if rel else str(Path(root))
    return None


def _style_item(
    s: PathSuggestion,
    path_mapping: dict[str, str] | None,
    at_reference_style: str,
) -> SuggestionItem:
    """#04: 按 at_reference_style 生成补全条目（缺省 "virtual" 保持旧行为）。

    dual = 标签/插入值保持虚拟路径，hint 追加真实路径；
    real = 插入值与标签改为真实磁盘路径（#10 起文件工具本就接受真实路径），hint 提示虚拟路径。
    """
    if at_reference_style == "virtual":
        return SuggestionItem(insert=s.path, label=s.path, hint=s.hint)
    real = _real_path_for(s.path, path_mapping)
    if at_reference_style == "real":
        if real:
            return SuggestionItem(insert=real, label=real, hint=f"虚拟路径 {s.path}")
        return SuggestionItem(insert=s.path, label=s.path, hint=s.hint)
    # dual
    if real:
        hint = f"{s.hint} · {real}" if s.hint else real
        return SuggestionItem(insert=s.path, label=s.path, hint=hint)
    return SuggestionItem(insert=s.path, label=s.path, hint=s.hint)

def resolve_overlay_state(
    value: str,
    cursor: int,
    *,
    vault_path,
    workspace_root,
    memories_root,
    path_mapping: dict[str, str] | None = None,
    at_reference_style: str = "virtual",
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
            _style_item(s, path_mapping, at_reference_style) for s in suggestions
        )
        return OverlayState(kind="path", at_index=at_index, items=items)

    return OverlayState(kind="none", at_index=0, items=())


def apply_suggestion(value: str, at_index: int, cursor: int, insert: str) -> tuple[str, int]:
    replacement = insert if insert.endswith(" ") else f"{insert} "
    new_value = value[:at_index] + replacement + value[cursor:]
    new_cursor = at_index + len(replacement)
    return new_value, new_cursor

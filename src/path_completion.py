"""@ 文件路径补全（vault Inbox 优先，可选 workspace）。"""
from __future__ import annotations

from pathlib import Path

_SKIP_DIR_NAMES = frozenset({".git", ".obsidian", "node_modules", "__pycache__"})


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in rel.parts[:-1])


def _scan_md_paths(root: Path, prefix: str) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    for file_path in root.rglob("*.md"):
        if not file_path.is_file() or _should_skip(file_path, root):
            continue
        rel = file_path.relative_to(root).as_posix()
        out.append(f"{prefix}{rel}")
    return out


def sort_paths_inbox_first(paths: list[str]) -> list[str]:
    def _key(path: str) -> tuple[int, str]:
        if path.startswith("/vault/Inbox/"):
            return (0, path.casefold())
        if path.startswith("/vault/Reports/"):
            return (1, path.casefold())
        if path.startswith("/vault/"):
            return (2, path.casefold())
        return (3, path.casefold())

    return sorted(paths, key=_key)


def collect_completion_paths(
    vault_path: Path | None,
    workspace_root: Path | None,
    *,
    include_workspace: bool = True,
) -> list[str]:
    paths: list[str] = []
    if vault_path is not None:
        paths.extend(_scan_md_paths(vault_path, "/vault/"))
    if include_workspace and workspace_root is not None:
        paths.extend(_scan_md_paths(workspace_root, "/workspace/"))
    return sort_paths_inbox_first(paths)


def at_query(value: str, cursor: int | None = None) -> tuple[int, str] | None:
    """若光标处于 @ 补全上下文，返回 (at_index, query)。"""
    pos = len(value) if cursor is None else cursor
    at = value.rfind("@", 0, pos)
    if at == -1:
        return None
    if at > 0 and not value[at - 1].isspace():
        return None
    query = value[at + 1 : pos]
    if any(ch.isspace() for ch in query):
        return None
    return at, query


def filter_paths(paths: list[str], query: str, *, limit: int = 50) -> list[str]:
    q = query.casefold()
    if not q:
        return paths[:limit]
    matched = [p for p in paths if q in p.casefold()]
    return matched[:limit]


def apply_completion(value: str, at_index: int, cursor: int, selected: str) -> tuple[str, int]:
    """把 @query 替换为选中路径，末尾补空格。"""
    replacement = selected if selected.endswith(" ") else f"{selected} "
    new_value = value[:at_index] + replacement + value[cursor:]
    new_cursor = at_index + len(replacement)
    return new_value, new_cursor

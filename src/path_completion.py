"""@ 文件路径补全（workspace 优先，vault 可选）。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SKIP_DIR_NAMES = frozenset({".git", ".obsidian", "node_modules", "__pycache__", ".venv", "venv"})
_BINARY_SUFFIXES = frozenset({
    ".xlsx", ".xls", ".xlsm", ".docx", ".doc", ".pptx", ".ppt",
    ".pdf", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib",
    ".db", ".sqlite", ".sqlite3",
})
_VAULT_SUFFIXES = frozenset({".md"})


@dataclass(frozen=True)
class PathSuggestion:
    path: str
    hint: str


def _should_skip(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in rel.parts[:-1])


def _scan_paths(root: Path, prefix: str, suffixes: frozenset[str] | None = None, *, cap: int = 500) -> list[str]:
    """扫描目录下所有文件。suffixes=None 时不过滤后缀（fuzzy search）。"""
    if not root.is_dir():
        return []
    out: list[str] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file() or _should_skip(file_path, root):
            continue
        if suffixes is not None and file_path.suffix.lower() not in suffixes:
            continue
        rel = file_path.relative_to(root).as_posix()
        out.append(f"{prefix}{rel}")
        if len(out) >= cap:
            break
    return out


def sort_path_suggestions(items: list[PathSuggestion]) -> list[PathSuggestion]:
    def _key(item: PathSuggestion) -> tuple[int, str]:
        path = item.path
        if path.startswith("/workspace/"):
            return (0, path.casefold())
        if path.startswith("/memories/"):
            return (1, path.casefold())
        if path.startswith("/vault/Inbox/"):
            return (2, path.casefold())
        if path.startswith("/vault/Reports/"):
            return (3, path.casefold())
        if path.startswith("/vault/"):
            return (4, path.casefold())
        return (5, path.casefold())

    return sorted(items, key=_key)


def _parse_at_scope(query: str) -> tuple[str, str]:
    """返回 (scope, local_query)。scope: workspace | vault | memories | all"""
    q = query
    if q.startswith("vault/") or q.startswith("vault"):
        rest = q[5:] if q.startswith("vault/") else q[4:].lstrip("/")
        return "vault", rest.lstrip("/")
    if q.startswith("mem/") or q.startswith("memories/"):
        if q.startswith("memories/"):
            return "memories", q[len("memories/") :]
        return "memories", q[len("mem/") :]
    if q.startswith("workspace/") or q.startswith("ws/"):
        prefix_len = len("workspace/") if q.startswith("workspace/") else len("ws/")
        return "workspace", q[prefix_len:]
    return "all", q


def collect_completion_paths(
    vault_path: Path | None,
    workspace_root: Path | None,
    memories_root: Path | None = None,
    *,
    query: str = "",
    include_vault: bool = True,
    limit: int = 200,
) -> list[PathSuggestion]:
    scope, local_q = _parse_at_scope(query)
    items: list[PathSuggestion] = []

    if scope in ("all", "workspace") and workspace_root is not None:
        for path in _scan_paths(workspace_root, "/workspace/"):
            hint = "项目"
            suffix = Path(path).suffix.lower()
            if suffix in _BINARY_SUFFIXES:
                hint = "项目 [binary]"
            items.append(PathSuggestion(path, hint))

    if scope in ("all", "memories") and memories_root is not None:
        for path in _scan_paths(memories_root, "/memories/", _VAULT_SUFFIXES, cap=100):
            items.append(PathSuggestion(path, "记忆"))

    if include_vault and scope in ("all", "vault") and vault_path is not None:
        for path in _scan_paths(vault_path, "/vault/", _VAULT_SUFFIXES):
            hint = "知识库"
            if path.startswith("/vault/Inbox/"):
                hint = "Inbox"
            elif path.startswith("/vault/Reports/"):
                hint = "Reports"
            items.append(PathSuggestion(path, hint))

    sorted_items = sort_path_suggestions(items)
    if local_q:
        return filter_path_suggestions(sorted_items, local_q, limit=limit)
    return sorted_items[:limit]


def sort_paths_inbox_first(paths: list[str]) -> list[str]:
    """兼容旧 API：字符串列表排序（workspace 优先）。"""
    items = [PathSuggestion(p, "") for p in paths]
    return [i.path for i in sort_path_suggestions(items)]


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


def filter_path_suggestions(
    items: list[PathSuggestion], query: str, *, limit: int = 50
) -> list[PathSuggestion]:
    q = query.casefold()
    if not q:
        return items[:limit]
    matched = [item for item in items if q in item.path.casefold()]
    return matched[:limit]


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

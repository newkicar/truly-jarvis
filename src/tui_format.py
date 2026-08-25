"""TUI 消息/审批格式化（Rich markup + Markdown，CLI+TUI 共用纯函数）。"""
from __future__ import annotations

from pathlib import Path

from rich.markdown import Markdown

from src.commands import ToolInvocation

TOOL_PREVIEW_MAX_LINES = 10
PERMISSION_DIFF_MAX_LINES = 30
DEFAULT_TUI_THEME = "textual-dark"
LEGACY_BAD_THEMES = frozenset({"ansi-light"})


def truncate_lines(text: str, max_lines: int = TOOL_PREVIEW_MAX_LINES) -> str:
    """截断为多行预览（≤ max_lines）。"""
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    kept = lines[:max_lines]
    return "\n".join(kept) + f"\n…（共 {len(lines)} 行，已截断）"


def render_markdown(text: str) -> Markdown:
    """Rich Markdown 渲染对象（供 RichLog.write 使用）。"""
    return Markdown(text or "")


def system_message_markup(text: str) -> str:
    """系统/启动提示（muted）。"""
    return f"[dim]{text}[/dim]"


def user_message_markup(text: str) -> str:
    """用户消息：左侧 cyan 竖线 + 标题「你」（RichLog markup，不用 Panel）。"""
    body = text.replace("\n", "\n  ")
    return f"[bold cyan]▌[/bold cyan] [bold]你[/bold]\n  {body}\n"


def ai_message_header_markup() -> str:
    """AI 消息标题行。"""
    return "[bold blue]▌[/bold blue] [bold]JARVIS[/bold]"


def ai_typing_markup() -> str:
    return "[dim italic]▌ JARVIS 正在思考…[/dim italic]"


SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
BLOCK_SPINNER_FRAMES = ("■", "⬝")
SPINNER_TEXT = "思考中..."


def spinner_line(frame_index: int, *, animations: bool = True, style: str = "braille") -> str:
    """spinner 一行的 markup：帧轮播；animations=False 降级静态 ⋯。"""
    if not animations:
        return f"[warning]⋯[/warning] {SPINNER_TEXT}"
    frames = BLOCK_SPINNER_FRAMES if style == "blocks" else SPINNER_FRAMES
    frame = frames[frame_index % len(frames)]
    return f"[warning]{frame}[/warning] {SPINNER_TEXT}"


def ai_stream_renderable(body: str):
    """流式 AI 回答：标题 + 增量 Markdown（供 Static/RichLog 渲染）。"""
    from rich.console import Group
    from rich.text import Text

    header = Text.from_markup(ai_message_header_markup())
    content = body if body else "…"
    return Group(header, Markdown(content))


class AiStreamThrottler:
    """节流 Rich 重绘，避免每个 token 触发全量 Markdown 排版。"""

    def __init__(self, interval: float = 0.12):
        self.interval = interval
        self.buffer = ""
        self._last_refresh = 0.0

    def reset(self) -> None:
        self.buffer = ""
        self._last_refresh = 0.0

    def append(self, delta: str) -> None:
        self.buffer += delta

    def due(self) -> bool:
        import time

        if not self.buffer:
            return False
        now = time.monotonic()
        return now - self._last_refresh >= self.interval

    def mark_refreshed(self) -> None:
        import time

        self._last_refresh = time.monotonic()


def format_tool_call(
    name: str,
    args: str,
    *,
    error: bool = False,
    output: str | None = None,
    indent: int = 0,
) -> str:
    """格式化工具调用行 + 可选结果预览（Rich markup 字符串）。"""
    prefix = "  " * indent
    tag = "✗" if error else "✓"
    header = f"{prefix}[dim]{tag} {name}({args[:80]})[/dim]"
    if not output:
        return header
    preview = truncate_lines(str(output).replace("\r\n", "\n"))
    indented = "\n".join(f"{prefix}  {line}" for line in preview.splitlines())
    return f"{header}\n{indented}"


def resolve_virtual_path(path: str, *, vault_path: Path | None, workspace_root: Path) -> Path | None:
    """把 /vault/ /workspace/ 虚拟路径解析为本地 Path。"""
    norm = path.replace("\\", "/")
    if norm.startswith("/vault/"):
        if vault_path is None:
            return None
        return vault_path / norm[len("/vault/") :].lstrip("/")
    if norm.startswith("/workspace/"):
        return workspace_root / norm[len("/workspace/") :].lstrip("/")
    if norm.startswith("/memories/"):
        return None
    p = Path(path)
    return p if p.is_absolute() and p.exists() else None


def read_local_file_text(local: Path | None) -> str | None:
    if local is None or not local.is_file():
        return None
    try:
        return local.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def proposed_file_content(inv: ToolInvocation, before: str | None) -> str:
    """根据工具参数推断写入/编辑后的文件内容。"""
    args = inv.args or {}
    if inv.name == "write_file":
        return str(args.get("content") or args.get("text") or "")
    if inv.name == "edit_file":
        old = str(args.get("old_string") or args.get("old_text") or "")
        new = str(args.get("new_string") or args.get("new_text") or args.get("replacement") or "")
        base = before if before is not None else ""
        if old and old in base:
            return base.replace(old, new, 1)
        if args.get("content") or args.get("text"):
            return str(args.get("content") or args.get("text"))
        return base
    if inv.name == "delete":
        return ""
    return ""


def format_file_diff(
    before: str | None,
    after: str,
    *,
    path: str,
    max_lines: int = PERMISSION_DIFF_MAX_LINES,
) -> str:
    """新建文件摘要或 unified diff 预览。"""
    import difflib

    if before is None:
        header = f"新建文件: {path}\n\n"
        body = after if after else "（空文件）"
        return header + truncate_lines(body, max_lines=max_lines)

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    if after and not after_lines:
        after_lines = [""]

    diff_lines = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"{path} (当前)",
            tofile=f"{path} (修改后)",
            lineterm="",
        )
    )
    if not diff_lines:
        return f"文件: {path}\n（内容无变化）"
    return truncate_lines("\n".join(diff_lines), max_lines=max_lines)


def permission_preview(
    inv: ToolInvocation, *, vault_path: Path | None = None, workspace_root: Path | None = None
) -> str:
    """权限 Modal 中间区预览：execute 显示命令，write/edit 显示 diff。"""
    args = inv.args or {}
    if inv.name == "execute":
        cmd = inv.path or str(args.get("command", args.get("cmd", "")))
        return truncate_lines(cmd, max_lines=20)

    if inv.name in ("write_file", "edit_file", "delete"):
        path = inv.path or str(args.get("file_path") or args.get("path") or "")
        before: str | None = None
        if path and vault_path and workspace_root:
            local = resolve_virtual_path(path, vault_path=vault_path, workspace_root=workspace_root)
            before = read_local_file_text(local)

        if inv.name == "delete":
            if before is not None:
                header = f"将删除: {path}\n\n"
                return header + truncate_lines(before, max_lines=PERMISSION_DIFF_MAX_LINES)
            return f"将删除: {path or '（未指定路径）'}"

        after = proposed_file_content(inv, before)
        if inv.name == "write_file" and before is None:
            return format_file_diff(None, after, path=path or "（未指定路径）")
        if before is not None:
            return format_file_diff(before, after, path=path or "（未指定路径）")
        return format_file_diff(None, after, path=path or "（未指定路径）")

    lines = [f"{k}: {str(v)[:120]}" for k, v in args.items()]
    return "\n".join(lines) if lines else "（无参数）"


def format_todos_panel(todos: list[dict] | None) -> str:
    """TUI 任务列表面板（write_todos / state.todos）。"""
    if not todos:
        return ""
    lines = ["[bold dim]Tasks[/bold dim]"]
    icons = {"pending": "○", "in_progress": "◐", "completed": "●"}
    for item in todos:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending")
        icon = icons.get(status, "○")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if status == "completed":
            lines.append(f"  [strike dim]{icon} {content}[/strike dim]")
        elif status == "in_progress":
            lines.append(f"  [bold]{icon} {content}[/bold]")
        else:
            lines.append(f"  {icon} {content}")
    return "\n".join(lines) if len(lines) > 1 else ""


# 兼容旧引用
def user_message_panel(text: str) -> str:
    return user_message_markup(text)


def ai_message_panel(text: str) -> Markdown:
    return render_markdown(text)

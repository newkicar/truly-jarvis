"""TUI 消息/审批格式化（Rich markup + Markdown，CLI+TUI 共用纯函数）。"""
from __future__ import annotations

from pathlib import Path

from rich.markdown import Markdown

from src.commands import ToolInvocation

TOOL_PREVIEW_MAX_LINES = 10
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


def resolve_virtual_path(path: str, *, vault_path: Path, workspace_root: Path) -> Path | None:
    """把 /vault/ /workspace/ 虚拟路径解析为本地 Path。"""
    norm = path.replace("\\", "/")
    if norm.startswith("/vault/"):
        return vault_path / norm[len("/vault/") :].lstrip("/")
    if norm.startswith("/workspace/"):
        return workspace_root / norm[len("/workspace/") :].lstrip("/")
    if norm.startswith("/memories/"):
        return None
    p = Path(path)
    return p if p.is_absolute() and p.exists() else None


def permission_preview(
    inv: ToolInvocation, *, vault_path: Path | None = None, workspace_root: Path | None = None
) -> str:
    """权限 Modal 中间区预览：execute 显示命令，write/edit 显示内容摘要。"""
    args = inv.args or {}
    if inv.name == "execute":
        cmd = inv.path or str(args.get("command", args.get("cmd", "")))
        return truncate_lines(cmd, max_lines=20)

    if inv.name in ("write_file", "edit_file", "delete"):
        content = (
            args.get("content")
            or args.get("new_string")
            or args.get("new_text")
            or args.get("text")
            or args.get("replacement")
            or ""
        )
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        if not content and inv.path and vault_path and workspace_root:
            local = resolve_virtual_path(inv.path, vault_path=vault_path, workspace_root=workspace_root)
            if local and local.is_file():
                try:
                    content = local.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
        header = f"文件: {inv.path}\n" if inv.path else ""
        body = truncate_lines(str(content)) if content else "（无内容预览，请查看 Path）"
        return header + body

    lines = [f"{k}: {str(v)[:120]}" for k, v in args.items()]
    return "\n".join(lines) if lines else "（无参数）"


# 兼容旧引用
def user_message_panel(text: str) -> str:
    return user_message_markup(text)


def ai_message_panel(text: str) -> Markdown:
    return render_markdown(text)

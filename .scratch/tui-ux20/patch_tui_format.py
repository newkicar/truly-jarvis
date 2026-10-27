import io
p = r"D:\Python Project\truly-jarvis-main\src\tui_format.py"
s = io.open(p, encoding="utf-8").read()

old_sig = '''def format_tool_call(
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
    # 参数/输出是用户不可信文本：先 escape，避免 [ ' = 序列被 Rich markup
    # 解析（崩溃.txt：Label/Static/RichLog 把 pandas 式命令渲染炸掉）。
    header = f"{prefix}[dim]{tag} {escape(name)}({escape(args[:80])})[/dim]"
    if not output:
        return header
    preview = truncate_lines(str(output).replace("\\r\\n", "\\n"))
    indented = "\\n".join(f"{prefix}  {escape(line)}" for line in preview.splitlines())
    return f"{header}\\n{indented}"'''

new_sig = '''def format_tool_call(
    name: str,
    args: str,
    *,
    error: bool = False,
    output: str | None = None,
    indent: int = 0,
    detail: bool = False,
) -> str:
    """格式化工具调用行 + 可选结果预览（Rich markup 字符串）。

    detail=True 时末尾追加一行「＋ 详情（点击展开/收起）」标记行
    （TUI CopyableRichLog 点击该行展开完整参数/输出，对标 codex/opencode）。
    """
    prefix = "  " * indent
    tag = "✗" if error else "✓"
    # 参数/输出是用户不可信文本：先 escape，避免 [ ' = 序列被 Rich markup
    # 解析（崩溃.txt：Label/Static/RichLog 把 pandas 式命令渲染炸掉）。
    header = f"{prefix}[dim]{tag} {escape(name)}({escape(args[:80])})[/dim]"
    result = header
    if output:
        preview = truncate_lines(str(output).replace("\\r\\n", "\\n"))
        indented = "\\n".join(f"{prefix}  {escape(line)}" for line in preview.splitlines())
        result = f"{header}\\n{indented}"
    if detail:
        result = f"{result}\\n{prefix}[dim italic]＋ 详情（点击展开/收起）[/dim italic]"
    return result'''

assert old_sig in s, "old format_tool_call not found"
s = s.replace(old_sig, new_sig, 1)

anchor = "def resolve_virtual_path("
new_blocks = '''TOOL_DETAIL_ARG_CAP = 500
TOOL_DETAIL_OUT_CAP_LINES = 200
REASONING_DISPLAY_CAP_LINES = 30


def tool_detail_block(
    name: str,
    args: str,
    *,
    error: bool = False,
    output: str | None = None,
    indent: int = 0,
    arg_cap: int = TOOL_DETAIL_ARG_CAP,
    out_cap_lines: int = TOOL_DETAIL_OUT_CAP_LINES,
) -> str:
    """展开态工具调用详情块：完整参数（超 cap 截断）+ 完整输出（超行数截断）
    + 末尾「＋ 收起（点击收起）」标记行。供 CopyableRichLog 点击展开时重写。"""
    prefix = "  " * indent
    tag = "✗" if error else "✓"
    lines = [f"{prefix}[dim]{tag} {escape(name)}[/dim]"]
    full_args = args or ""
    if len(full_args) > arg_cap:
        shown = full_args[:arg_cap]
        lines.append(
            f"{prefix}[dim]  参数: {escape(shown)}…（截断，共 {len(full_args)} 字符）[/dim]"
        )
    else:
        lines.append(f"{prefix}[dim]  参数: {escape(full_args)}[/dim]")
    if output:
        out_text = str(output).replace("\\r\\n", "\\n")
        preview = truncate_lines(out_text, max_lines=out_cap_lines)
        indented = "\\n".join(f"{prefix}  {escape(line)}" for line in preview.splitlines())
        lines.append(f"{prefix}[dim]  输出:[/dim]")
        lines.append(indented if indented else f"{prefix}  [dim]（空）[/dim]")
    lines.append(f"{prefix}[dim italic]＋ 收起（点击收起）[/dim italic]")
    return "\\n".join(lines)


def reasoning_block_markup(text: str, *, cap: int = REASONING_DISPLAY_CAP_LINES) -> str:
    """Agent 思考（reasoning）内容块：💭 标题 + 两空格缩进淡色斜体正文。

    总是展开（无折叠）；超 cap 行截断并标注总行数。全部文本先 escape。
    """
    header = "[dim italic]💭 思考[/dim italic]"
    body_lines = (text or "").splitlines()
    if not body_lines:
        return header
    if len(body_lines) > cap:
        kept = body_lines[:cap]
        suffix = f"\\n  [dim italic]…（共 {len(body_lines)} 行，已截断）[/dim italic]"
    else:
        kept = body_lines
        suffix = ""
    body = "\\n".join(f"  [dim italic]{escape(line)}[/dim italic]" for line in kept)
    return f"{header}\\n{body}{suffix}"


'''
assert anchor in s
s = s.replace(anchor, new_blocks + anchor, 1)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("tui_format.py patched")

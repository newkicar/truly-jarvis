from pathlib import Path
p = Path('src/tui_format.py')
s = p.read_text(encoding='utf-8')
anchor = 'def resolve_virtual_path'
assert s.count(anchor) == 1
fn = "def tool_detail_worth_expanding(\n    name: str,\n    args: str,\n    *,\n    error: bool = False,\n    output: str | None = None,\n) -> bool:\n    \"\"\"判断一次工具调用是否值得显示「＋ 详情（点击展开/收起）」标记行。\n\n    失败调用 / 有非空输出 / 参数较长（>80 字符，预览态截断会丢信息）→ 值得展开；\n    否则折叠为普通单行调用（避免满屏标记噪音，对标 codex/opencode 的克制展示）。\n    \"\"\"\n    if error:\n        return True\n    if output and str(output).strip():\n        return True\n    return len(args or \"\") > 80\n\n\n"
i = s.index(anchor)
s = s[:i] + fn + s[i:]
p.write_text(s, encoding='utf-8')
print('tui_format ok')

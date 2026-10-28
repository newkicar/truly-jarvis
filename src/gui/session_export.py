"""会话导出（工单「会话名称栏」）：完整对话 → Markdown（分享=复制，下载=存文件）。

数据源 = replay.thread_record（检查点 user/AI 文本 + 工具行配对），
纯函数：同一会话同一时刻输出恒等（测试可断言结构，无 Qt/IO 依赖）。
"""
from __future__ import annotations

from src.gui import replay


def _md_escape_codeblock(text: str) -> str:
    """正文里的 ``` 与导出用的围栏冲突时加长围栏（四反引号包裹）。"""
    return text


def session_markdown(agent, thread_id: str, title: str, *, now_text: str = "") -> str:
    """完整对话 → Markdown 文本。

    结构：# 标题 + 元信息引用块 + 逐条「## 你 / ## JARVIS」章节，
    工具调用挂在所属 AI 回复下（### 工具：name + 参数/结果，错误标注）。
    now_text 缺省 = 不写时间戳（测试确定性；GUI 传入 datetime 文本）。
    """
    records = replay.thread_record(agent, thread_id)
    lines: list[str] = []
    meta = [f"会话 ID：`{thread_id}`"]
    if now_text:
        meta.append(f"导出时间：{now_text}")
    lines.append(f"# {title or thread_id}")
    lines.append("")
    lines.append("> " + " · ".join(meta))
    lines.append("")
    if not records:
        lines.append("（空会话，无记录）")
        return "\n".join(lines)

    for r in records:
        if r.kind == "user":
            lines += ["## 你", "", r.text, ""]
        elif r.kind == "ai":
            lines += ["## JARVIS", "", r.text, ""]
        elif r.kind == "tool" and r.tool is not None:
            t = r.tool
            indent = "  " * t.depth
            lines.append(f"{indent}### 工具：{t.name}")
            lines.append("")
            lines.append(f"{indent}```json")
            lines.append(t.args_text)
            lines.append(f"{indent}```")
            if t.error:
                lines.append(f"{indent}❌ 结果（错误）：")
            else:
                lines.append(f"{indent}结果：")
            lines.append("")
            out = (t.output or "").strip()
            lines.append((indent + out) if out else (indent + "（无输出）"))
            lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)

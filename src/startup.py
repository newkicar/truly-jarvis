"""启动信息格式化（CLI print / TUI RichLog 共用）。"""


def format_startup_lines(
    *,
    mcp_tool_count: int = 0,
    thread_id: str = "default",
    jobs: list | None = None,
) -> list[str]:
    """返回启动时应展示的信息行（不含 trailing 空行）。"""
    lines: list[str] = []
    if mcp_tool_count:
        lines.append(f"[MCP] 已加载 {mcp_tool_count} 个外部工具")
    if thread_id.startswith("session-"):
        lines.append(f"新会话: {thread_id}（指定 thread_id 可继续该会话）")
    jobs = jobs or []
    if jobs:
        lines.append(f"已注册 {len(jobs)} 个定时任务:")
        for job in jobs:
            trigger = getattr(job, "trigger", job)
            job_id = getattr(job, "id", str(job)).removeprefix("javis-")
            lines.append(f"  - {job_id}（{trigger}）")
    else:
        lines.append("（无定时任务）")
    return lines

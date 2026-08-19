"""命令分发与会话管理纯逻辑（CLI 与 TUI 共用）。

从 main.py 抽取：不依赖终端交互（无 input()/print()），
所有函数「接收 agent/thread_id → 返回文本」，可被 CLI 与 TUI 直接复用。
"""
from dataclasses import dataclass
from pathlib import Path

from src import time_travel

_HELP_COMMANDS = """\
命令：
  /exit           退出
  /sessions       列出历史会话
  /history        查看当前会话时间线（每轮提问/分叉，短 id 可用于回退）
  /replay <id>    从指定 checkpoint 重跑（支持短 id）
  /fork <id>      从指定 checkpoint 分叉出新分支（支持短 id）
  /snapshot       记录当前文件状态到当前 checkpoint（git 快照）
  /snapshots      列出文件快照（git）
  /rollback <id>  按 checkpoint 回退项目文件到对应 git 提交
  /reload-schedules  重载 schedules/*.json 定时任务配置（无需重启）
直接输入文字开始对话。
"""

CLI_HELP = (
    _HELP_COMMANDS
    + "审批操作时: [y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮)；\n"
    + "也可直接编辑 javis.json 的 permissions 段（allow/ask/deny）。\n"
)

TUI_HELP = (
    _HELP_COMMANDS
    + "HITL 审批时: 点击按钮选择（放行/永久放行/拒绝/编辑参数），Esc 放弃。\n"
)


@dataclass(frozen=True)
class ToolInvocation:
    """HITL 审批的工具调用信息（tool 名称 + 路径/命令 + 参数）。"""

    name: str
    path: str
    args: dict

    @classmethod
    def from_action(cls, action: dict) -> "ToolInvocation":
        """从 stream.interrupts 的 action_requests 项构造。"""
        name = action.get("name", "?")
        args = action.get("args", {})
        if name == "execute":
            path = str(args.get("command", args.get("cmd", "")))
        else:
            path = str(args.get("file_path", args.get("path", "")))
        return cls(name=name, path=path, args=args)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def content_to_text(content) -> str:
    """把 AI message content（str 或 content blocks 列表）转为可展示纯文本。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(str(block.get("text", "")))
                # tool_call / tool_use 等由 tool_calls 通道展示，跳过
        return "".join(parts)
    return str(content)


def render(messages) -> str:
    """取最后一条 AI 消息的可展示文本（忽略 tool_call blocks）。"""
    for msg in reversed(messages):
        if msg.type == "ai":
            return content_to_text(getattr(msg, "content", ""))
    return ""


def render_markdown(text: str):
    """Rich Markdown 渲染对象（供 TUI RichLog 使用）。"""
    from src.tui_format import render_markdown as _render_markdown

    return _render_markdown(text)


def checkpoint_short_id(cid: str) -> str:
    return cid[:13] if cid else cid


def boundary_checkpoints(agent, thread_id: str):
    """返回会话的「边界点」checkpoint，从旧到新。

    边界点 = source in (input, fork, update)，即每次用户提问 / 分叉 / 状态更新的
    起点；过滤掉中间的 loop 超步骤（工具调用、子代理等），避免 90+ 条噪音。
    """
    keep_sources = {"input", "fork", "update"}
    out = []
    try:
        for s in agent.get_state_history(config={"configurable": {"thread_id": thread_id}}):
            if (s.metadata or {}).get("source") in keep_sources:
                out.append(s)
    except Exception:
        return out
    out.reverse()  # get_state_history 从新到旧，反转成从旧到新
    return out


def resolve_checkpoint_id(agent, thread_id: str, raw: str):
    """把用户输入（完整 id 或短 id 前缀）解析成完整 checkpoint_id。

    短 id = cid[:13]（/history 显示用的短格式）。支持前缀唯一匹配；
    多个匹配返回 None，表示歧义。单次遍历完成精确 + 前缀匹配。
    """
    prefix_matches: list[str] = []
    for s in agent.get_state_history(config={"configurable": {"thread_id": thread_id}}):
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        if cid == raw:
            return cid
        if cid and cid.startswith(raw):
            prefix_matches.append(cid)
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return None


def last_human_text(values) -> str:
    """从 checkpoint 的 messages 里取最后一条用户消息文本（截断 50 字）。"""
    for msg in reversed(values.get("messages", [])):
        if getattr(msg, "type", "") == "human":
            content = getattr(msg, "content", "") or ""
            if isinstance(content, str):
                return content.strip().replace("\n", " ")[:50]
    return ""


def session_thread_ids(agent) -> list[str]:
    """从 checkpointer 拉取非 sched-* 的 thread_id 列表（供 TUI 侧边栏等）。"""
    checkpointer = getattr(agent, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return []
    rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()
    return [str(r[0]) for r in rows if not str(r[0]).startswith("sched-")]


def list_sessions(agent) -> str:
    threads = session_thread_ids(agent)
    checkpointer = getattr(agent, "checkpointer", None)
    if getattr(checkpointer, "conn", None) is None:
        return "（无 checkpointer，无法列出会话）"
    if not threads:
        return "（暂无历史会话）"
    return "历史会话:\n" + "\n".join(f"  - {t}" for t in threads)


def list_history(agent, thread_id: str) -> str:
    checkpoints = boundary_checkpoints(agent, thread_id)
    if not checkpoints:
        return "（暂无历史）"
    lines = []
    for i, s in enumerate(checkpoints):
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        src = (s.metadata or {}).get("source")
        step = s.metadata.get("step") if s.metadata else None
        short = checkpoint_short_id(cid)
        if src == "input":
            label = f"user: {last_human_text(s.values)}"
        elif src == "fork":
            label = f"分叉点 (step {step})"
        else:  # update
            label = f"状态更新 (step {step})"
        lines.append(f"  {i}. [{src:5s}] {label:<60} {short}")
    lines.append(
        "   → 用短 id（前 13 位）即可 /replay 或 /fork，如 /replay "
        + checkpoint_short_id(checkpoints[-1].config.get("configurable", {}).get("checkpoint_id", ""))
    )
    return "\n".join(lines)


def replay(agent, thread_id: str, checkpoint_id: str) -> str:
    full_id = resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if full_id is None:
        return f"重跑失败: 找不到 checkpoint {checkpoint_id}"
    prior = {"configurable": {"thread_id": thread_id, "checkpoint_id": full_id}}
    try:
        result = agent.invoke(None, config=prior)
    except Exception:
        return f"重跑失败: checkpoint {full_id}"
    return "重跑结果:\n" + render(result["messages"])


def fork(agent, thread_id: str, checkpoint_id: str):
    """从指定 checkpoint 分叉出新分支，返回 (提示文本, 新 thread_id 或 None)。"""
    base = {"configurable": {"thread_id": thread_id}}
    full_id = resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if full_id is None:
        return f"分叉失败: 找不到 checkpoint {checkpoint_id}", None
    try:
        target = None
        found_terminal = False
        for s in agent.get_state_history(config=base):
            if s.config["configurable"].get("checkpoint_id") == full_id:
                if s.next:
                    target = s
                else:
                    found_terminal = True
                break
        if target is None and found_terminal:
            # 目标 checkpoint 是终态（无待续节点），回退到最近有 pending 的节点
            for s in agent.get_state_history(config=base):
                if s.next:
                    target = s
                    break
        if target is None:
            return f"分叉失败: 找不到 checkpoint {full_id}", None
        new_config = agent.update_state(
            target.config,
            values=target.values,
            as_node="model",
        )
    except Exception:
        return f"分叉失败: checkpoint {full_id}", None
    new_thread = new_config["configurable"]["thread_id"]
    return f"已从 {full_id} 分叉（保留原历史），当前会话 {new_thread}", new_thread


def snapshot(agent, thread_id: str) -> str:
    state = agent.get_state({"configurable": {"thread_id": thread_id}})
    cid = state.config.get("configurable", {}).get("checkpoint_id")
    if not cid:
        return "快照失败: 无法确定当前 checkpoint"
    commit = time_travel.snapshot(project_root(), thread_id, cid)
    if commit is None:
        return "项目文件无变更，未产生快照"
    return f"已记录文件快照: checkpoint {cid} -> {commit}"


def list_snapshots() -> str:
    rows = time_travel.list_snapshots(project_root())
    if not rows:
        return "（暂无文件快照）"
    lines = ["文件快照 (从旧到新):"]
    for i, (cid, tid, commit, ts) in enumerate(rows):
        short_cid = checkpoint_short_id(cid)
        lines.append(
            f"  {i}. [{ts}]  commit {commit[:10]}  thread: {tid}  {short_cid}"
        )
    lines.append(
        "   → 用短 cid（前 13 位）即可 /rollback，如 /rollback "
        + checkpoint_short_id(rows[-1][0])
    )
    return "\n".join(lines)


def rollback(agent, thread_id: str, checkpoint_id: str, vault_path: Path | None = None) -> str:
    full_id = resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if not full_id:
        return f"回退失败: 未找到 checkpoint {checkpoint_id}"

    lines: list[str] = []
    commit = time_travel.resolve_commit(project_root(), full_id)
    if commit is None:
        lines.append(f"未找到 checkpoint {checkpoint_id} 的项目 git 快照（跳过项目文件回退）")
    else:
        time_travel.rollback_commit(project_root(), commit)
        lines.append(f"已回退项目文件到 {commit}（checkpoint {full_id}）")

    if vault_path is not None:
        from src import inbox_snapshots

        actions = inbox_snapshots.restore_inbox_for_rollback(
            project_root(), vault_path, agent, thread_id, full_id
        )
        if actions:
            lines.append("Inbox/Reports 还原:")
            for vp, action in actions:
                lines.append(f"  - {action} {vp}")
        else:
            lines.append("Inbox/Reports：该会话无需要还原的文件")

    lines.append("注意：可用 /replay 对齐会话状态。")
    return "\n".join(lines)


def current_permissions(permission_state: dict) -> dict:
    """把内存 permission_state 还原成 javis.json 的 permissions 配置 dict。

    state 结构: {"default": rule, "tools": {tool: rule}}；
    default 视为 "*" 键，tools 里与 default 相同的规则可省略（保持文件简洁）。
    """
    out: dict = {}
    default = permission_state["default"]
    if default != "ask":
        out["*"] = default
    for tool, rule in permission_state["tools"].items():
        if rule == default:
            continue
        out[tool] = rule
    return out


def always_approve(permission_state: dict, tool: str) -> bool:
    """把某 gated 工具设为 allow 并持久化到 javis.json（always approve 入口）。

    返回 True 表示已持久化；False 表示该工具不在 gated 列表、无法持久化。
    仅改 state + 写回 javis.json，无需重建 agent（运行时即生效）。
    """
    from src.permissions import GATED_TOOLS, apply_permission_override, dump_permissions_json

    if tool not in GATED_TOOLS:
        return False
    apply_permission_override(permission_state, tool, "allow")
    from src.config import load_config

    load_config()
    dump_permissions_json(
        current_permissions(permission_state),
        project_root() / "javis.json",
    )
    return True


def dispatch_command(agent, thread_id: str, command: str, sched=None, vault_path: Path | None = None):
    """处理会话命令，返回 (结果文本, 新 thread_id 或 None)。fork 可能切换会话。"""
    parts = command.split()
    cmd = parts[0]

    if cmd == "/sessions":
        return list_sessions(agent), None
    if cmd == "/history":
        return list_history(agent, thread_id), None
    if cmd == "/replay" and len(parts) == 2:
        return replay(agent, thread_id, parts[1]), None
    if cmd == "/fork" and len(parts) == 2:
        return fork(agent, thread_id, parts[1])
    if cmd == "/snapshot":
        return snapshot(agent, thread_id), None
    if cmd == "/snapshots":
        return list_snapshots(), None
    if cmd == "/rollback" and len(parts) == 2:
        vp = vault_path
        if vp is None:
            try:
                from src.config import load_config

                vp = load_config().vault_path
            except Exception:
                vp = None
        return rollback(agent, thread_id, parts[1], vp), None
    if cmd == "/reload-schedules":
        if sched is None:
            return "调度器未启动，无法重载", None
        from src import scheduler
        from src.config import load_config

        return scheduler.reload_schedules(sched, agent, load_config()), None
    return f"未知命令: {cmd}（/help 查看帮助）", None
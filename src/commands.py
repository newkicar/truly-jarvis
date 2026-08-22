"""命令分发与会话管理纯逻辑（CLI 与 TUI 共用）。

从 main.py 抽取：不依赖终端交互（无 input()/print()），
所有函数「接收 agent/thread_id → 返回文本」，可被 CLI 与 TUI 直接复用。
"""
import os
from dataclasses import dataclass
from pathlib import Path

from src import time_travel
from src.project_paths import (
    ENV_JARVIS_HOME,
    ENV_PROJECT_ROOT,
    install_root,
    resolve_env_file,
    resolve_javis_json,
    user_home,
)

_HELP_COMMANDS = """\
命令：
  /exit           退出
  /sessions       列出历史会话
  /delete-session [thread_id]  删除历史会话（可写序号；省略 id 则删当前）
  /copy-session   复制当前会话 ID 到剪贴板
  /doctor         诊断配置与会话健康（模型/权限/checkpoint）
  /history        查看当前会话时间线（带序号，可用于回退）
  /replay <id>    从指定 checkpoint 重跑（序号 / 短 id / 完整 id）
  /fork <id>      从指定 checkpoint 分叉出新分支（序号 / 短 id / 完整 id）
  /snapshot       记录当前文件状态到当前 checkpoint（git 快照）
  /snapshots      列出文件快照（git）
  /rollback <id>  按 checkpoint 回退项目文件到对应 git 提交（序号 / 短 id）
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
    + "会话：侧边栏点选后 Y 复制 ID、D 删除；或 /delete-session 2 按序号删。\n"
    + "复制：对话区鼠标拖选（松开自动复制，javis.json tui.copy_on_select）；"
    + "Ctrl+Insert / Y（侧边栏会话）；/copy-session 复制 thread_id。\n"
    + "退出：Ctrl+C 或 Ctrl+Q；集成终端若 Ctrl+C 直接杀进程，请用 /exit。\n"
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


from src.project_paths import get_project_root


def project_root() -> Path:
    return get_project_root()


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
    """把用户输入解析成完整 checkpoint_id。

    支持：/history 序号（1 起）、完整 id、短 id 前缀唯一匹配。
    """
    raw = raw.strip()
    if not raw:
        return None
    if raw.isdigit():
        checkpoints = boundary_checkpoints(agent, thread_id)
        idx = int(raw)
        if 1 <= idx <= len(checkpoints):
            return checkpoints[idx - 1].config.get("configurable", {}).get("checkpoint_id")
        return None
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
    lines = ["历史会话:"]
    for i, t in enumerate(threads, 1):
        lines.append(f"  {i}. {t}")
    lines.append(
        "删除: /delete-session <序号或 thread_id>（省略 id 删当前；序号见上表）"
    )
    lines.append("复制当前会话 ID: /copy-session")
    return "\n".join(lines)


def resolve_session_target(agent, raw: str) -> str | None:
    """解析会话目标：序号（/sessions 列表）或 thread_id 前缀。"""
    raw = raw.strip()
    if not raw:
        return None
    threads = session_thread_ids(agent)
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(threads):
            return threads[idx - 1]
        return None
    return resolve_thread_id(agent, raw)


def copy_session_id_text(thread_id: str) -> str:
    """复制 thread_id 到系统剪贴板（Windows），并返回提示文本。"""
    from src.tui_log import copy_text_to_system_clipboard

    copy_text_to_system_clipboard(thread_id)
    return f"已复制会话 ID: {thread_id}"


def resolve_thread_id(agent, raw: str) -> str | None:
    """把用户输入解析成 thread_id（完整 id 或前缀唯一匹配）。"""
    raw = raw.strip()
    if not raw:
        return None
    threads = session_thread_ids(agent)
    if raw in threads:
        return raw
    matches = [t for t in threads if t.startswith(raw)]
    if len(matches) == 1:
        return matches[0]
    return None


def channel_values_stuck(channel_values: dict | None) -> bool:
    """checkpoint 是否卡在 graph 中断态（API 失败 mid-stream 后常见）。"""
    if not channel_values:
        return False
    if channel_values.get("__pregel_tasks"):
        return True
    return any(str(key).startswith("branch:to:") for key in channel_values)


def checkpoint_config_stuck(checkpointer, thread_id: str, *, checkpoint_id: str | None = None) -> bool:
    """读取 checkpointer 最新（或指定）checkpoint 是否处于中断态。"""
    if checkpointer is None or not hasattr(checkpointer, "get_tuple"):
        return False
    config = {"configurable": {"thread_id": thread_id}}
    if checkpoint_id:
        config["configurable"]["checkpoint_id"] = checkpoint_id
    try:
        tup = checkpointer.get_tuple(config)
    except Exception:
        return False
    if not tup:
        return False
    cv = (tup.checkpoint or {}).get("channel_values") or {}
    return channel_values_stuck(cv)


def _rollback_thread_to_last_usable_checkpoint(agent, thread_id: str) -> bool:
    """回退到最近已完成（无 next、非 stuck）的 checkpoint；失败则删 thread。"""
    checkpointer = getattr(agent, "checkpointer", None)
    base_config = {"configurable": {"thread_id": thread_id}}
    try:
        for state in agent.get_state_history(base_config):
            cid = state.config.get("configurable", {}).get("checkpoint_id")
            if not cid:
                continue
            if checkpoint_config_stuck(checkpointer, thread_id, checkpoint_id=cid):
                continue
            if getattr(state, "next", None):
                continue
            agent.update_state({"configurable": {"thread_id": thread_id, "checkpoint_id": cid}}, None)
            return True
    except Exception:
        pass

    if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
        checkpointer.delete_thread(thread_id)
        return True
    return False


def turn_needs_finalize(agent, thread_id: str) -> bool:
    """会话是否处于需清理的未完成 turn（stuck channel 或 pending next）。"""
    checkpointer = getattr(agent, "checkpointer", None)
    if checkpoint_config_stuck(checkpointer, thread_id):
        return True
    try:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        return bool(getattr(state, "next", None))
    except Exception:
        return False


def finalize_turn(agent, thread_id: str) -> bool:
    """Turn 结束清理：取消/放弃/HITL 中断后避免脏 checkpoint 污染下轮。返回是否做了 repair。"""
    if not turn_needs_finalize(agent, thread_id):
        return False
    return _rollback_thread_to_last_usable_checkpoint(agent, thread_id)


def repair_stuck_thread(agent, thread_id: str) -> bool:
    """把卡在 __pregel_tasks / branch:to:* 的会话回退到最近可用 checkpoint。"""
    checkpointer = getattr(agent, "checkpointer", None)
    if not checkpoint_config_stuck(checkpointer, thread_id):
        return False
    return _rollback_thread_to_last_usable_checkpoint(agent, thread_id)


def _mask_secret(value: str, *, prefix: int = 4) -> str:
    if not value:
        return "（空）"
    if len(value) <= prefix + 1:
        return "*" * len(value)
    return f"{value[:prefix]}…"


def _permissions_summary(permissions: dict | None) -> str:
    if not permissions:
        return "（未配置；gated 工具默认 ask）"
    default = permissions.get("*", "ask")
    extras = [f"{k}={v}" for k, v in permissions.items() if k != "*"]
    if not extras:
        return f"*={default}"
    tail = ", ".join(extras[:6])
    if len(extras) > 6:
        tail += ", …"
    return f"*={default}；{tail}"


def _config_layer_lines(project_root: Path) -> list[str]:
    """列出 effective 配置来源（只读，与 load_config 解析顺序一致）。"""
    lines: list[str] = []
    env_path = resolve_env_file(project_root)
    if env_path.is_file():
        lines.append(f"  .env ← {env_path}")
    else:
        lines.append(f"  .env ← （未找到；期望 {env_path} 或 {install_root() / '.env'}）")

    json_path = resolve_javis_json(project_root)
    if json_path.is_file():
        lines.append(f"  javis.json ← {json_path}")
    else:
        lines.append(f"  javis.json ← （未找到；期望 {project_root / 'javis.json'}）")

    lines.append(f"  用户全局目录 ← {user_home()}（skills；JARVIS_HOME 可覆盖）")
    if os.environ.get(ENV_PROJECT_ROOT, "").strip():
        lines.append(f"  环境变量 {ENV_PROJECT_ROOT}={os.environ[ENV_PROJECT_ROOT].strip()}")
    if os.environ.get(ENV_JARVIS_HOME, "").strip():
        lines.append(f"  环境变量 {ENV_JARVIS_HOME}={os.environ[ENV_JARVIS_HOME].strip()}")
    return lines


def _checkpoint_thread_stats(agent, thread_id: str) -> tuple[int | None, int | None]:
    """返回 (checkpoint 条数, 最大 blob 字节)，无 checkpointer 时为 (None, None)。"""
    checkpointer = getattr(agent, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return None, None
    try:
        row = conn.execute(
            "SELECT COUNT(*), MAX(length(checkpoint)) FROM checkpoints WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)
    except Exception:
        return None, None


def _session_message_count(agent, thread_id: str) -> int | None:
    try:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        messages = (state.values or {}).get("messages") or []
        return len(messages)
    except Exception:
        return None


def _mcp_enabled_count(mcps: dict) -> int:
    servers = mcps.get("servers") if isinstance(mcps, dict) else None
    if not isinstance(servers, dict):
        return 0
    count = 0
    for entry in servers.values():
        if isinstance(entry, dict) and entry.get("enabled", True):
            count += 1
    return count


def format_doctor_report(config, agent, thread_id: str, *, mcp_tool_count: int | None = None) -> str:
    """生成 /doctor 只读诊断报告（CLI/TUI 共用）。"""
    checkpointer = getattr(agent, "checkpointer", None)
    stuck = turn_needs_finalize(agent, thread_id)
    cp_count, cp_max = _checkpoint_thread_stats(agent, thread_id)
    msg_count = _session_message_count(agent, thread_id)
    mcp_servers = _mcp_enabled_count(config.mcps)
    if mcp_tool_count is None:
        mcp_tools_line = f"MCP servers（enabled）: {mcp_servers}"
    else:
        mcp_tools_line = f"MCP: {mcp_servers} server(s)，{mcp_tool_count} tool(s) 已加载"

    lines = [
        "JARVIS 诊断",
        "─────────────────────────────",
        f"项目根:     {config.project_root}",
        f"Vault:      {config.vault_path}",
        f"模型:       {config.model_id}",
        f"端点:       {config.base_url}",
        f"API Key:    {_mask_secret(config.api_key)}",
        mcp_tools_line,
        f"Checkpoint: {config.checkpoint_db}",
        "",
        "配置来源:",
        *_config_layer_lines(config.project_root),
        f"  permissions: {_permissions_summary(config.permissions)}",
    ]
    theme = config.tui.get("theme") if isinstance(config.tui, dict) else None
    if theme:
        lines.append(f"  theme: {theme}")

    from src.agent import harness_capabilities, harness_profile_loaded
    from src.permission_hooks import parse_permission_hooks, summarize_permission_hooks

    caps = harness_capabilities(config)
    exec_label = "已加载" if caps["execute"] else "未加载 ⚠"
    todos_label = "已加载" if caps["write_todos"] else "未加载 ⚠"
    tavily_label = "已配置" if caps.get("tavily") else "未配置 ⚠"
    profile_label = "已加载" if harness_profile_loaded(config.model_id) else "未注册 ⚠"
    hook_rules = parse_permission_hooks(config.hooks, project_root=config.project_root)
    hook_summary = summarize_permission_hooks(hook_rules).split("\n", 1)[0]
    lines.append(
        f"Harness:    execute {exec_label}; write_todos {todos_label}; "
        f"quick_search {tavily_label}"
    )
    lines.append(f"HarnessProfile: {profile_label} ({config.model_id})")
    lines.append(f"  {hook_summary}")

    lines.extend(
        [
            "",
            f"当前会话:   {thread_id}",
        ]
    )
    if msg_count is not None:
        lines.append(f"消息条数:   {msg_count}")
    if cp_count is not None:
        lines.append(f"Checkpoint: {cp_count} 条（最大 blob {cp_max} 字节）")

    if stuck:
        lines.extend(
            [
                "会话状态:   ⚠ 未完成 turn（stuck checkpoint 或 pending HITL）",
                "建议:       /delete-session 或 python -m src.main -n --cli 开新会话",
                "            （也可直接再发一条消息，系统会自动尝试 repair）",
            ]
        )
    else:
        lines.append("会话状态:   正常")

    return "\n".join(lines)


def delete_session(agent, target: str, current_thread_id: str) -> tuple[str, str | None]:
    """删除指定会话 checkpoint；若删的是当前会话则返回新 thread_id。"""
    if target.startswith("sched-"):
        return "不能删除定时任务会话 sched-*", None

    resolved = resolve_session_target(agent, target)
    if resolved is None:
        threads = session_thread_ids(agent)
        if target.isdigit():
            return f"删除失败: 无效序号「{target}」（当前共 {len(threads)} 个会话）", None
        matches = [t for t in threads if t.startswith(target)]
        if len(matches) > 1:
            return f"删除失败: thread_id「{target}」歧义，匹配: {', '.join(matches)}", None
        return f"删除失败: 找不到会话「{target}」", None

    checkpointer = getattr(agent, "checkpointer", None)
    if checkpointer is None or not hasattr(checkpointer, "delete_thread"):
        return "（无 checkpointer，无法删除会话）", None

    checkpointer.delete_thread(resolved)

    from src import inbox_snapshots

    root = project_root()
    inbox_count = inbox_snapshots.delete_writes_for_thread(root, resolved)
    snap_count = time_travel.delete_snapshots_for_thread(root, resolved)
    extras: list[str] = []
    if inbox_count:
        extras.append(f"Inbox 快照 {inbox_count} 条")
    if snap_count:
        extras.append(f"文件快照映射 {snap_count} 条")
    extra_msg = f"（一并清理: {', '.join(extras)}）" if extras else ""

    if resolved == current_thread_id:
        import uuid

        new_thread = f"session-{uuid.uuid4().hex[:8]}"
        return f"已删除当前会话 {resolved}，并切换到新会话 {new_thread}{extra_msg}", new_thread
    return f"已删除会话 {resolved}{extra_msg}", None


def list_history(agent, thread_id: str) -> str:
    checkpoints = boundary_checkpoints(agent, thread_id)
    if not checkpoints:
        return "（暂无历史）"
    lines = ["当前会话时间线（从旧到新）:"]
    for i, s in enumerate(checkpoints, 1):
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
    last = len(checkpoints)
    lines.append(f"   → /replay {last} 或 /fork {last}（也可用短 id / 完整 id）")
    return "\n".join(lines)


def prepare_replay(agent, thread_id: str, checkpoint_id: str) -> tuple[str | None, str | None]:
    """解析 /replay 目标 checkpoint。返回 (error_message, full_checkpoint_id)。"""
    full_id = resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if full_id is None:
        if checkpoint_id.strip().isdigit():
            n = len(boundary_checkpoints(agent, thread_id))
            return f"重跑失败: 无效序号「{checkpoint_id}」（当前共 {n} 个边界点）", None
        return f"重跑失败: 找不到 checkpoint {checkpoint_id}", None
    return None, full_id


def completed_turn_checkpoint(agent, thread_id: str, checkpoint_id: str):
    """同一轮里最新的 checkpoint；仅当该轮已结束（无 next）时返回，否则 None。

    /history 列出的是 input 边界（提问瞬间，next 通常仍指向模型）。
    从该点 stream_events(None) 会再执行 LLM。已完成的轮次应直接读保存的回答。
    """
    try:
        newest_first = list(
            agent.get_state_history(config={"configurable": {"thread_id": thread_id}})
        )
    except Exception:
        return None
    in_turn = False
    end = None
    for s in reversed(newest_first):
        cid = (s.config or {}).get("configurable", {}).get("checkpoint_id")
        src = (s.metadata or {}).get("source")
        if not in_turn:
            if cid == checkpoint_id:
                in_turn = True
                end = s
            continue
        if src == "input":
            break
        end = s
    if end is None or getattr(end, "next", None):
        return None
    return end


def fork(agent, thread_id: str, checkpoint_id: str):
    """从指定 checkpoint 分叉出新分支，返回 (提示文本, 新 thread_id 或 None)。"""
    base = {"configurable": {"thread_id": thread_id}}
    full_id = resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if full_id is None:
        if checkpoint_id.strip().isdigit():
            n = len(boundary_checkpoints(agent, thread_id))
            return f"分叉失败: 无效序号「{checkpoint_id}」（当前共 {n} 个边界点）", None
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
    dump_permissions_json(
        current_permissions(permission_state),
        project_root() / "javis.json",
    )
    return True


def dispatch_command(agent, thread_id: str, command: str, sched=None, vault_path: Path | None = None):
    """处理会话命令，返回 (结果文本, 新 thread_id, replay_checkpoint_id)。

    replay_checkpoint_id 非空时 text 为 None，调用方应走 stream_events 重跑。
    """
    parts = command.split()
    cmd = parts[0]

    if cmd == "/sessions":
        return list_sessions(agent), None, None
    if cmd == "/delete-session":
        if len(parts) > 2:
            return "用法: /delete-session [thread_id]", None, None
        target = parts[1] if len(parts) == 2 else thread_id
        text, new_thread = delete_session(agent, target, thread_id)
        return text, new_thread, None
    if cmd == "/copy-session":
        return copy_session_id_text(thread_id), None, None
    if cmd == "/doctor":
        from src.config import load_config
        from src.mcps import load_mcp_tools

        try:
            cfg = load_config()
        except Exception as exc:
            return f"诊断失败: {exc}", None, None
        mcp_tools = load_mcp_tools(cfg.mcps)
        return format_doctor_report(cfg, agent, thread_id, mcp_tool_count=len(mcp_tools)), None, None
    if cmd == "/history":
        return list_history(agent, thread_id), None, None
    if cmd == "/replay":
        if len(parts) != 2:
            return "用法: /replay <checkpoint_id>", None, None
        err, full_id = prepare_replay(agent, thread_id, parts[1])
        if err:
            return err, None, None
        return None, None, full_id
    if cmd == "/fork" and len(parts) == 2:
        text, new_thread = fork(agent, thread_id, parts[1])
        return text, new_thread, None
    if cmd == "/snapshot":
        return snapshot(agent, thread_id), None, None
    if cmd == "/snapshots":
        return list_snapshots(), None, None
    if cmd == "/rollback" and len(parts) == 2:
        vp = vault_path
        if vp is None:
            try:
                from src.config import load_config

                vp = load_config().vault_path
            except Exception:
                vp = None
        return rollback(agent, thread_id, parts[1], vp), None, None
    if cmd == "/reload-schedules":
        if sched is None:
            return "调度器未启动，无法重载", None, None
        from src import scheduler
        from src.config import load_config

        return scheduler.reload_schedules(sched, agent, load_config()), None, None
    return f"未知命令: {cmd}（/help 查看帮助）", None, None
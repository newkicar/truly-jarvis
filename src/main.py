"""CLI 入口。

一期：标准库 input 交互循环，支持 /exit、/sessions、/history、/replay、/fork。
二期：textual TUI。
"""
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from src import scheduler, time_travel
from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config
from src.permissions import build_permission_interrupts

ensure_utf8_stdout()

PROMPT = "JARVIS> "
HELP = """命令：
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
审批操作时: [y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮)；
也可直接编辑 javis.json 的 permissions 段（allow/ask/deny）。
"""


def _render(messages) -> str:
    """取最后一条 AI 消息内容。"""
    for msg in reversed(messages):
        if msg.type == "ai":
            return msg.content
    return ""


def _run_session(agent, thread_id: str, sched=None, permission_state: dict | None = None):
    """交互循环。agent 已装配，thread_id 即会话标识。sched 为定时调度器。"""
    print("JARVIS 就绪。输入 /help 查看命令，/exit 退出。")
    while True:
        try:
            user_input = input(PROMPT).strip()
        except EOFError:
            print()
            break

        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/help":
            print(HELP)
            continue

        if user_input.startswith("/"):
            text, new_thread = _dispatch_command(agent, thread_id, user_input, sched)
            print(text)
            if new_thread:
                thread_id = new_thread
                print(f"已切换到会话 {thread_id}")
            continue

        _stream_turn(agent, thread_id, user_input, permission_state)


def _stream_turn(agent, thread_id: str, user_input: str, permission_state: dict | None = None):
    """用 event streaming(v3) 跑一轮对话，实时打印子代理/工具/最终回答。

    遇到 HITL 审批中断时，暂停并让用户在终端决定（y/a/n/e）。
    """
    from langgraph.types import Command

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}
    resume = None
    while True:
        print()
        stream = agent.stream_events(
            Command(resume=resume) if resume else {"messages": [{"role": "user", "content": user_input}]},
            version="v3",
            config=config,
        )

        consumed = 0
        for kind, item in stream.interleave("messages", "tool_calls", "subagents"):
            if kind == "subagents":
                status = getattr(item, "status", "")
                print(f"  [{item.name}] {status}")
            elif kind == "tool_calls":
                err = getattr(item, "error", None)
                name = getattr(item, "tool_name", "?")
                args = getattr(item, "input", "")
                tag = "✗" if err else "✓"
                print(f"  {tag} {name}({str(args)[:80]})")
            else:  # messages
                for delta in item.text:
                    print(delta, end="", flush=True)
                    consumed += 1

        if not getattr(stream, "interrupted", False) or not getattr(stream, "interrupts", None):
            final_state = stream.output
            if not consumed:
                final_text = _render(final_state["messages"]) if final_state else ""
                if final_text:
                    print(final_text)
            print("\n")
            return

        resume = _handle_interrupts(stream.interrupts, permission_state)
        if resume is None:
            print("\n")
            return


def _handle_interrupts(interrupts, permission_state: dict | None = None):
    """展示待审批操作并收集用户决策，返回 Command.resume 内容。

    返回 None 表示用户放弃本轮（未对全部中断做决定）。
    """
    from src.permissions import GATED_TOOLS, apply_permission_override

    decisions = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None) or {}
        action_requests = value.get("action_requests", [])
        for action in action_requests:
            name = action.get("name", "?")
            args = action.get("args", {})
            print(f"\n  [审批] {name}")
            for k, v in (args or {}).items():
                print(f"    {k}: {str(v)[:120]}")
            while True:
                choice = input(
                    "    操作: [y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮) > "
                ).strip().lower()
                if choice == "y":
                    decisions.append({"type": "approve"})
                    break
                if choice == "n":
                    decisions.append(
                        {"type": "reject", "message": "用户拒绝了该操作，请更换方案或询问用户。不要重试相同调用。"}
                    )
                    break
                if choice == "a":
                    if permission_state is not None and name in GATED_TOOLS:
                        apply_permission_override(permission_state, name, "allow")
                        from src.config import load_config
                        from src.permissions import dump_permissions_json

                        cfg = load_config()
                        dump_permissions_json(_current_permissions(permission_state), _project_root() / "javis.json")
                        print(f"    已设置 {name} = allow（已写入 javis.json，以后自动放行）")
                    else:
                        print(f"    无法持久化 {name} 的 always approve（非 gated tool）")
                    decisions.append({"type": "approve"})
                    break
                if choice == "e":
                    print("    编辑参数（留空使用原值）:")
                    edited = dict(args or {})
                    for k in list(edited.keys()):
                        new_v = input(f"    {k} [原: {str(edited[k])[:60]}] > ").strip()
                        if new_v:
                            edited[k] = new_v
                    decisions.append(
                        {"type": "edit", "edited_action": {"name": name, "args": edited}}
                    )
                    break
                if choice == "q":
                    return None
                print("    无效输入")
    return {"decisions": decisions}


def _current_permissions(permission_state: dict) -> dict:
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


def _project_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


def _dispatch_command(agent, thread_id: str, command: str, sched=None):
    """处理会话命令，返回 (结果文本, 新 thread_id 或 None)。fork 可能切换会话。"""
    parts = command.split()
    cmd = parts[0]

    if cmd == "/sessions":
        return _list_sessions(agent), None
    if cmd == "/history":
        return _list_history(agent, thread_id), None
    if cmd == "/replay" and len(parts) == 2:
        return _replay(agent, thread_id, parts[1]), None
    if cmd == "/fork" and len(parts) == 2:
        return _fork(agent, thread_id, parts[1])
    if cmd == "/snapshot":
        return _snapshot(agent, thread_id), None
    if cmd == "/snapshots":
        return _list_snapshots(), None
    if cmd == "/rollback" and len(parts) == 2:
        return _rollback(parts[1]), None
    if cmd == "/reload-schedules":
        if sched is None:
            return "调度器未启动，无法重载", None
        import src.scheduler as sched_mod

        return sched_mod.reload_schedules(sched, agent, load_config()), None
    return f"未知命令: {cmd}（/help 查看帮助）", None


def _list_sessions(agent) -> str:
    checkpointer = getattr(agent, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return "（无 checkpointer，无法列出会话）"
    rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()
    threads = [r[0] for r in rows if not str(r[0]).startswith("sched-")]
    if not threads:
        return "（暂无历史会话）"
    return "历史会话:\n" + "\n".join(f"  - {t}" for t in threads)


def _boundary_checkpoints(agent, thread_id: str):
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


def _checkpoint_short_id(cid: str) -> str:
    return cid[:13] if cid else cid


def _resolve_checkpoint_id(agent, thread_id: str, raw: str):
    """把用户输入（完整 id 或短 id 前缀）解析成完整 checkpoint_id。

    短 id = cid[:13]（/history 显示用的短格式）。支持前缀唯一匹配；
    多个匹配返回 None，表示歧义。
    """
    for s in agent.get_state_history(config={"configurable": {"thread_id": thread_id}}):
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        if cid == raw:
            return cid
    matches = []
    for s in agent.get_state_history(config={"configurable": {"thread_id": thread_id}}):
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        if cid and cid.startswith(raw):
            matches.append(cid)
    if len(matches) == 1:
        return matches[0]
    return None


def _last_human_text(values) -> str:
    """从 checkpoint 的 messages 里取最后一条用户消息文本（截断 50 字）。"""
    for msg in reversed(values.get("messages", [])):
        if getattr(msg, "type", "") == "human":
            content = getattr(msg, "content", "") or ""
            if isinstance(content, str):
                return content.strip().replace("\n", " ")[:50]
    return ""


def _list_history(agent, thread_id: str) -> str:
    checkpoints = _boundary_checkpoints(agent, thread_id)
    if not checkpoints:
        return "（暂无历史）"
    lines = []
    for i, s in enumerate(checkpoints):
        cid = s.config.get("configurable", {}).get("checkpoint_id")
        src = (s.metadata or {}).get("source")
        step = s.metadata.get("step") if s.metadata else None
        short = _checkpoint_short_id(cid)
        if src == "input":
            label = f"user: {_last_human_text(s.values)}"
        elif src == "fork":
            label = f"分叉点 (step {step})"
        else:  # update
            label = f"状态更新 (step {step})"
        lines.append(f"  {i}. [{src:5s}] {label:<60} {short}")
    lines.append("   → 用短 id（前 13 位）即可 /replay 或 /fork，如 /replay " + _checkpoint_short_id(checkpoints[-1].config.get("configurable", {}).get("checkpoint_id", "")))
    return "\n".join(lines)


def _replay(agent, thread_id: str, checkpoint_id: str) -> str:
    full_id = _resolve_checkpoint_id(agent, thread_id, checkpoint_id)
    if full_id is None:
        return f"重跑失败: 找不到 checkpoint {checkpoint_id}"
    prior = {"configurable": {"thread_id": thread_id, "checkpoint_id": full_id}}
    try:
        result = agent.invoke(None, config=prior)
    except Exception:
        return f"重跑失败: checkpoint {full_id}"
    return "重跑结果:\n" + _render(result["messages"])


def _fork(agent, thread_id: str, checkpoint_id: str):
    """从指定 checkpoint 分叉出新分支，返回 (提示文本, 新 thread_id 或 None)。"""
    base = {"configurable": {"thread_id": thread_id}}
    full_id = _resolve_checkpoint_id(agent, thread_id, checkpoint_id)
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


def _snapshot(agent, thread_id: str) -> str:
    state = agent.get_state({"configurable": {"thread_id": thread_id}})
    cid = state.config.get("configurable", {}).get("checkpoint_id")
    if not cid:
        return "快照失败: 无法确定当前 checkpoint"
    commit = time_travel.snapshot(_project_root(), thread_id, cid)
    if commit is None:
        return "项目文件无变更，未产生快照"
    return f"已记录文件快照: checkpoint {cid} -> {commit}"


def _list_snapshots() -> str:
    rows = time_travel.list_snapshots(_project_root())
    if not rows:
        return "（暂无文件快照）"
    lines = ["文件快照 (从旧到新):"]
    for i, (cid, tid, commit, ts) in enumerate(rows):
        short_cid = _checkpoint_short_id(cid)
        lines.append(
            f"  {i}. [{ts}]  commit {commit[:10]}  thread: {tid}  {short_cid}"
        )
    lines.append(
        "   → 用短 cid（前 13 位）即可 /rollback，如 /rollback "
        + _checkpoint_short_id(rows[-1][0])
    )
    return "\n".join(lines)


def _rollback(checkpoint_id: str) -> str:
    commit = time_travel.resolve_commit(_project_root(), checkpoint_id)
    if commit is None:
        return f"回退失败: 未找到 checkpoint {checkpoint_id} 的文件快照"
    time_travel.rollback_commit(_project_root(), commit)
    return f"已回退项目文件到 {commit}（checkpoint {checkpoint_id}）。注意：需 /replay 对齐会话状态。"


def main(argv=None) -> int:
    config = load_config()
    args = argv[1:] if argv else []
    thread_id = "default"
    if "-n" in args or "--new" in args:
        import uuid

        thread_id = f"session-{uuid.uuid4().hex[:8]}"
    elif args:
        thread_id = args[0]

    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        agent = build_agent(config, checkpointer=checkpointer)
        _interrupt_on, permission_state = build_permission_interrupts(config.permissions)
        if thread_id.startswith("session-"):
            print(f"新会话: {thread_id}（指定 thread_id 可继续该会话）")

        sched = scheduler.make_scheduler(agent, config)
        sched.start()
        jobs = sched.get_jobs()
        if jobs:
            print(f"已注册 {len(jobs)} 个定时任务:")
            for job in jobs:
                print(f"  - {job.id.removeprefix('javis-')}（{job.trigger}）")
        else:
            print("（无定时任务）")
        try:
            _run_session(agent, thread_id, sched, permission_state)
        finally:
            sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
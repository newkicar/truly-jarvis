"""JARVIS 入口。

默认启动 Textual TUI；`--cli` 参数回退到标准库 input 交互循环。
CLI 支持 /exit、/sessions、/history、/replay、/fork、/snapshot、/rollback 等命令。
"""
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from src import commands, scheduler
from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config
from src.mcps import load_mcp_tools
from src.permissions import build_permission_interrupts

ensure_utf8_stdout()

PROMPT = "JARVIS> "
HELP = commands.HELP


def _render(messages) -> str:
    """取最后一条 AI 消息内容。"""
    return commands.render(messages)


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
            text, new_thread = commands.dispatch_command(agent, thread_id, user_input, sched)
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
                    if permission_state is not None and commands.always_approve(permission_state, name):
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


def main(argv=None) -> int:
    config = load_config()
    args = argv[1:] if argv else []
    thread_id = "default"
    use_tui = "--cli" not in args
    if "-n" in args or "--new" in args:
        import uuid

        thread_id = f"session-{uuid.uuid4().hex[:8]}"
    elif args:
        # 过滤掉入口开关参数，只保留可能的 thread_id
        rest = [a for a in args if a not in ("--cli", "--tui")]
        if rest:
            thread_id = rest[0]

    mcp_tools = load_mcp_tools(config.mcps)
    if mcp_tools:
        print(f"[MCP] 已加载 {len(mcp_tools)} 个外部工具")

    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        _, permission_state = build_permission_interrupts(config.permissions)
        agent = build_agent(
            config,
            checkpointer=checkpointer,
            permission_state=permission_state,
            mcp_tools=mcp_tools,
        )
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
            if use_tui:
                from src.tui import JarvisApp

                JarvisApp(config, agent, permission_state, sched, thread_id).run()
            else:
                _run_session(agent, thread_id, sched, permission_state)
        finally:
            sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
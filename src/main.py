"""JARVIS 入口。

默认启动 Textual TUI；`--cli` 参数回退到标准库 input 交互循环。
`--init [目录]` 在当前或指定目录初始化 javis.json 与目录结构。
CLI 支持 /exit、/sessions、/delete-session、/history、/replay、/fork、/snapshot、/rollback 等命令。
"""
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from src import commands, scheduler, streaming, startup
from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config
from src.mcps import load_mcp_tools
from src.permissions import build_permission_interrupts
from src.project_init import run_init_cli, suggest_init_if_missing

ensure_utf8_stdout()

PROMPT = "JARVIS> "


def _cli_tool_line(name, args, err, output, depth=0):
    from src.tui_format import format_tool_call

    line = format_tool_call(name, args, error=err, output=output, indent=depth)
    # Rich markup → plain for CLI
    import re

    print(re.sub(r"\[/??[^\]]*\]", "", line.replace("[dim]", "").replace("[/dim]", "")))


def _run_session(agent, thread_id: str, sched=None, permission_state: dict | None = None, config=None):
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
            print(commands.CLI_HELP)
            continue

        if user_input.startswith("/"):
            text, new_thread, replay_cid = commands.dispatch_command(
                agent, thread_id, user_input, sched
            )
            if replay_cid:
                _stream_replay(agent, thread_id, replay_cid, permission_state, config)
            elif text:
                print(text)
            if new_thread:
                thread_id = new_thread
                print(f"已切换到会话 {thread_id}")
            continue

        _stream_turn(agent, thread_id, user_input, permission_state, config)


def _handle_interrupts(interrupts, permission_state: dict | None = None):
    """展示待审批操作并收集用户决策，返回 Command.resume 内容。"""
    return streaming.collect_interrupt_decisions(
        interrupts,
        lambda inv: streaming.cli_prompt_action(inv, permission_state=permission_state),
        permission_state=permission_state,
    )


def _stream_replay(agent, thread_id: str, checkpoint_id: str, permission_state: dict | None = None, config=None):
    """从 checkpoint 用 stream_events(v3) 重跑，实时打印子代理/工具/最终回答。"""
    print()
    vault_path = getattr(config, "vault_path", None) if config else None
    workspace_root = config.project_root if config else None

    def on_always_approve(name: str) -> None:
        print(f"    已设置 {name} = allow（已写入 javis.json，以后自动放行）")

    streaming.run_agent_turn(
        agent,
        thread_id,
        None,
        checkpoint_id=checkpoint_id,
        handle_interrupts=lambda interrupts: streaming.collect_interrupt_decisions(
            interrupts,
            lambda inv: streaming.cli_prompt_action(
                inv,
                permission_state=permission_state,
                on_always_approve=on_always_approve,
                vault_path=vault_path,
                workspace_root=workspace_root,
            ),
            permission_state=permission_state,
            on_always_approve=on_always_approve,
        ),
        callbacks={
            "on_subagent": lambda name, status, depth=0: print(f"{'  ' * depth}  [{name}] {status}"),
            "on_tool_call": lambda name, args, err, output=None, depth=0: _cli_tool_line(
                name, args, err, output, depth
            ),
            "on_message_delta": lambda delta: print(delta, end="", flush=True),
            "on_status": _cli_status_line,
        },
        on_fallback_message=lambda text: print(text),
        permission_state=permission_state,
        project_root=workspace_root,
        max_steps=int(getattr(config, "execution_max_steps", 200)) if config else 200,
    )
    print("\n")


def _cli_status_line(text: str) -> None:
    print(f"\n  … {text}")


def _stream_turn(agent, thread_id: str, user_input: str, permission_state: dict | None = None, config=None):
    """用 event streaming(v3) 跑一轮对话，实时打印子代理/工具/最终回答。"""
    print()
    vault_path = getattr(config, "vault_path", None) if config else None
    workspace_root = config.project_root if config else None
    max_steps = int(getattr(config, "execution_max_steps", 200)) if config else 200

    def on_always_approve(name: str) -> None:
        print(f"    已设置 {name} = allow（已写入 javis.json，以后自动放行）")

    try:
        streaming.run_agent_turn(
            agent,
            thread_id,
            user_input,
            handle_interrupts=lambda interrupts: streaming.collect_interrupt_decisions(
                interrupts,
                lambda inv: streaming.cli_prompt_action(
                    inv,
                    permission_state=permission_state,
                    on_always_approve=on_always_approve,
                    vault_path=vault_path,
                    workspace_root=workspace_root,
                ),
                permission_state=permission_state,
                on_always_approve=on_always_approve,
            ),
            callbacks={
                "on_subagent": lambda name, status, depth=0: print(f"{'  ' * depth}  [{name}] {status}"),
                "on_tool_call": lambda name, args, err, output=None, depth=0: _cli_tool_line(
                    name, args, err, output, depth
                ),
                "on_message_delta": lambda delta: print(delta, end="", flush=True),
                "on_status": _cli_status_line,
            },
            on_fallback_message=lambda text: print(text),
            permission_state=permission_state,
            project_root=workspace_root,
            max_steps=max_steps,
        )
    except Exception as exc:
        print(f"\n错误: {streaming.format_agent_error(exc)}\n")
    print("\n")


def main(argv=None) -> int:
    raw_args = argv if argv is not None else sys.argv
    args = raw_args[1:]

    if "--init" in args:
        init_args = [
            a
            for a in args
            if a not in ("--init", "--cli", "--tui", "-n", "--new", "--force")
        ]
        if "--force" in args:
            init_args = ["--force", *init_args]
        return run_init_cli(init_args or None)

    try:
        config = load_config()
    except (KeyError, FileNotFoundError):
        # P2: 首次运行——自动生成项目配置 + skills/ + 全局目录
        from src.project_paths import JARVIS_JSON, ensure_user_home

        root = Path.cwd()
        jarvis_file = root / JARVIS_JSON
        if not jarvis_file.is_file():
            from src.project_init import JARVIS_JSON_TEMPLATE

            data = dict(JARVIS_JSON_TEMPLATE)
            data["project_name"] = root.name
            jarvis_file.write_text(
                __import__("json").dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (root / "skills").mkdir(exist_ok=True)
        ensure_user_home()
        config = load_config()

    thread_id = "default"
    use_tui = "--cli" not in args
    if "-n" in args or "--new" in args:
        import uuid

        thread_id = f"session-{uuid.uuid4().hex[:8]}"
    elif args:
        rest = [a for a in args if a not in ("--cli", "--tui")]
        if rest:
            thread_id = rest[0]

    mcp_tools = load_mcp_tools(config.mcps)

    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        _, permission_state = build_permission_interrupts(
            config.permissions,
            hooks=config.hooks,
            project_root=config.project_root,
        )
        agent = build_agent(
            config,
            checkpointer=checkpointer,
            permission_state=permission_state,
            mcp_tools=mcp_tools,
        )

        sched = scheduler.make_scheduler(agent, config)
        sched.start()
        jobs = sched.get_jobs()
        startup_lines = startup.format_startup_lines(
            mcp_tool_count=len(mcp_tools),
            thread_id=thread_id,
            jobs=jobs,
        )
        if not use_tui:
            for line in startup_lines:
                print(line)

        try:
            if use_tui:
                from src.tui import JarvisApp

                JarvisApp(
                    config,
                    agent,
                    permission_state,
                    sched,
                    thread_id,
                    mcp_tool_count=len(mcp_tools),
                    startup_lines=startup_lines,
                ).run()
            else:
                _run_session(agent, thread_id, sched, permission_state, config)
        finally:
            sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

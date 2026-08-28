"""真实模型端到端冒烟脚本（手动运行，不进 CI，消耗额度）。

用法:
  python -m src.smoke_test [问题]           # CLI 一轮对话冒烟
  python -m src.smoke_test --tui            # 启动 TUI，手动输入验证
  python -m src.smoke_test --tui-hitl       # TUI + 自动发送 HITL 用例（写 Inbox）

CLI 验证: 路由 → researcher 委派 → 本地 WIKI 检索 + Tavily 搜索 → 带来源结构化总结。

TUI 验证（--tui）:
  - 流式 Markdown 输出、工具调用行、Esc 取消
  - 侧边栏会话列表（Ctrl+B）、@ 路径补全

TUI HITL 冒烟（--tui-hitl，需真实终端）:
  1. 依赖 `.env` 中 BASE_URL / API_KEY / MODEL_ID（go 套餐真模型）
  2. 启动后自动发送「在 /vault/Inbox/ 创建 smoke-hitl-test.md」预设 prompt
  3. 等待 Permission Modal 弹出（应含 write_file 路径与 diff 预览）
  4. 手动点选: 放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)
  5. 放行后 agent 应 resume 并继续流式输出；拒绝则放弃本轮
  6. 可选替代用例（手动输入）: 「在 workspace 执行 dir 命令」触发 execute 审批

注意: 非确定性、耗时、耗额度；**切勿**加入 GitHub Actions / CI。

CLI 脚本化: 勿用 `echo ... | python -m src.main --cli`（会卡在 JARVIS>）；用本模块或 `(echo 问题 & echo /exit) | python -m src.main -n --cli`。
API 400 排错见仓库根 README「调试与排错」。
"""
from __future__ import annotations

import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from src import scheduler, startup
from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config
from src.mcps import load_mcp_tools
from src.commands import thread_config
from src.permissions import build_permission_interrupts

ensure_utf8_stdout()

# 预设：写 Inbox 必过 vault 守卫 + HITL write_file 审批
TUI_HITL_PROMPT = (
    "请在 /vault/Inbox/ 创建文件 smoke-hitl-test.md，"
    "内容为一行文字：TUI HITL smoke test。"
    "只需创建这一份文件并告诉我完整路径。"
)

TUI_HITL_CHECKLIST = [
    "【TUI HITL 冒烟】已自动发送写 Inbox 用例，请手动验证 Permission Modal：",
    "  · 放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)",
    "  · 放行后应 resume 并继续流式输出",
    "  · 依赖 .env 真模型，不进 CI",
]

TUI_MANUAL_HINT = [
    "【TUI 冒烟】可手动输入消息验证流式与命令。",
    "  HITL 自动用例: python -m src.smoke_test --tui-hitl",
]


def parse_smoke_argv(argv: list[str]) -> tuple[bool, bool, str | None]:
    """解析冒烟参数 → (use_tui, use_hitl, cli_question)。"""
    use_tui = "--tui" in argv or "--tui-hitl" in argv
    use_hitl = "--hitl" in argv or "--tui-hitl" in argv
    positional = [a for a in argv if not a.startswith("-")]
    question = positional[0] if positional else None
    return use_tui, use_hitl, question


def main() -> int:
    argv = sys.argv[1:]
    use_tui, use_hitl, question = parse_smoke_argv(argv)
    config = load_config()
    config.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
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
        startup_lines = list(
            startup.format_startup_lines(
                mcp_tool_count=len(mcp_tools),
                thread_id="smoke",
                jobs=sched.get_jobs(),
            )
        )
        startup_prompt: str | None = None
        if use_tui and use_hitl:
            startup_lines.extend(TUI_HITL_CHECKLIST)
            startup_prompt = TUI_HITL_PROMPT
        elif use_tui:
            startup_lines.extend(TUI_MANUAL_HINT)

        try:
            if use_tui:
                from src.tui import JarvisApp

                JarvisApp(
                    config,
                    agent,
                    permission_state,
                    sched,
                    thread_id="smoke",
                    mcp_tool_count=len(mcp_tools),
                    startup_lines=startup_lines,
                    startup_prompt=startup_prompt,
                ).run()
                return 0

            for line in startup_lines:
                print(line)

            default_question = "调研大模型行业最新动态，重点关注开源模型进展"
            final_question = question or default_question
            print(f"\n=== 提问: {final_question} ===\n")
            result = agent.invoke(
                {"messages": [{"role": "user", "content": final_question}]},
                config={**thread_config("smoke"), "recursion_limit": 30},
            )
            for msg in result["messages"]:
                if msg.type == "ai":
                    print(msg.content)
            print("\n=== 冒烟完成 ===")
        finally:
            sched.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

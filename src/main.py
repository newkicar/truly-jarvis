"""CLI 入口。

一期：标准库 input 交互循环，支持 /exit、/sessions、/history、/replay、/fork。
二期：textual TUI。
"""
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config

ensure_utf8_stdout()

PROMPT = "JARVIS> "
HELP = """命令：
  /exit           退出
  /sessions       列出历史会话
  /history        查看当前会话时间线
  /replay <id>    从指定 checkpoint 重跑
  /fork <id>      从指定 checkpoint 分叉出新分支
直接输入文字开始对话。
"""


def _render(messages) -> str:
    """取最后一条 AI 消息内容。"""
    for msg in reversed(messages):
        if msg.type == "ai":
            return msg.content
    return ""


def _run_session(agent, thread_id: str):
    """交互循环。agent 已装配，thread_id 即会话标识。"""
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
            print(_dispatch_command(agent, thread_id, user_input))
            continue

        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 30},
        )
        print(_render(result["messages"]))


def _dispatch_command(agent, thread_id: str, command: str) -> str:
    """处理会话命令，返回要打印的结果文本。"""
    parts = command.split()
    cmd = parts[0]

    if cmd == "/sessions":
        return _list_sessions(agent)
    if cmd == "/history":
        return _list_history(agent, thread_id)
    if cmd == "/replay" and len(parts) == 2:
        return _replay(agent, thread_id, parts[1])
    if cmd == "/fork" and len(parts) == 2:
        return _fork(agent, thread_id, parts[1])
    return f"未知命令: {cmd}（/help 查看帮助）"


def _list_sessions(agent) -> str:
    checkpointer = getattr(agent, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    if conn is None:
        return "（无 checkpointer，无法列出会话）"
    rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id").fetchall()
    threads = [r[0] for r in rows]
    if not threads:
        return "（暂无历史会话）"
    return "历史会话:\n" + "\n".join(f"  - {t}" for t in threads)


def _list_history(agent, thread_id: str) -> str:
    lines = []
    try:
        for i, checkpoint in enumerate(agent.get_state_history(config={"configurable": {"thread_id": thread_id}})):
            cid = checkpoint.config.get("configurable", {}).get("checkpoint_id")
            lines.append(f"  {i}. {cid}")
    except Exception:
        return "（无法读取历史）"
    return "\n".join(lines) if lines else "（暂无历史）"


def _replay(agent, thread_id: str, checkpoint_id: str) -> str:
    prior = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
    try:
        result = agent.invoke(None, config=prior)
    except Exception:
        return f"重跑失败: checkpoint {checkpoint_id}"
    return "重跑结果:\n" + _render(result["messages"])


def _fork(agent, thread_id: str, checkpoint_id: str) -> str:
    base = {"configurable": {"thread_id": thread_id}}
    try:
        target = None
        for s in agent.get_state_history(config=base):
            if s.config["configurable"].get("checkpoint_id") == checkpoint_id:
                target = s
                break
            if s.next and target is None:
                target = s  # 保底：取最近有 pending 节点的 checkpoint
        if target is None:
            return f"分叉失败: 找不到 checkpoint {checkpoint_id}"
        new_config = agent.update_state(
            target.config,
            values=target.values,
            as_node="model",
        )
    except Exception:
        return f"分叉失败: checkpoint {checkpoint_id}"
    new_thread = new_config["configurable"]["thread_id"]
    return f"已从 {checkpoint_id} 分叉（保留原历史），当前会话 {new_thread}"


def main(argv=None) -> int:
    config = load_config()
    with SqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:
        agent = build_agent(config, checkpointer=checkpointer)
        thread_id = "default"
        if argv and len(argv) > 1:
            thread_id = argv[1]
        _run_session(agent, thread_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
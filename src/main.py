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

        _stream_turn(agent, thread_id, user_input)


def _stream_turn(agent, thread_id: str, user_input: str):
    """用 event streaming(v3) 跑一轮对话，实时打印子代理/工具/最终回答。

    相比 invoke() 全程静默，流式让用户看到「在干嘛」，长时间无响应可定位。
    """
    print()
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": user_input}]},
        version="v3",
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": 30},
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

    final_state = stream.output
    if not consumed:
        final_text = _render(final_state["messages"]) if final_state else ""
        if final_text:
            print(final_text)
    print("\n")


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
        found_terminal = False
        for s in agent.get_state_history(config=base):
            if s.config["configurable"].get("checkpoint_id") == checkpoint_id:
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
    args = argv[1:] if argv else []
    thread_id = "default"
    if "-n" in args or "--new" in args:
        import uuid

        thread_id = f"session-{uuid.uuid4().hex[:8]}"
    elif args:
        thread_id = args[0]

    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        agent = build_agent(config, checkpointer=checkpointer)
        if thread_id.startswith("session-"):
            print(f"新会话: {thread_id}（指定 thread_id 可继续该会话）")
        _run_session(agent, thread_id)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
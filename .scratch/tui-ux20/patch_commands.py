import io
p = r"D:\Python Project\truly-jarvis-main\src\commands.py"
s = io.open(p, encoding="utf-8").read()

# 1) json import
old_imp = "import os\nimport re\n"
assert old_imp in s
s = s.replace(old_imp, "import json\nimport os\nimport re\n", 1)

# 2) thread_history_entries after thread_history_text
anchor = '''

def last_ai_text(agent, thread_id: str, limit: int = 300) -> str:'''
new_func = '''

def _msg_text(content) -> str:
    """消息 content 归一化为纯文本（deepagents 可能是 list[dict] 多模态块）。"""
    if isinstance(content, list) and content:
        first = content[0]
        content = first.get("text", "") if isinstance(first, dict) else str(first)
    return content if isinstance(content, str) else ""


def thread_history_entries(agent, thread_id: str, max_entries: int = 20) -> list[tuple]:
    """取指定 thread 的历史条目（含工具调用与思考），供切换会话/撤回后持久上屏。

    返回打标 tuple 列表（从旧到新，从末尾截取至多 max_entries 条）：
      ("user", text)
      ("reasoning", text)          # msg.additional_kwargs["reasoning_content"]
      ("ai", text)
      ("tool", name, args_json, err, output, depth)
    工具行在发起它的 AI 消息处展开（按 AIMessage.tool_calls），结果经 tool_call_id
    匹配后续 ToolMessage；err = status=="error" 或含 execute 失败状态行标记。
    """
    try:
        history = list(agent.get_state_history(config=thread_config(thread_id)))
    except Exception:
        return []
    if not history:
        return []
    messages = (history[0].values or {}).get("messages") or []

    tool_results: dict = {}
    for msg in messages:
        if getattr(msg, "type", "") == "tool":
            cid = getattr(msg, "tool_call_id", "") or ""
            if cid:
                tool_results[cid] = msg

    result: list[tuple] = []
    fail_marker = "[Command failed with exit code"
    for msg in messages:
        role = getattr(msg, "type", "")
        if role == "human":
            text = _msg_text(getattr(msg, "content", "")).strip()
            if text:
                result.append(("user", text))
        elif role == "ai":
            reasoning = (getattr(msg, "additional_kwargs", None) or {}).get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                result.append(("reasoning", reasoning.strip()))
            text = _msg_text(getattr(msg, "content", "")).strip()
            if text:
                result.append(("ai", text))
            for tc in getattr(msg, "tool_calls", None) or []:
                name = str(tc.get("name") or "?")
                args_json = json.dumps(tc.get("args", {}), ensure_ascii=False, default=str)
                res = tool_results.get(str(tc.get("id") or ""))
                if res is None:
                    result.append(("tool", name, args_json, False, None, 0))
                    continue
                out_text = _msg_text(getattr(res, "content", ""))
                err = getattr(res, "status", None) == "error" or fail_marker in out_text
                result.append(("tool", name, args_json, err, out_text or None, 0))
    return result[-max_entries:]

'''
assert anchor in s
s = s.replace(anchor, new_func + "def last_ai_text(agent, thread_id: str, limit: int = 300) -> str:", 1)
io.open(p, "w", encoding="utf-8", newline="").write(s)
print("commands.py patched")

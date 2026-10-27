"""probe_reasoning.py — 1a 决定性探针：网关是否实际下发 reasoning_content。

 三段：
   A. openai SDK 原始流式：delta 上出现过的字段键（是否有 reasoning_content）
   B. langchain ChatOpenAI 原生 stream：chunk.additional_kwargs 键
   C. 补丁 + langgraph v3：additional_kwargs 注入后 .reasoning 投影是否出字
 只读 .env，不回显任何密钥。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import parse_env_file
env = parse_env_file(ROOT / ".env")
base_url = env["BASE_URL"]
api_key = env["API_KEY"]
model_id = env["MODEL_ID"]
print(f"[env] model={model_id} endpoint={base_url}")

PROMPT = "用一句话解释什么是递归，然后给一个python例子"

print("\n=== A. openai SDK raw stream ===")
raw_has_reasoning = False
try:
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key)
    delta_keys: set = set()
    sample_reasoning = []
    with client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": PROMPT}],
        stream=True,
        max_tokens=300,
    ) as stream:
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            if delta is None:
                continue
            d = delta.model_dump() if hasattr(delta, "model_dump") else dict(delta)
            delta_keys.update(k for k, v in d.items() if v not in (None, "", []))
            rc = d.get("reasoning_content")
            if rc:
                sample_reasoning.append(rc)
    print("delta 字段(非空出现过的键):", sorted(delta_keys))
    print("reasoning_content 出现 chunk 数:", len(sample_reasoning))
    if sample_reasoning:
        joined = "".join(sample_reasoning)
        print("reasoning 首200字:", joined[:200])
    raw_has_reasoning = bool(sample_reasoning)
except Exception as e:
    print("A 失败:", type(e).__name__, str(e)[:300])

print("\n=== B. langchain ChatOpenAI stream (no patch) ===")
from langchain_openai import ChatOpenAI
m = ChatOpenAI(base_url=base_url, api_key=api_key, model=model_id, temperature=0, timeout=120)
ak_keys: set = set()
reasoning_chunks_b = 0
try:
    for chunk in m.stream(PROMPT, max_tokens=300):
        ak_keys.update(chunk.additional_kwargs.keys())
        if chunk.additional_kwargs.get("reasoning_content"):
            reasoning_chunks_b += 1
    print("additional_kwargs 键:", sorted(ak_keys))
    print("原生 reasoning_content chunk 数:", reasoning_chunks_b)
except Exception as e:
    print("B 失败:", type(e).__name__, str(e)[:300])

print("\n=== C. patched + langgraph v3 .reasoning projection ===")
import langchain_openai.chat_models.base as lob

_orig_delta = lob._convert_delta_to_message_chunk
_orig_dict = lob._convert_dict_to_message

def patch_delta(_dict, default_class):
    chunk = _orig_delta(_dict, default_class)
    rc = _dict.get("reasoning_content")
    if isinstance(rc, str) and rc:
        chunk.additional_kwargs["reasoning_content"] = rc
    return chunk

def patch_dict(_dict):
    msg = _orig_dict(_dict)
    rc = _dict.get("reasoning_content")
    if isinstance(rc, str) and rc:
        msg.additional_kwargs["reasoning_content"] = rc
    return msg

lob._convert_delta_to_message_chunk = patch_delta
lob._convert_dict_to_message = patch_dict

from langgraph.graph import StateGraph, MessagesState

def node(state):
    return {"messages": [m.invoke(state["messages"], max_tokens=300)]}

g = StateGraph(MessagesState)
g.add_node("model", node)
g.set_entry_point("model")
compiled = g.compile()

reasoning_total = 0
text_total = 0
first_reasoning_piece = None
first_text_piece = None
for item in compiled.stream(
    {"messages": [{"role": "user", "content": PROMPT}]},
    stream_mode="messages",
):
    try:
        for r in item.reasoning:
            reasoning_total += len(r)
            if first_reasoning_piece is None:
                first_reasoning_piece = r
    except Exception as e:
        print("item.reasoning 迭代异常:", type(e).__name__, str(e)[:200])
    try:
        for t in item.text:
            text_total += len(t)
            if first_text_piece is None:
                first_text_piece = t
    except Exception as e:
        print("item.text 迭代异常:", type(e).__name__, str(e)[:200])

print("reasoning 总字数:", reasoning_total)
print("正文 总字数:", text_total)
if first_reasoning_piece:
    print("reasoning 首段(前200字):", first_reasoning_piece[:200])
if first_text_piece:
    print("正文 首段(前200字):", first_text_piece[:200])

print("\n=== C2. patched non-stream ===")
res = m.invoke([{"role": "user", "content": PROMPT}], max_tokens=300)
ak = res.additional_kwargs.get("reasoning_content")
print("非流式 reasoning_content 字数:", len(ak) if isinstance(ak, str) else "N/A")
if isinstance(ak, str) and ak:
    print("非流式 reasoning 首200字:", ak[:200])

print("\n=== 结论 ===")
print("raw 有 reasoning_content:", raw_has_reasoning)

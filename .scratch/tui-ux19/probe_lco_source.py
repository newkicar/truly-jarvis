import inspect
from langchain_openai.chat_models import base as B
import langchain_openai
print("has _convert_delta_to_message_chunk:", hasattr(B, "_convert_delta_to_message_chunk"))
if hasattr(B, "_convert_delta_to_message_chunk"):
    print(inspect.getsource(B._convert_delta_to_message_chunk)[:3000])
from langchain_core.messages import AIMessageChunk
a = AIMessageChunk(content=[{"type": "text", "text": "hi", "id": "x"}], id="1")
b = AIMessageChunk(content=[{"type": "reasoning", "text": "why", "id": "y"}], id="1")
c = a + b
if isinstance(c.content, list):
    print("MERGED block+block:", c.content)
d = AIMessageChunk(content="", id="1")
e = d + b
if isinstance(e.content, list):
    print("STR+BLOCK:", e.content)
else:
    print("STR+BLOCK -> str:", repr(e.content))
f = AIMessageChunk(content="a", id="1")
g = AIMessageChunk(content="b", id="1", additional_kwargs={"jarvis_reasoning": "R1"})
h = f + g
print("KW after add:", h.additional_kwargs)
i = h + AIMessageChunk(content="c", id="1", additional_kwargs={"jarvis_reasoning": "R2"})
print("KW after 2nd:", i.additional_kwargs)
print("PKG", inspect.getfile(B))

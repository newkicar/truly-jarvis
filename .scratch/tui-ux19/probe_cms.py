import inspect, re
from langchain_core.language_models.chat_model_stream import ChatModelStream
print("module:", ChatModelStream.__module__)
src = inspect.getsource(ChatModelStream)
print(len(src))
for m in re.finditer(r"reasoning", src):
    s = max(0, m.start()-400); print(src[s:m.end()+500]); print("======")
open(".scratch/tui-ux19/chat_model_stream_src.txt","w",encoding="utf-8").write(src)
EOF_MARKER=None

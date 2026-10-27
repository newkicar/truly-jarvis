import inspect, re
import langgraph.stream as ls
print("exports:", [n for n in dir(ls) if not n.startswith("_")])
from langgraph.stream import run_stream
src = inspect.getsource(run_stream)
print(len(src))
open(".scratch/tui-ux19/langgraph_run_stream_src.txt","w",encoding="utf-8").write(src)
# find reasoning mentions
for m in re.finditer(r"reasoning", src):
    s=max(0,m.start()-300); print(src[s:m.end()+400]); print("======")
EOF_MARKER=None

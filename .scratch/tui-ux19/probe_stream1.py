import langgraph, pkgutil
print(list(langgraph.__path__))
import langgraph.stream
print([m.name for m in pkgutil.iter_modules(langgraph.stream.__path__)])
import inspect, re
from langgraph.stream import Stream
src = inspect.getsource(Stream)
print("Stream source has 'reasoning':", "reasoning" in src)
EOF_MARKER=None

import inspect, os, re
import deepagents
print("deepagents at", os.path.dirname(deepagents.__file__))
from deepagents import _streaming as ds
print([n for n in dir(ds) if "stream" in n.lower() or "Message" in n])

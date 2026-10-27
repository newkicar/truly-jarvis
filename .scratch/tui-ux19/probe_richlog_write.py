import inspect, os, re, textual
print("textual", textual.__version__, os.path.dirname(textual.__file__))
from textual.widgets import RichLog
src = inspect.getsource(RichLog)
m = re.search(r"def write\(.*?(?=\n    def |\n    @)", src, re.S)
print(m.group(0) if m else "write not found")

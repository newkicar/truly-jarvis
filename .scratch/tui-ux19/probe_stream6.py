import re
fp = r"D:\python_env\Lib\site-packages\langgraph\stream\run_stream.py"
text = open(fp, encoding="utf-8").read()
lines = text.splitlines()
# print imports
print("\n".join(lines[:40]))
print("=== interleave region ===")
print("\n".join(lines[240:330]))
EOF_MARKER=None

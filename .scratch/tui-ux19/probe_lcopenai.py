import re, os
root = r"D:\python_env\Lib\site-packages\langchain_openai"
for dirpath, _, files in os.walk(root):
    if "__pycache__" in dirpath: continue
    for fn in files:
        if not fn.endswith(".py"): continue
        fp = os.path.join(dirpath, fn)
        text = open(fp, encoding="utf-8").read()
        n = len(re.findall(r"reasoning", text))
        if n: print(fp, n)
EOF_MARKER=None

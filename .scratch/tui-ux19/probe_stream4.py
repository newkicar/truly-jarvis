import re, os
root = r"D:\python_env\Lib\site-packages\langgraph"
for dirpath, _, files in os.walk(root):
    for fn in files:
        if not fn.endswith(".py"): continue
        fp = os.path.join(dirpath, fn)
        text = open(fp, encoding="utf-8").read()
        for m in re.finditer(r"reasoning", text):
            line = text[:m.start()].count("\n")+1
            print(fp.replace(root,""), m.group(), line)
EOF_MARKER=None

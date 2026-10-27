import os, re
root = r"D:\python_env\Lib\site-packages\langgraph\stream"
for fn in os.listdir(root):
    if not fn.endswith(".py"): continue
    text = open(os.path.join(root, fn), encoding="utf-8").read()
    for pat in ["def interleave", "reasoning", "class .*Transformer", "def text"]:
        for m in re.finditer(re.escape(pat) if pat[0] in "def" else pat, text):
            line = text[:m.start()].count("\n")+1
            print(fn, pat, line)
EOF_MARKER=None

import re, os
site = r"D:\python_env\Lib\site-packages"
for pkg in ["langgraph","langchain_core","langchain_openai","langchain","langchain_middleware" if os.path.exists(os.path.join(site,"langchain_middleware")) else ""]:
    root = os.path.join(site, pkg)
    if not os.path.isdir(root): continue
    for dirpath, _, files in os.walk(root):
        if "__pycache__" in dirpath: continue
        for fn in files:
            if not fn.endswith(".py"): continue
            fp = os.path.join(dirpath, fn)
            text = open(fp, encoding="utf-8").read()
            if "class ChatModelStream" in text:
                print("CLASS in", fp)
            for pat in ["reasoning_delta", "reasoning_chunks", "class .*Reasoning", "def reasoning"]:
                for m in re.finditer(pat, text):
                    line = text[:m.start()].count("\n")+1
                    print(pkg, fn, repr(pat), line)
EOF_MARKER=None

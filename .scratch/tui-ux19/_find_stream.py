import os
sp = r"D:\python_env\Lib\site-packages"
for name in ["langgraph", "langchain_core", "langchain_openai", "deepagents"]:
    d = os.path.join(sp, name)
    hits = []
    for root, dirs, files in os.walk(d):
        for f in files:
            if f.endswith(".py"):
                p = os.path.join(root, f)
                s = open(p, encoding="utf-8", errors="ignore").read()
                if ("SyncTextProjection" in s) or ("class ChatModelStream" in s) or ("reasoning-delta" in s):
                    hits.append(os.path.relpath(p, sp))
    print(name, hits[:12])

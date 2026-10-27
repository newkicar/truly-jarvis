import glob, re, os
base = r"D:\python_env\Lib\site-packages"
for p in glob.glob(os.path.join(base, "langgraph", "stream", "**", "*.py"), recursive=True):
    t = open(p, encoding="utf-8").read()
    lines = t.splitlines()
    for i, line in enumerate(lines, 1):
        if re.search(r"^\s+(@property|def |class |reasoning|self\._?reasoning)", line):
            print(p.split("stream")[1], i, line.rstrip()[:150])

import io, glob, re

def grep(pat, paths, limit=40):
    n = 0
    for p in paths:
        try:
            lines = io.open(p, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for i, l in enumerate(lines, 1):
            if pat in l:
                print(f"{p}:{i}: {l.rstrip()[:150]}")
                n += 1
                if n >= limit:
                    return
src = glob.glob("src/*.py")
print("== user_message_markup ==")
grep("user_message_markup", src + ["tests/test_tui.py"])
print("== format_tool_call usages ==")
grep("format_tool_call", src + glob.glob("tests/*.py"))
print("== tui.py json import ==")
grep("import json", ["src/tui.py"])
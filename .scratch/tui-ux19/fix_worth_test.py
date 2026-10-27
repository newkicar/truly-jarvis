import sys
path = r"D:\Python Project\truly-jarvis-main\tests\test_tui_format.py"
data = open(path, "rb").read().decode("utf-8")
old = '    assert "\uff09\u622a\u65ad\uff0c\u5171 %d \u5b57\u7b26" % len(big) in block2'
new = '    assert "\u622a\u65ad\uff0c\u5171 %d \u5b57\u7b26\uff09" % len(big) in block2'
if old not in data:
    print("ANCHOR NOT FOUND"); sys.exit(1)
open(path, "wb").write(data.replace(old, new, 1).encode("utf-8"))
print("fixed")

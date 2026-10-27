import sys

path = r"D:\Python Project\truly-jarvis-main\tests\test_tui.py"
data = open(path, "rb").read().decode("utf-8")
old = '        assert "[user] \u95ee\u9898 1" in joined  # transcript \u5df2\u6309\u56de\u9000\u540e\u72b6\u6001\u91cd\u5efa\r\n'
new = ('        assert "\u258c \u4f60" in joined and "\u95ee\u9898 1" in joined  # tui-ux19: transcript \u5df2\u6309\u56de\u9000\u540e\u72b6\u6001\u4ee5\u65b0\u6e32\u67d3\u683c\u5f0f\u91cd\u5efa\r\n'
       '        assert "\u56de\u7b54 1" in joined\r\n')
if old not in data:
    print("ANCHOR NOT FOUND"); sys.exit(1)
data = data.replace(old, new, 1)
open(path, "wb").write(data.encode("utf-8"))
print("patched", path)

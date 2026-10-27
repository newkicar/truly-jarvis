# tui-ux19: 修 _write_variant_strips 的 rich 15 API 回归
# 根因：Console 无 .console 属性（rich 15 中 Console.size 返回 ConsoleDimensions，
# 选项对象在 Console.options 属性上）。
import io

path = "src/tui_log.py"
raw = open(path, "rb").read()
text = raw.decode("utf-8")
old = "opts = local.console.size.options"
new = "opts = local.options"
assert text.count(old) == 1, f"anchor count = {text.count(old)}"
text = text.replace(old, new)
open(path, "wb").write(text.encode("utf-8"))
print("patched OK")

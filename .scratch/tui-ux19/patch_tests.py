import sys

def patch(path, replacements):
    data = open(path, "rb").read().decode("utf-8")
    for old, new in replacements:
        if old not in data:
            print("ANCHOR NOT FOUND in", path, ":", repr(old[:100]))
            sys.exit(1)
        data = data.replace(old, new, 1)
    open(path, "wb").write(data.encode("utf-8"))
    print("patched", path)

ROOT = r"D:\Python Project\truly-jarvis-main"

patch(ROOT + r"\tests\test_tui_turn.py", [
    ('def test_callbacks_dict_has_all_five_keys():',
     'def test_callbacks_dict_has_all_six_keys():'),
    ('assert set(cb) == {"on_subagent", "on_tool_call", "on_message_delta", "on_message_end", "on_status"}',
     'assert set(cb) == {"on_subagent", "on_tool_call", "on_message_delta", "on_message_end", "on_status", "on_reasoning_end"}'),
])

patch(ROOT + r"\tests\test_tui.py", [
    ('        assert "[user] \u95ee\u9898 1" in joined  # transcript \u5df2\u6309\u56de\u9000\u540e\u72b6\u6001\u91cd\u5efa\n',
     '        assert "\u258c \u4f60" in joined and "\u95ee\u9898 1" in joined  # tui-ux19: transcript \u5df2\u6309\u56de\u9000\u540e\u72b6\u6001\u4ee5\u65b0\u6e32\u67d3\u683c\u5f0f\u91cd\u5efa\n        assert "\u56de\u7b54 1" in joined\n'),
])
print("done")

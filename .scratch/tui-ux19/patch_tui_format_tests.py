import sys

path = r"D:\Python Project\truly-jarvis-main\tests\test_tui_format.py"
raw = open(path, "rb").read()
nl = b"\r\n" if raw.count(b"\r\n") > raw.count(b"\n") // 2 else b"\n"
data = raw.decode("utf-8")

addition = '''

from src.tui_format import (
    REASONING_DISPLAY_CAP_LINES,
    TOOL_DETAIL_ARG_CAP,
    TOOL_DETAIL_OUT_CAP_LINES,
    reasoning_block_markup,
    tool_detail_block,
    tool_detail_worth_expanding,
)


# ---------------- tui-ux19: 工具详情展开 / 思考块 纯函数 ----------------

def test_tool_detail_worth_expanding_truth_table():
    """error / 非空输出 / 长参数 → True；普通短调用无输出 → False。"""
    assert tool_detail_worth_expanding("execute", "ls", error=True) is True
    assert tool_detail_worth_expanding("read_file", "path=x", output="abc") is True
    assert tool_detail_worth_expanding("grep", "q") is False
    long_args = "q" * 81
    assert tool_detail_worth_expanding("grep", long_args) is True
    assert tool_detail_worth_expanding("grep", "q" * 80) is False
    # 空白输出不算有输出 → 回落到参数长度判断
    assert tool_detail_worth_expanding("grep", "q", output="   ") is False


def test_format_tool_call_detail_marker():
    line = format_tool_call("execute", "ls", detail=True)
    assert "\uff0b \u8be6\u60c5\uff08\u70b9\u51fb\u5c55\u5f00/\u6536\u8d77\uff09" in line
    plain = format_tool_call("execute", "ls")
    assert "\uff0b \u8be6\u60c5" not in plain


def test_tool_detail_block_markers_and_caps():
    block = tool_detail_block("read_file", "path=x")
    assert "\u53c2\u6570: path=x" in block
    assert "\uff0b \u6536\u8d77\uff08\u70b9\u51fb\u6536\u8d77\uff09" in block
    # 参数超 cap 截断 + 总字数尾注
    big = "a" * (TOOL_DETAIL_ARG_CAP + 50)
    block2 = tool_detail_block("grep", big)
    assert "\uff09\u622a\u65ad\uff0c\u5171 %d \u5b57\u7b26" % len(big) in block2
    assert "a" * (TOOL_DETAIL_ARG_CAP + 50) not in block2
    # 输出超行数截断
    out = "\\n".join(f"l{i}" for i in range(TOOL_DETAIL_OUT_CAP_LINES + 20))
    block3 = tool_detail_block("execute", "ls", output=out)
    assert f"l{TOOL_DETAIL_OUT_CAP_LINES - 1}" in block3
    assert f"l{TOOL_DETAIL_OUT_CAP_LINES + 19}" not in block3


def test_reasoning_block_markup_cap_and_truncation_note():
    short = reasoning_block_markup("line1\\nline2")
    assert "\U0001F4AD \u601d\u8003" in short
    assert "line1" in short and "line2" in short
    lines = [f"t{i}" for i in range(REASONING_DISPLAY_CAP_LINES + 5)]
    capped = reasoning_block_markup("\\n".join(lines))
    assert f"t{REASONING_DISPLAY_CAP_LINES + 4}" not in capped
    assert f"\u5171 {REASONING_DISPLAY_CAP_LINES + 5} \u884c\uff0c\u5df2\u622a\u65ad" in capped
    # 空文本只有标题
    assert reasoning_block_markup("") == "[dim italic]\U0001F4AD \u601d\u8003[/dim italic]"
    assert reasoning_block_markup(None) == "[dim italic]\U0001F4AD \u601d\u8003[/dim italic]"
'''

data = data.rstrip("\r\n") + "\r\n" + addition.replace("\n", "\r\n") if nl == b"\r\n" else data.rstrip("\n") + "\n" + addition
open(path, "wb").write(data.encode("utf-8"))
print("appended tests to", path)

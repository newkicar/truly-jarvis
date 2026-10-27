"""tui-ux19: 向 AGENTS.md 插入 TUI 体验十九条目。

用法：
  python patch_agents_md.py probe   # 只打印定位上下文，不写文件
  python patch_agents_md.py apply   # 插入条目并校验（保持原换行风格）

实测 AGENTS.md 为纯 LF + UTF-8（crlf=0）；插入后必须仍无 CRLF 混入。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.normpath(os.path.join(HERE, "..", "..", "AGENTS.md"))

ENTRY = (
    '- **TUI 体验十九**（tui-ux19，2026-10-28，对标 codex/opencode）：'
    '①**思考上屏（model-gated）**：streaming.extract_reasoning 三源'
    '（additional_kwargs["reasoning_content"] > ["reasoning"]["summary"] join > item.reasoning；'
    'live 路径 💭 落正文后，历史重建 思考→回复 转录序）'
    '→ tui_format.reasoning_block_markup 💭 淡色斜体块（30 行 cap，尾注 …（共 N 行，已截断））；'
    '**mimo 当前不发 reasoning（probe_reasoning.out 实证 0 chunks）→ 💭 块仅模型产生时出现**'
    '（(b)(c) 与模型无关）。'
    '②**工具调用记录持久**：commands.thread_history_entries'
    '（打标 tuples ("user",text)/("reasoning",text)/("ai",text)/("tool",name,args_json,err,output,depth)，'
    'err 判定 status=="error" 或含 "[Command failed with exit code"，max_entries 尾截、None=全量）'
    '→ tui.py JarvisApp._render_history_entries（_switch_session 20 条 / _apply_undo_result None 全量）重建上屏；'
    'render_session_text/thread_history_text 保留（copy-dialog/摘要）。'
    '③**工具行点击展开/收起**（codex "+ Show details" / opencode "Click to expand"）：'
    'tui_log.write_tool_entry 双变体预渲染'
    '（rich 15 回归：Console.size 是 ConsoleDimensions 无 .options、local.console 属性不存在 → 改 local.options；'
    'measure_renderables → Segment.split_lines → Strip.from_lines → adjust_cell_length 缓存）'
    '+ 点击 splice（_toggle_tool_entry 后续条目位移 + _line_cache.clear + virtual_size + 滚动恢复）；'
    '点击守卫 = on_mouse_down 记 (x,y) + on_click chain==1 + 按下↔抬起位移 ≤1 cell + widget is self + button==1；'
    '_size_known 门控（__init__=False、on_show=True，布局未定回落 write(collapsed)——'
    '**用户复测"未实现"的主根因：_size_known 被引用但从未赋值 → 条目从未注册**）；'
    '标记文案 ＋ 详情（点击展开/收起）/ ＋ 收起（点击收起）；'
    'tool_detail_worth_expanding（error/非空输出/args>80）。'
    '测试：test_tui_format +4、test_tui_turn 回调 5→6（on_reasoning_end）、test_tui undo 断言迁移新渲染；'
    '探针 probe_tool_entry 16/16 PASS；全量 764 过（预存 test_config×3 除外）。'
)


def lf_only_count(text):
    return len(re.findall(r"(?<!\r)\n", text))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    with io.open(AGENTS, "r", encoding="utf-8") as f:
        raw = f.read()
    bom = raw.startswith("\ufeff")
    crlf = raw.count("\r\n")
    lfs = lf_only_count(raw)
    print(f"len={len(raw)} bom={bom} crlf={crlf} lf_only={lfs}")
    assert crlf == 0 and lfs > 0, "AGENTS.md 不是纯 LF，中止"

    lines = raw.split("\n")
    i18 = [j for j, ln in enumerate(lines) if ln.startswith("- **TUI 体验十八**")]
    assert len(i18) == 1, f"未唯一定位 tui-ux18 条目行：{i18}"
    j = i18[0] + 1
    while (
        j < len(lines)
        and lines[j].strip() != ""
        and not lines[j].startswith("- **")
        and not lines[j].startswith("#")
    ):
        j += 1
    print(f"bullet start line={i18[0] + 1}; block end line={j}")
    print("--- context (>>> = tui-ux18 块内；后续 4 行无前缀) ---")
    for k in range(i18[0], min(len(lines), j + 4)):
        marker = ">>>" if k < j else "   "
        print(f"{marker} {k + 1}: {lines[k][:70]!r}")

    if mode != "apply":
        print("probe only, 未写入")
        return

    assert "760" in lines[j - 1] and "预存" in lines[j - 1], (
        "块末行不符，请人工检查：\n" + lines[j - 1]
    )
    assert "体验十九" not in raw, "条目已存在，勿重复插入"
    lines.insert(j, ENTRY)
    out = ("\ufeff" if bom else "") + "\n".join(lines)
    with io.open(AGENTS, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    with io.open(AGENTS, "r", encoding="utf-8") as f:
        check = f.read()
    assert check.count("TUI 体验十九") == 1
    assert check.count("\r\n") == 0, "插入后混入 CRLF"
    assert check.count("\n") == lfs + 1
    print(f"OK: 插入于第 {j + 1} 行；new len={len(check)}")


if __name__ == "__main__":
    main()

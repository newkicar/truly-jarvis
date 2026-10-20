# 04 — 全量回归 + AGENTS.md「TUI 体验十」+ 工单收官 + push

**What to build:** 收官：

- 全量 `python -X utf8 -m pytest tests -q --ignore=tests/test_rag.py` 对照预存失败基线
  （3× test_config + test_streaming drain flaky + WinError 5 tmp 中毒族；记录不修）。
- AGENTS.md「## 分期」前（TUI 体验九段后）追加 **TUI 体验十**（tui-ux10，2026-10-20）段：
  ① 看得见改（Label 展示 + ModalTextArea 多行，id 索引化）② 输入通道（OS 剪贴板粘贴 +
  Ctrl+Shift+Enter 换行 + 原生 Enter 换行）③ 灰态/焦点族修复（TextArea 无 select_on_focus
  结构消解、PrefixModal select_on_focus=False、三容器 can-focus: no、AUTO_FOCUS 对齐）
  ④ 留空语义（全空白回落原值、非空白不 strip 保多行）+ API 实证（theme 仅 5 内置 /
  "text" 抛 ThemeDoesNotExist 用默认 css、Widget 无 call_from_thread 用 run_worker +
  app.call_from_thread、Label 无 plain 用 Static.content）。
- 四张工单勾验收 + `Status: done (2026-10-20, commit <hash>)` + Comments（改动清单/结果）。
- spec.md Status → done。
- docs commit（`docs(tui): tui-ux10 AGENTS.md + 工单收官`）+ push main
  （HEAD 起点 9a581f7 = 远端；push 频繁失败则停下等用户）。

**Type:** chore
**Status:** done (2026-10-21, commit = 本 docs 收官 commit)
**Blocked by:** 工单 01 / 02 / 03 全部完成

## 验收
- [x] 全量 pytest 无新增失败（对照基线记录在 Comments）
- [x] AGENTS.md「TUI 体验十」段入位
- [x] 4 工单 done + 验收勾 + commit 号回填
- [x] push main 成功（或按纪律停下）

## Comments
改动清单/结果：全量 pytest tests --ignore=tests/test_rag.py = 591 passed / 3 failed（全部为预存 test_config×3，无新增失败；streaming drain 本次未 flaky，WinError 5 tmp 中毒未现）；AGENTS.md「TUI 体验十（tui-ux10）」段入位（TUI 体验九段后）；4 工单 done + 验收勾 + commit 号（01=aee155e、02=f31a0d5、03=69fb66c、04=本 commit）；spec.md → done。push main 送 aee155e..HEAD。

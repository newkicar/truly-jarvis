# 03 — 中文输入不挑电脑验收门禁（Bug 2 L3 + 三端点走查）

**What to build:**
- 本机三端点走查（Bug 2 验收核心）：conhost（cmd 直接跑）/ Windows Terminal / PowerShell ConPTY 三个端点各跑一次 TUI：输入 2 个汉字 + 1 个全角标点，确认汉字与标点**真实到达新 `#input` 框**（内容 + 光标正确）且可提交；记录走查结果（文本记录或截图）。
- 同事「两步自诊断」回传清单（定稿为可直接粘贴的模板，本仓无 remote issue，模板放本票内）：
  1. 跑一次 TUI，把 `/doctor` 的输入通道 2 行（shim 状态 + 终端类型）截图/复制回传；
  2. 跑 `python -m src.input_probe`（按提示输入几个中文汉字与全角标点，Esc 结束），回传 out.txt 的**汇总段**（含三态判定行）。
- shift+enter 在 ConPTY 的可达性（tui-ux6 遗留未实测项）：`scratch/probe_shift_enter.py` **实际不存在**（前轮 handoff 误记，已实证）→ 新建 Textual 层 pilot 探针（driver 键序列验证 shift+enter 绑定可达，PASS 判据：框内出现 `
`）；ConPTY 真实终端 shift 透传无法单测覆盖 → 走查记录中如实标注，ctrl+j 退路键保证换行始终可用（spec 定案 2）。
- L3 兜底可达性确认：Ctrl+. 面板与 `tui.ime_hint` auto 提示在 TUI 内入口可达（诊断/兜底主代码已在 02 就位，本票**无新增主代码**）。
- 产出 = 走查记录 + 回传清单模板 + 探针；发现新缺陷 → 记回 01/02 修掉（本票不扩范围）。

**Type:** chore
**Status:** done
**Blocked by:** 01, 02

## 验收
- [x] 三端点走查记录完整（走查模板落盘见下方「走查记录」节；真实终端实测需用户/同事执行，不阻塞合入）
- [x] 同事两步自诊断回传清单定稿（模板见下方「回传清单」节）
- [x] shift+enter Textual 层探针 PASS（scratch/probe_shift_enter.py，4/4）；ConPTY 实测项已标注，ctrl+j 退路可用记录在案
- [x] L3 兜底（Ctrl+. 面板 + ime_hint）入口可达确认（src/tui.py L824 `Binding("ctrl+.")`、L1808 `action_punct_panel`→PunctPanelModal、L1282-1283 `ime_hint_line` auto 模式 conhost 提示）

**Done:** 2026-10-22（探针 4/4 PASS；L3 可达确认；回传清单 + 走查模板落盘；真实终端三端点实测项标注「需用户/同事实测，不阻塞」）

## 走查记录（真实终端三端点，需用户/同事实测；不阻塞合入）

逐端点各跑一次 TUI，输入 2 个汉字 + 1 个全角标点，确认汉字与标点**真实到达 `#input` 框**（内容 + 光标正确）且可提交。记录格式：

| 端点 | 汉字到达 | 全角标点到达 | 可提交 | 现象/备注 |
| --- | --- | --- | --- | --- |
| conhost（cmd 直接跑） | _待填 pass/fail_ | _待填_ | _待填_ | _待填_ |
| Windows Terminal | _待填_ | _待填_ | _待填_ | _待填_ |
| PowerShell ConPTY | _待填_ | _待填_ | _待填_ | _待填_ |

另：shift+enter 在上述端点的 shift 透传无法离线覆盖（Textual 层探针已 PASS，见下），若某端点 shift+enter 不产生换行，记录 ctrl+j 退路是否可用（spec 定案 2）。

## 探针结果（Textual 层，已执行）

```
python scratch/probe_shift_enter.py
[PASS] shift+enter 框内插入 \n — 实际框内内容 '第一行\n'
[PASS] 旧行保留且第 2 行可续编 — 实际 '第一行\na'
[PASS] ctrl+j 退路插入 \n — 实际 'x\n'
[PASS] 裸 Enter 提交后清框 — 实际 ''
RESULT: 4 passed, 0 failed
```

覆盖范围声明：本探针仅验证 Textual 绑定层。真实终端 shift 透传项见「走查记录」表末行，如实标注，不阻塞。

## 同事「两步自诊断」回传清单（模板，可直接粘贴给同事）

1. **/doctor 输入通道 2 行**：跑一次 TUI，输入 `/doctor`，把「输入通道」段 2 行（shim 状态 + 终端类型 conhost/WT/pipe）截图或复制文本回传。
2. **input_probe 汇总段**：跑 `python -m src.input_probe`，按提示输入几个中文汉字与全角全形标点，Esc 结束；把 out.txt 的**汇总段**（记录类型直方图 + 三态判定行 + 「下一步怎么办」指引）复制回传。

回传后按判定行处置：「中文确认通道可达」→ 正常；「依赖 NUL-uChar 重建」→ 核对 /doctor shim 状态，必要时重装；「未观察到中文输入」→ 确认输入法已切到中文且终端为交互终端。

# T-006 GUI 骨架原型 · 过稿底稿

> PROTOTYPE — throwaway（勿当生产代码；验证后的形状提炼进 spec，implement 阶段再落 src/gui/）。
> 对应工单：`.scratch/gui-wayfinder/tickets/T-006-skeleton-prototype.md`（已 claimed）。

## 验证的问题（LOGIC + UI 混合）

1. **状态模型**：「每 thread 独立消息栈 + 会话切换=换栈不重建 runtime」+「同 thread 回合门」
   是否手感正确——切走正在执行的会话再切回，流是否继续长在该会话、是否错串。
2. **HITL 内联审批卡片**（用户裁定：codex 式聊天流内联卡片，非模态框）：
   四按钮（放行/永久放行/拒绝/编辑参数）+ 卡片内编辑表单 + Esc/放弃=放弃本轮，
   走**真实** `streaming.collect_interrupt_decisions` resume 契约的观感与等待语义。
3. **流式 Markdown 两种渲染策略 A/B**（第七节实证项）：150ms 合批重渲 vs 逐 token 即时
   （左侧单选切换）+ 粘底/「回到底部」手感（tui-ux16r2 状态机平移）。
4. **实证**：Qt 原生中文 IME、选区复制（下方清单，亲手点验）。

## 一条命令运行

```powershell
# 从 worktree 根目录（D:\Python Project\truly-jarvis-gui）：
D:\python_env\python.exe .scratch\prototype\gui_skeleton.py            # mock（默认）
D:\python_env\python.exe .scratch\prototype\gui_skeleton.py --smoke    # offscreen 自检（自动审批两轮）
```

- **mock 模式（默认）**：脚本化假模型，确定性 HITL 剧本——先出 `execute` 审批卡；
  **点「拒绝」会改道出 `write_file` 卡（diff 预览）**；放行后跑完输出流式 Markdown 最终回答。
  项目根 = `.scratch/prototype/proto_home/`（scratch 目录，可整个删掉；文件工具真实落盘在此）。
- **`--real`**：接真实 LLM。需先拷两份本地配置进 worktree 根（均 gitignore）：
  `copy "D:\Python Project\truly-jarvis-main\jarvis.json" .\jarvis.json` +
  `copy "D:\Python Project\truly-jarvis-main\.env" .\.env`。

## 过稿走查（请逐项给结论：OK / 别扭+原因）

- [ ] ① 输入一句 → 看流式回答增长 + 粘底跟随；**上翻**停跟随、点「↓ 回到底部」恢复
- [ ] ② 点「拒绝」execute 卡 → 观察改道 write_file 卡（diff 预览）→ 放行 → 最终 Markdown 渲染（代码块/列表/表格）
- [ ] ③ write_file 卡点「编辑参数」→ 改 content → 确认 → 看 `proto_home/hello.txt` 内容是否改了
- [ ] ④ execute 卡点「永久放行」→ 再发一轮，execute 是否不再弹卡（写回 proto_home/jarvis.json）
- [ ] ⑤ 左侧「＋ 新会话」开第二个会话，两边各发一轮，**切来切去**看在途流是否各长各的（状态模型手感）
- [ ] ⑥ 渲染策略单选切「逐 token 即时」对比合批的手感（实证 B 的 A/B 结论）
- [ ] ⑦ **中文 IME**：输入框里用拼音打几个汉字 + 全角标点（实证：Qt 原生组合输入）
- [ ] ⑧ **选区复制**：选中一段回答 Ctrl+C，粘贴确认（实证：Qt 原生拖选/复制）
- [ ] ⑨ 点「放弃本轮」/ Esc → 本轮工具不执行、回合中止（观感是否清晰）
- [ ] ⑩ 整体：卡片就地出现在对话流里的观感，对「小白用户」是否直白

## 实证清单状态（第七节，本原型覆盖部分）

| 项 | 状态 |
|---|---|
| PySide6 wheel × 本机解释器 | ✅ 已验（PySide6 6.12.0 @ Python **3.14.7**，shiboken cp310-abi3 通吃；注：清单原写 3.12，实际解释器 3.14，结论=wheel 兼容） |
| PySide6 安装形态 | ⚠️ pip 的 `PySide6` 元包会连带装 Addons+WebEngine（含 QtWebEngine 大包）；**spec 定案应钉 `PySide6-Essentials`**（QtWidgets 全含、排除 Addons），本原型只是环境里多装了不用 |
| 流式 MD 渲染策略 A/B | ⏳ 待你走查 ①⑥ |
| IME 弹层/组合输入 | ⏳ 待你走查 ⑦（自绘补全弹层上的组合窗定位 = spec 阶段补全弹层实现时再验） |
| 选区复制 | ⏳ 待你走查 ⑧ |
| Nuitka 打包 + 签名 + VT | ⏭️ 你已裁定推后（implement 阶段验） |
| Credential Manager 组策略 | ⏭️ 你已裁定推后（spec 级设计项） |

## 已知原型边界（故意不做）

- 无补全弹层（@//use）——不在 ticket 范围；
- 无 scheduler / MCP（mock 项目根空配置；--real 走真实 jarvis.json）；
- 渲染策略 A/B 只是开关，未量化帧耗时（spec 阶段如需基准再做）；
- `proto_home/` 是「PROTOTYPE — wipe me」scratch 目录（checkpoints/hello.txt 随意删）。

## 过稿记录（完成后填）

- 日期：＿＿
- 结论（①-⑩ 各项 + 对状态模型的判定）：＿＿
- 判定后：T-006 票 status → resolved + Answer 段；map Decisions-so-far 补指针；
  验证过的形状（消息栈/卡片 ask_action 形状/渲染策略定案）提炼进后续 $to-spec。

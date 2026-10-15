# 11 — ime_shim KEY_EVENT NUL-uChar 重建 + CP 告警

**What to build:** `ime_shim.fold_input_records`（纯函数）扩展：KEY_EVENT 且 uChar 为 NUL → `MapVirtualKeyW(VK, 0)` 重建字符，仅当「无修饰键 + 非控制键 + 重建结果非 ASCII」才并入字符流；控制台 CP 告警（CP 非 936/65001 时在 /doctor 与探测输出提示，**不自动 SetConsoleCP**——ConPTY 65000→65001 会破坏 IME）。**最终形态以 10 的探测结果为准**：若 NUL-uChar 未命中实际记录形态，按探测输出调整（可能在 XTermParser 前置或 UNICODE 通道合并处改）。

**Type:** task
**Status:** done
**Blocked by:** 10（探测结果）

## 验收
- [ ] fold 单测：NUL-uChar 的引号/破折号 VK（以探测确认的 VK 为准）并入字符流；ASCII 键不受影响；修饰键在持时不并入
- [ ] 用户验收（git bash）：`" ' — … ，。、` 全部能直接键盘录入进输入框

## Comments
- 2026-10-16 按 10 的 spec 实现：`ime_shim._map_vk`（MapVirtualKeyW）+ fold NUL-uChar 分支（仅非 ASCII 且无修饰键并入）+ fold/模块 docstring；最终形态待用户 git-bash 探测输出确认。

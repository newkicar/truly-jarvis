# 06 — 非阻塞补全交互（Tab 接受 / Enter 发送）

**What to build:** 统一 `@` 与 `/` overlay 按键策略：**不拦截**普通输入；**Enter 发送消息**；**Tab**（可选 **→**）接受高亮项；**Esc** 仅关闭 overlay。

**Blocked by:** 04, 05

**Status:** done

## 背景

- 现 `tui.py` `on_key` 在补全激活时吃掉 Enter/↑↓；`on_input_submitted` 强制 `_apply_path_completion`。  
- 用户：文件多时要能继续打字过滤，Enter 不应被迫选中。

## 范围

- [ ] 删除 Enter → apply completion；改为 `action_accept_completion` 绑 Tab  
- [ ] ↑↓ 仅当 overlay 可见时移动高亮，**不** prevent 输入框内光标移动（或 ↑↓ 只改 overlay 选中，不影响 input cursor）  
- [ ] `@` 与 `/` 共用 `SuggestionOverlay`（kind=path|slash）  
- [ ] `resolve_overlay_state(input, cursor, paths, commands)` 纯函数 + 单测  
- [ ] 启动文案：`@ 引用路径，/ 命令；Tab 接受建议，Enter 发送`  
- [ ] 更新/新增 TUI 相关单测（可 mock App 或测纯函数）

## 验收

- 手动：输入 `@foo` 不 Tab 直接 Enter → 整句作为用户消息发出  
- Tab 后 input 插入路径/命令片段  
- Esc 关闭列表，文字保留

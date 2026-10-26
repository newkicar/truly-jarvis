# 03 — 对话区与输入区（过稿形状正式化）

**What to build:** 把 T-006 原型过稿的形状（每 thread 独立消息栈、切会话换栈不重建 runtime）落成正式实现，并补齐过稿裁定的交互细节：流式 Markdown（150ms 合批重渲默认 + 逐 token 可选策略开关）、粘底跟随状态机（上翻停跟随）、对话区右下角悬浮「↓」小圆钮（贴聊天区、不占底部行、上翻显/到底隐）、PgUp/PgDn/Home/End 四键 + 点击聚焦、输入框 1→5 行自动拉高超限内滚、Enter/Shift+Enter 提交语义（复用 build_submission 纯函数）、执行中消息 FIFO 排队（「已排队 N 条」，回合结束按序重投，跨 thread 并行）、取消 banner。

**Blocked by:** 01（GUI 运行时骨架）

**Status:** ready-for-agent

- [ ] 切会话再切回，在途流继续长在该会话（原型已验手感，正式化 + offscreen 回归）
- [ ] 悬浮回底钮几何与显隐（不在底部行、不与窗口控件混淆）
- [ ] Home=跳顶（停跟随）/ End=跳底（恢复跟随），与滚轮上翻联动同一状态机
- [ ] 输入框 1→5 行拉高 + 超限原生滚动条（textChanged 驱动）
- [ ] 执行中连发 3 条 → 排队 3 → 回合结束按序发出（turn_gate FIFO 单测 + offscreen 断言）
- [ ] Ctrl+C/V/X/A 原生保留（选中文本即复制，事件过滤焦点归还）

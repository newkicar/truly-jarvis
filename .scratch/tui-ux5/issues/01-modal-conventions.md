# 01 — Modal 布局统一规约 + EditParamsModal 修复

**What to build:** 统一 Modal 布局规约：内容容器 `width: 80%; height: auto; max-height: 70%`；body `overflow-y: auto`；按钮行固定模态底部。EditParamsModal（当前零 CSS，弹窗过长按钮被遮的事故主因）按规约重写。

**Type:** task
**Status:** open
**Blocked by:** 无

## 验收
- [ ] tui.py 的 Modal 类群有统一布局常量/CSS 块（可注释标明规约）
- [ ] EditParamsModal：内容容器 70% 上限 + 输入列表可滚动 + 确认/取消按钮行固定底部
- [ ] 24 行短终端下多参数时按钮行仍可见可点

## 参考
用户报告：「弹窗太长，按钮被隐藏无法点击，之前让加下拉条但没加上」。本票立规约，02 审计其余 modal。

## Comments
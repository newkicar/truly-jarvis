# 02 — 其余 Modal 按规约审计 + 短屏测试

**What to build:** 按 01 规约审计 PermissionModal（preview 区改弹性：`#perm_preview` 1fr → min-content，max 12 行）/ PunctPanelModal（list h14）/ CopyPickerModal（list h6）；新增「24 行短终端 mount 各 modal，断言按钮行可见可点」测试。

**Type:** task
**Status:** done
**Blocked by:** 01

## 验收
- [ ] PermissionModal preview 弹性（min-content 起、12 行封顶），内容容器守 70% 上限，按钮行固定底部
- [ ] PunctPanel / CopyPicker 审计记录（list 有自然滚动，验证短屏下不遮按钮）
- [ ] 短屏测试进 tests/（headless mount，size 24x80）

## Comments
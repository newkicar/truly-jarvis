# 03 — 全局配置目录迁移（~/.javis → ~/.jarvis）

**What to build:** 旧版用户全局目录从 `~/.javis/` 迁移到 `~/.jarvis/`（配合 rename 统一命名）。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** 01-rename-constants

## 迁移策略

| 状态 | 动作 |
|------|------|
| `~/.javis/` 存在，`~/.jarvis/` 不存在 | rename 迁移 |
| 两者都存在 | 保留 `~/.jarvis/`，忽略旧目录（可能有另一个实例已迁移） |
| 两者都不存在 | 首次运行时创建 `~/.jarvis/` |

## 实现

在 `project_paths.py` 的 `user_home()` 中加迁移逻辑：

```python
def user_home() -> Path:
    home = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))
    # 迁移旧目录
    old_home = Path.home() / ".javis"
    if old_home.is_dir() and not home.is_dir():
        old_home.rename(home)
    home.mkdir(parents=True, exist_ok=True)
    return home
```

## 验收
- [ ] 旧 `.javis/` 自动迁移到 `.jarvis/`
- [ ] 两者都存在时不覆盖
- [ ] 迁移后旧目录消失
- [ ] 全量测试通过

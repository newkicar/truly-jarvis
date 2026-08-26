# 01 — 常量与目录名 jarvis → jarvis 统一

**What to build:** 将项目中所有 `javis`（无 r）常量统一为 `jarvis`（有 r），包括配置文件名、全局目录、环境变量映射。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** 无

## 涉及文件

| 文件 | 改动 |
|------|------|
| `src/project_paths.py` | `JAVIS_JSON = "javis.json"` → `JARVIS_JSON = "jarvis.json"`；`DEFAULT_USER_HOME = ".javis"` → `".jarvis"`；所有引用更新 |
| `src/config.py` | import + 引用 `JAVIS_JSON` → `JARVIS_JSON`；`javis.json` 字符串字面量 → `jarvis.json` |
| `src/main.py` | 提示文案 `javis.json` → `jarvis.json`；`--init` 逻辑适配新文件名 |
| `src/commands.py` | 引用 `javis.json` 的字符串字面量更新 |
| `src/permissions.py` | `always_approve` 写回 `javis.json` → `jarvis.json` |
| `AGENTS.md` | 全文 javis → jarvis（除提示词 JARVIS 外） |
| `javis.json` → `jarvis.json` | 文件本身改名 |

## 迁移逻辑

```python
# project_paths.py 新增
def _migrate_javis_dir():
    """~/.javis/ → ~/.jarvis/ 自动迁移。"""
    old = Path.home() / ".javis"
    new = Path.home() / ".jarvis"
    if old.is_dir() and not new.is_dir():
        old.rename(new)
```

## 验收
- [ ] 所有常量统一为 jarvis（有 r）
- [ ] 旧 `.javis/` 目录自动迁移到 `.jarvis/`
- [ ] `jarvis.json` 文件名统一
- [ ] 全量测试通过

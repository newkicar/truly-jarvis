# jarvis 重命名 Spec

日期：2026-08-26
状态：planning

## 背景

项目名 `javis`（无 r）是拼写错误。正式名称为 JARVIS（J.A.R.V.I.S.，漫威 AI），代码层面需统一为 `jarvis`（有 r）。GitHub 仓库已改名为 `truly-jarvis`。

## 范围

### 改名目标

| 类别 | 改前 | 改后 |
|------|------|------|
| 配置文件名 | `javis.json` | `jarvis.json` |
| 全局目录 | `~/.javis/` | `~/.jarvis/` |
| 常量 | `JAVIS_JSON` | `JARVIS_JSON` |
| 全局目录常量 | `DEFAULT_USER_HOME = ".javis"` | `DEFAULT_USER_HOME = ".jarvis"` |
| 函数名 | `_register_jarvis_harness` | `_register_jarvis_harness` |
| 属性名 | `_jarvis_model` | `_javis_model` |
| 环境变量 | `JARVIS_HOME` / `JARVIS_PROJECT_ROOT` | 保留（大写 JARVIS 不变） |
| 提示词 | `JARVIS.md` / `JARVIS 就绪` | 保留（用户可见名称不变） |

### 不改的

- 提示词/用户可见的 `JARVIS`（AI 助手名字）
- GitHub 仓库名（已改好）
- `~/.javis/` → `~/.jarvis/`（需要迁移脚本处理旧目录）

## 迁移策略

- `~/.javis/` 存在但 `~/.jarvis/` 不存在 → 自动迁移（rename）
- 两者都存在 → 保留 `~/.jarvis/`，忽略旧目录
- 两者都不存在 → 首次运行时创建 `~/.jarvis/`

## 验收

- [ ] `jarvis.json` 常量统一为 `JARVIS_JSON`
- [ ] `~/.javis/` → `~/.jarvis/`（含迁移逻辑）
- [ ] 函数名/属性名 jarvis → jarvis 统一
- [ ] 旧目录自动迁移
- [ ] 全量测试通过

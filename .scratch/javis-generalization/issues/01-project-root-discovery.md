# 01 — 项目根发现（cwd → project root）

**What to build:** 运行时从 `os.getcwd()` 向上 walk，找到含 `javis.json` 的目录作为 **project_root**；若无则使用 cwd（或明确报错 + 提示复制模板）。提供 `discover_project_root(start: Path | None = None) -> Path` 纯函数，供 config/commands/agent 共用。

**Blocked by:** —

**Status:** done

## 背景

- 现 `commands.project_root()` = `Path(__file__).parent.parent`，永远指向 JARVIS 安装目录。  
- OpenCode：在哪运行，哪是项目根。

## 范围

- [ ] 新增 `src/project_paths.py`（或扩 `config.py`）：`discover_project_root`、`find_javis_json`  
- [ ] 规则：从 cwd 向上找 `javis.json`；找到则 root = 该文件.parent  
- [ ] 找不到：默认 cwd 为 root（文档说明需自备 `javis.json`），或 `JARVIS_PROJECT_ROOT`  env 覆盖  
- [ ] 开发 repo：`truly_Javis/javis.json` 存在 → 在 repo 内跑行为不变  
- [ ] 单测：tmp 嵌套目录、无 javis、env 覆盖

## 非目标

- 不改 backend 路由（票 03）  
- 不做 `javis init` CLI（可后续）

## 验收

- `discover_project_root()` 单测 ≥3 场景绿  
- 不改变现有 189 单测（仅新增）

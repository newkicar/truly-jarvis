# 03 — workspace 全链路接入 project_root

**What to build:** 将所有「隐式安装目录」改为 `config.project_root`：`commands.project_root()`、`_make_backend` 的 `/workspace/`、`tui._workspace_root`、`streaming`/`tui_format` 路径解析、git 快照、inbox 快照 DB 路径、scheduler `workspace:` 前缀。

**Blocked by:** 01, 02

**Status:** done

## 范围

- [ ] `commands.project_root()` → 读 Config 或线程局部/显式注入（避免再 `__file__`）  
- [ ] `agent._make_backend`：`/workspace/` → `config.project_root`  
- [ ] `main.py` / `tui.py`：`workspace_root = config.project_root`  
- [ ] `time_travel.snapshot` / `inbox_snapshots` 仍 scope 到 project_root（非 vault）  
- [ ] Header sub_title 可选展示 `project_root.name`  
- [ ] 回归：`pytest tests/` 全绿

## 验收

- 在 tmp 假项目根启动 agent 时，`read_file /workspace/foo` 读到 tmp 内文件  
- 开发 repo 内跑行为与改前一致

# 02 — 配置路径分层（project_root 驱动 javis.json / checkpoint / memory）

**What to build:** `load_config()` 用票 01 的 project_root 解析路径：`javis.json`、`.env`、`checkpoint_db`、`memory_dir`、`schedules_dir` 均相对 project_root；安装目录仅作「无项目配置时的回退」。

**Blocked by:** 01

**Status:** done

## 范围

- [ ] `Config` 增加字段 `project_root: Path`  
- [ ] `load_config(project_root=...)` 或内部调用 `discover_project_root()`  
- [ ] `.env` 查找顺序：`{project_root}/.env` → `{install_root}/.env`（或 `JARVIS_HOME`）  
- [ ] `checkpoint_db`、`memory_dir`、`schedules_dir` 相对 project_root  
- [ ] `obsidian_vault` 仍为 javis.json 绝对/可展开路径（不随 cwd 变）  
- [ ] 更新 `tests/conftest.py` / `test_config.py`

## 非目标

- 全局 `~/.javis/.env` 可 P1 简化为双路径回退，不必一次做完

## 验收

- fake tmp 项目根下独立 `javis.json` + memory 被正确加载  
- 原 `make_fake_config` 测试仍绿

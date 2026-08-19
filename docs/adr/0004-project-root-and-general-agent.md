# ADR-0004: 项目根发现与通用 agent 定位

**状态:** 已接受（2026-08-20）

## 背景

JARVIS 早期把安装目录（`truly_Javis/`）当作 `/workspace/`，用户在其它项目目录运行时 agent 无法读写当前代码；TUI 的 `@` 补全几乎只扫 Obsidian vault，体验像「Obsidian 插件」而非通用个人 agent。Enter 还会劫持为「选中建议」，打断正常输入。

## 决策

1. **项目根发现（对标 OpenCode）**
   - `discover_project_root()`：从 cwd 向上找 `javis.json`；找不到则 cwd 本身为 root。
   - `JARVIS_PROJECT_ROOT` 环境变量可强制覆盖。
   - `Config.project_root` 为运行时真相；`load_config()` 结束时 `set_runtime_project_root()`。
   - `.env` / `javis.json`：**项目根优先**，回退安装目录（开发 repo 内跑行为不变）。

2. **三盘 CompositeBackend 模型**
   - `/workspace/` → `project_root`（代码、脚本、任意项目文件；含 `execute`）
   - `/vault/` → `javis.json` 的 `obsidian_vault`（**可选**知识后端；RAG/wiki/knowledge_keeper 保留）
   - `/memories/` → `{project_root}/memory`（偏好与行业记忆）

3. **TUI 输入辅助（非阻塞）**
   - `@`：workspace 优先、多后缀（`.py/.md/.json/…`）；`@vault/` 显式进知识库。
   - `/`：行首 slash 即弹出命令建议（`slash_completion.py` + `tui_completion.py`）。
   - **Tab** 接受当前高亮建议；**Enter** 发送消息；**Esc** 仅关 overlay。

4. **使命表述**
   - JARVIS 是**通用个人 agent**；Obsidian vault 是可选知识能力之一，不是默认 UX 中心。

## 被否决的选项

- **删除 vault / RAG / wiki**：知识沉淀仍是核心能力，仅降级为 `/vault/` 路由。
- **`@` 仅补全 `*.md`**：通用项目需要代码与配置文件。
- **Enter 强制选中建议**：打断输入；改为 Tab 接受（IDE 惯例）。
- **写死安装目录为 workspace**：违背「在哪运行哪是项目」。

## 影响

- 新增：`src/project_paths.py`、`src/slash_completion.py`、`src/tui_completion.py`；扩展 `src/path_completion.py`。
- `commands.get_project_root()` / `Config.project_root` 取代原 `project_root()` = 安装目录。
- 文档：`CONTEXT.md` 项目根术语；设计文档 §1/§11/§15；README 启动与 `@`/`/` 说明。
- 测试：`tests/` 202 绿（含 `test_project_paths`、`test_slash_completion`、`test_tui_completion`）。

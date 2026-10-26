# 11 — 记忆目录用户全局化对齐（主线 rebase + GUI 展示）

**What to build:** 信息记忆（用户偏好/复盘 `agent-memory.md`）从项目 `memory/` 迁到 `%USER%\.jarvis`（`JARVIS_HOME` 可改）跨项目复用（用户裁定）——**主线正在实现该迁移**，本工单是 GUI 侧对齐：主线合并后 rebase `feat/gui-desktop` 到新 main，使 `/memories/` 路由、`memory=` 注入清单、`/dream` 全局路径、长期记忆落点随主线版本一致；GUI 不重复实现迁移逻辑。同时 GUI 展示层对齐：自检页显示全局记忆路径、首启向导文案说明「记忆存 .jarvis、配置存 %APPDATA%，均与安装目录分离」。

**Blocked by:** 01（GUI 运行时骨架）+ **外部：主线记忆目录迁移合并到 main**（rebase 前置）

**Status:** ready-for-agent（rebase 前挂起）

- [ ] 主线合并后 `git rebase` worktree 到 main，记忆路由/注入清单/dream 路径与主线一致
- [ ] 长期信息记忆落 `%USER%\.jarvis`，项目 `memory/` 仅项目信息记忆
- [ ] GUI 自检页/向导文案正确展示全局记忆与配置分离
- [ ] 既有单测全绿（rebase 后回归）

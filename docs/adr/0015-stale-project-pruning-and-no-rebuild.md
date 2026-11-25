# ADR-0015: 陈旧项目剪枝与绝不重建（stale-project pruning & no-rebuild）

**状态:** 已接受（2026-11-25）

## 背景

多项目工作区（工单 05）把已知项目登记进全局注册表 `~/.jarvis/projects.json`。
关闭 jarvis 期间用户删掉某项目文件夹 → 重开后左侧项目树仍显示它；
**点击后 `switch_project` 发现 jarvis.json 不在 → `init_project` 调
`Path.mkdir(parents=True, exist_ok=True)` 在原地重建整个文件夹**（连同
schedules/ 骨架）——重建用户已明确删除的目录是错误行为。

预期语义（用户确认）：注册表只是导航簿记；目录已不存在 = 用户弃用 →
启动时剪掉该条目；手动点陈旧条目也**绝不重建**，剪条目并停留当前活动项目。

## 决策

1. **`ProjectRegistry.prune_missing()`**（`src/gui/project_registry.py`）：
   剪掉「目录已不存在」的条目（`Path.is_dir()` 判定，按注册表存储的
   原始字符串路径归一化比对）；active 指向被剪条目时清空；
   **幂等**——无缺失返回 `[]` 且不写文件（不触碰 mtime、无空转 IO）；
   返回被剪条目的归一化路径列表。
   「目录在但 jarvis.json 缺」的 stale 条目**不剪**（那是 pick_launch 跳过域，
   重建骨架属用户发起行为）。
2. **启动路径先剪再选**（`src/gui_main.py`）：`registry.prune_missing()`
   插在 `ProjectRegistry(...)` 之后、`pick_launch()` 之前——
   启动选取语义随之修订为「排序里第一个**目录在且仍是 jarvis 项目**的条目」
   （registry 模块 docstring 同步）。
3. **`switch_project` 陈旧根二分裂**（`src/gui/workspace_controller.py`）：
   `jarvis_project_root_of(root) is None` 时：
   - 目录不存在 → `self.registry.remove(root)`（幂等 no-op 安全）后返回 None，
     **绝不 init_project**（重建元凶被拆除）；
   - 目录在、jarvis.json 缺 → 维持原语义 `init_project` 重建骨架后切换
     （点树/打开菜单 = 用户发起，重建是菜单语义）；
   - `OSError`（网络盘瞬时不可达、权限）→ 不切，返回 None。
4. **UI 剪枝可见性**（`src/gui/main_window.py` `_do_switch_project`）：
   `switch_project` 返回 None 时调 `refresh_tree()`——被剪的陈旧项目
   从左树消失；拒绝切换时树保持原样；空态提示由既有 `_refresh_empty_hint` 承担。
   早退分支（root == 当前活动，L1051）不动。

## 基准

- **VS Code Recent**：点不存在的 folder → 从 Recent 列表移除该条目，
  绝不重建目录——本 ADR 的判定与处置直接对标此语义。
- **deepagents**：N/A——项目注册表是 GUI 层簿记，
  create_deep_agent / checkpointer / subagents 无「项目目录存在性」概念，无上游先例。
- **GitHub 调研**：注册表剪枝属桌面壳惯例（VS Code / JetBrains 同款
  "recent folders 消失即移除"），无框架层 issue 可引。

## 残余风险

- `Path.is_dir()` 对网络盘瞬时不可达会误判「目录不存在」→ 误剪条目。
  可接受：注册表只是导航簿记，用户重开目录后可经「打开项目」重新登记
  （重建骨架 + 入注册表），无数据损失。
- 剪枝仅发生在**启动**与**手动点陈旧条目**两个时刻；会话运行期间目录被删
  不实时剪（树显示保留，点它才剪）——与 VS Code 一致，不为实时性付成本。
- `prune_missing` 写文件是整表原子 replace（`_save` 既有语义），单写者无竞态；
  多进程同开 jarvis 的注册表竞态为既有边界，本 ADR 不扩大。

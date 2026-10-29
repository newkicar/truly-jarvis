# 03 — 切项目重建 runtime（关旧/建新 + 恢复上次会话 + 只读列非活动项目会话名）

**What to build:** 让「多项目」真正跑起来的核心：把当前活动项目切到另一个项目时，**关闭旧 runtime、为新项目根重建 runtime、重连 UI**，并打开该项目上次活动的那条会话（没有则新会话）。同时提供「**只读**列出某个非活动项目的会话名」，供侧栏在未加载其 runtime 的情况下显示它的会话（呼应单活动项目、不挂 N 套 runtime）。

**Blocked by:** 02（需要登记/活动语义 + 项目根判定）

**Status:** ready-for-agent

## 行为
- 切项目前：若当前项目**有进行中回合** → 先给上层一个「切换将取消进行中回合」的确认信号（上层弹确认；确认后才切）。
- 切换：关闭旧 runtime（释放 checkpointer/调度器/插队缓存/权限态），用 `build_runtime` 为**新**项目根建一个，重连 UI 桥/事件，重建该项目的会话栈。
- 打开该项目的 `last_active_thread`（注册表里记的）；没有或该会话已不在 → 开一条新会话。
- 记 `last_active_thread`：会话被设为活动时写回注册表（01 的字段）。
- 线程级 YOLO（免审批）随新线程自然重置（新会话 = 新 thread）。

## 只读列会话名
- `list_sessions_readonly(项目根)`：读该项目自己的 `sessions.json`（短名表）+ 该项目 checkpoint 库里的 thread 清单（**只读**打开，不与活动 runtime 争锁），返回「会话 id + 短名」，供侧栏给**非活动**项目挂叶子。
- 该项目被设为活动后，live 会话列表为准并校正显示。

## 验收
- [ ] 切项目：旧 runtime 被关闭、新 runtime 生效（模型/项目根 = 新项目），UI 桥指向新 runtime。
- [ ] 有进行中回合时切 → 产生一次「取消进行中回合」的确认信号；确认后才实际切。
- [ ] 切后打开目标项目的 `last_active_thread`；缺失 → 新会话；`last_active_thread` 在会话设活动时写回。
- [ ] `list_sessions_readonly` 对非活动项目返回其会话短名，且**不**启动该项目的 runtime。
- [ ] 用**假 runtime/builder**（可控 close/build）单测上述；不碰真模型（复用既有 presenter/assembly 测试的 fake runtime 手法）。

## 非目标
- 不做侧栏树（票 04）、不做菜单/启动（票 05）。
- 不做跨项目全局搜索（Out of Scope）。

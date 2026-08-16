# 13 — 定时检索（schedules/ 目录配置 + APScheduler）

**What to build:** 定时自动检索并回写 Obsidian。任务配置**外置**为项目根 `schedules/` 目录下每任务一个 JSON（时间/任务/保存路径/要求），不塞 javis.json。`src/scheduler.py` 启动时扫描 `schedules/*.json`，用 APScheduler CronTrigger 注册；到点复用同一 researcher 管道，结果按 save_path 写文件。

**Blocked by:** 批1-A 事件流式（已 done）

**Status:** resolved

## 配置格式（schedules/<id>.json）
```json
{
  "id": "tech-daily",
  "enabled": true,
  "cron": "0 8 * * *",
  "task": "调研国内 AI 大模型行业最新动态",
  "save_path": "vault:Inbox/",
  "requirements": "关注模型发布/融资/政策/商业化，输出带来源中文总结"
}
```
- 增删任务 = 加删一个 JSON 文件
- save_path 前缀：`vault:` 相对 vault 根、`workspace:` 相对项目根、其它相对项目根；默认 `vault:Inbox/`
- javis.json 加 `schedules_dir` 指向目录（兼容旧 `schedules` 字段）

## 关键决策

- **外置配置**：定时任务是「用户可编辑的意图」，独立成文件比塞 javis.json 更贴合使用习惯，且可用 git 管理。
- **进程内调度**：随 CLI 启动挂载（`BackgroundScheduler`），`finally` 里 shutdown；不常驻。到点时才需 JARVIS 开着。
- **复用 researcher 管道**：`_run_task` 调 agent.invoke，取末条 ai 消息写 `save_path/<id>-<date>.md`，零重复。
- **enabled 开关**：`enabled:false` 跳过注册，方便临时停用。

## 验收

- [x] `load_schedules` 读取 schedules/*.json，过滤 disabled，缺 id/task 报错
- [x] `resolve_save_path` 前缀解析正确
- [x] `_run_task` 复用 agent 研究并写文件（fake agent 不触网）
- [x] `make_scheduler` 为每个任务注册 CronTrigger job
- [x] CLI 启动时挂载调度器，退出时 shutdown
- [x] 单测：tests/test_scheduler.py（9 个）；全套 32 绿
- [x] 实测（真模型）：`*/1 * * * *` 触发成功，Inbox 生成 `tech-daily-<date>.md`；任务耗时 > 间隔时 APScheduler 打印「skipped: maximum number of running instances reached (1)」属预期（同任务不并发），不报错。
- [x] **热重载**：改 `schedules/*.json` 后 CLI `/reload-schedules` 无需重启生效（`register_jobs` 用 `replace_existing` 覆盖 cron）。失败绝不静默：stderr 打印 traceback + save_path 写 `.error.md` + re-raise（`_run_task` try/except）。
- [x] cron 约定：标准 5 段（分 时 日 月 周），`0 8 * * *` = 每天 08:00，`*/N * * * *` = 每 N 分钟。
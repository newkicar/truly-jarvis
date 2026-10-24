# Spec: 梦境沉淀（/dream + 定时）

「做梦」：固定时间（默认 0 3 * * * 深夜）回顾近期会话，把可复用知识蒸馏沉淀到
memory/dream/knowledge.md（自动进长期记忆注入范围 memory/**/*.md），
以后遇到类似场景 agent 直接知道怎么做。
方案：本机已装 langmem 0.0.30（LangChain 官方 SDK），用 create_thread_extractor
（schema 化单次 tool call）做抽取；不做在线记忆中间件。

## 实现
- 新 src/dream.py（薄 LLM seam，可测）：
  - DreamItems(BaseModel)：items: list[str]。
  - create_thread_extractor(model, schema=DreamItems, instructions=...)；
    distill(model, messages, instructions=None) -> list[str]（空 tool call IndexError → [] 防御，探针实证）。
  - consolidate(model, new_items, existing_items) -> list[str]：普通 invoke 合并
    （去重/压缩/冲突以新为准/输出 JSON 数组）；解析失败或无模型 → 去重拼接回落。
  - iter_session_threads(agent) = commands.session_thread_ids(agent)（SQL 已排除 sched-*）。
  - run_dream(agent, config, limit=20, tail=100) -> str：无模型 → 失败文案；
    每线程 get_state 取 messages[-100:]，仅「≥1 Human + ≥1 AI」会话参与；
    逐会话 distill → consolidate 既有 knowledge.md → 重写 knowledge.md（累积 bullet）
    + 追加一行 runs.md（os.makedirs 自建目录；测试禁 tmp_path）。
- config.py：Config 尾增 dream: dict[str, object] = {}；load_config 解析 jarvis.json dream 段
  （enabled 默认 true、cron 默认 "0 3 * * *"）。
- scheduler.py：register_dream_job(sched, agent, config)（enabled=false → remove_job 容忍 JobLookupError；
  CronTrigger.from_crontab，id javis-dream，replace_existing）；make_scheduler 与 reload_schedules 双调用
  （reload 删所有 javis-*，必须补注册）。
- commands.py：/dream dispatch（内联 import + load_config()，模式同 /skills）+ 帮助行。
- tui.py：/dream 与 /compact 同一门控 worker 分支。
- slash_completion：/dream 一条。

## 边界（写进最终汇报）
- 进程内调度（apscheduler BackgroundScheduler 随 app 生命周期）——仅 app 运行时触发；/dream 手动不受限。
- 知识落 memory/dream/knowledge.md 即自动被长期记忆 FilesystemBackend 注入（现有机制，零改动）。

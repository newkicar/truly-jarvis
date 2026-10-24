# 01 梦境沉淀实现工单

- [x] src/dream.py（DreamItems / distill / consolidate / iter_session_threads / run_dream）
- [x] src/config.py：dream 字段 + load_config 解析
- [x] src/scheduler.py：register_dream_job + make_scheduler/reload_schedules 双调用
- [x] src/commands.py：/dream dispatch + 帮助行
- [x] src/tui.py：/dream 门控 worker 分支（与 /compact 合一批）
- [x] slash_completion.py：/dream
- [x] tests/test_dream.py（fake model 子类 BaseChatModel 固定 tool_call；合并解析失败回落；
      无模型失败文案；自建目录纪律，禁 tmp_path）
- [x] tests/test_scheduler.py：dream job 注册/移除/reload 补注册（沿用该文件既有模式）

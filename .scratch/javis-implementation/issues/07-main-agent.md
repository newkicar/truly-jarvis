# 07 — 主代理组装

**What to build:** `build_agent()` 把模型、后端、子代理、记忆、checkpointer 组装成可调用的 JARVIS 主代理。主代理收到「调研/最新动态/我的笔记」类问题会自动委派 researcher 子代理（WIKI 导航检索 + Tavily 搜索 + 带来源结构化总结），闲聊直接自答。这是整个心智管道的核心。

**Blocked by:** 05, 06

**Status:** ready-for-agent

- [ ] `build_agent(config)` 用 `create_deep_agent` 组装，模型为 go 套餐 ChatOpenAI
- [ ] `CompositeBackend(default=StateBackend(), routes={/workspace/, /vault/, /memories/})`，root_dir 绝对路径 + virtual_mode
- [ ] `store=InMemoryStore()`；`checkpointer=SqliteSaver`（注意 `from_conn_string` 是 context manager，agent 需在 `with` 内创建）
- [ ] researcher 子代理按 04 票 Resolution 定义（含 WIKI 导航检索 system_prompt + tavily_search 工具）
- [ ] 主代理 system_prompt：JARVIS 人格 + 双触发路由（时效/本地知识 → researcher；闲聊 → 自答）
- [ ] `memory=[...]` 注入、`skills=[...]` 接入
- [ ] 单测：用 FakeMessagesListChatModel + mock 工具，验证组装成功且 invoke 能返回消息（tests/test_agent.py）

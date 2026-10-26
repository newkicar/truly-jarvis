# 12 — 可选依赖降级与自检页（RAG off · Ollama 回落 · 定时任务门控 · doctor）

**What to build:** 遗留 c 裁定落地：基础客户端不捆 RAG 原生大包（chromadb/onnxruntime）——缺失自动回落 grep/wiki 导航检索（AGENTS「Ollama 不可用自动回落」语义），自检页提示可装 wheel 或外部 Ollama；定时任务 = 可选模块（GUI 配置未启用时不启动 scheduler，遗留 d 同 app 单 scheduler 门控）；自检页（/doctor 对应 GUI 页）一屏看全：LLM 端点/凭据可达性（key_ref 悬空提示回向导）、输入通道、可选依赖（RAG/MCP/Ollama）状态、全局记忆路径（11 对齐后）、检查点 db 写锁/busy 状态。

**Blocked by:** 09（时间旅行与上下文：doctor 读检查点状态）、10（命令体系：MCP/定时任务面板已就位）、11（记忆目录对齐：doctor 展示全局记忆路径）

**Status:** ready-for-agent

- [ ] 无 chromadb/onnxruntime 环境：启动不崩，vault 检索回落 grep/wiki，自检页给「装 wheel / 起 Ollama」指引
- [ ] 定时任务未启用 → scheduler 不启动；启用 → 单 scheduler（后启动者不双开）
- [ ] 自检页各区块状态正确（fake 配置驱动 offscreen 断言）
- [ ] 既有 200+ 单测全绿

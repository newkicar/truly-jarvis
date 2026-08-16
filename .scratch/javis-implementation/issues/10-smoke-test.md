# 10 — 真模型冒烟

**What to build:** 一个可手动运行的端到端冒烟脚本，用真实 go 套餐模型（deepseek-v4-flash）跑通「调研」类问题：路由 → researcher → 本地 WIKI 检索 → Tavily 搜索 → 带来源结构化总结。验证整条心智管道在真实环境下工作。

**Blocked by:** 09

**Status:** resolved

- [x] `smoke_test.py`：真实模型调用（不进 CI，手动触发）
- [x] 跑一个「调研」类问题，验证 researcher 被正确委派
- [x] 输出为 spec 规定的结构化 markdown（TL;DR + 要点带来源 + 知识库笔记 + 参考资料）
- [x] 真实环境端到端通过

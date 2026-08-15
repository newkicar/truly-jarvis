# 14 — knowledge_keeper 知识沉淀子代理

**What to build:** 对话中把「值得长期保留的新知识」整理成带 wikilink 的 vault 笔记。主代理路由「写知识 → knowledge_keeper」。工具继承主代理后端默认 write_file（可写 /vault/）。

**Blocked by:** —（二期独立）

**Status:** resolved

## 关键决策

- **轻量子代理**：独立 SubAgent dict（name/description/system_prompt），工具继承主代理 backend 的 write_file/edit_file，不显式声明。
- **只新增、限写 Inbox 暂存区**：vault 是用户真实知识库且不可 git 回退（§10.4）。knowledge_keeper 严格只新增笔记到 `/vault/Inbox/`，**绝不修改/删除既有笔记**；wikilink 仅关联确实存在的笔记，不编造。用户在 Obsidian 审核后手动归档——风险从「LLM 自动维护链接」降到「LLM 只新增草稿」。
- **与 2-D 互补**：2-D 定时任务 → 原始研究 dump 到 Inbox；knowledge_keeper → 对话中精选知识 → 带链接笔记也进 Inbox。统一暂存区，由用户审核归档。

## 验收

- [x] `build_knowledge_keeper()` 返回合法 SubAgent dict，system_prompt 含「只新增 / 限写 /vault/Inbox/」
- [x] `build_agent` subagents 同时含 researcher + knowledge_keeper
- [x] 主代理 system_prompt 加「写知识 → knowledge_keeper」路由
- [x] 单测：test_build_agent_registers_researcher_and_knowledge_keeper、test_build_knowledge_keeper_shape；全套 27 绿
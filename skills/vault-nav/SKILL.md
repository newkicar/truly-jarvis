---
name: vault-nav
description: 在 /vault/ 知识库查找与 wikilink 导航。用户问知识库里有没有某主题、出链反链时使用 grep/read_file/vault_links。
---

# Vault WIKI 导航

## 推荐流程

1. `grep` 在 `/vault/` 搜关键词 → 得到候选路径。
2. `read_file` 读命中笔记。
3. `vault_links` 看出链 `[[wikilink]]`，沿链继续读。
4. `vault_backlinks` 查谁链接到当前笔记。
5. 语义相近但用词不同时，用 `vault_semantic_search`（researcher 子代理也带此工具）。

## 输出

- 引用时用完整虚拟路径，如 `/vault/文件夹/笔记.md`。
- 只读；写入 Inbox 见 knowledge_keeper / 用户明确要求。

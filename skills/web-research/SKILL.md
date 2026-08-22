---
name: web-research
description: 查实时信息、天气、新闻、外部事实。需联网核实时用 quick_search；vault 融合或多源对比用 task(researcher)。
---

# 联网调研

## 何时用哪个工具

1. **主代理 quick_search**：一句话能答的事实（天气、定义、最新新闻标题、公开数据）。
2. **task(researcher, …)**：需要 Obsidian /vault/ 与互联网合并、多源对比、或深度摘要时。

## 步骤

1. 先判断：本地 `/vault/` 或 `/memories/` 是否已有答案（grep / read_file）。
2. 缺外部事实 → `quick_search(精确查询词)`。
3. 仍不够 → `task(researcher, "…用户原问题…")`，把用户意图原样传入。
4. 汇总时标注来源（URL 或 /vault/ 路径）；不确定则说明。

## 不要

- 不凭训练记忆硬答实时问题。
- 不在能搜索时先反问用户「要不要我查一下」。

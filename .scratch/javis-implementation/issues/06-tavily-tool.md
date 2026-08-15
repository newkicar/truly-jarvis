# 06 — Tavily 搜索工具

**What to build:** researcher 能调用的 `tavily_search` 工具：用 Tavily 搜索指定查询 → 对值得的 URL 抓全文 → 转成 markdown → 拼成结构化文本返回给 agent。这是「互联网搜索」能力的载体，也是 spec 里 researcher 检索流程的第二步。

**Blocked by:** 05（需要 TAVILY_KEY）

**Status:** ready-for-agent

- [ ] `tavily_search(query, max_results)`：Tavily 搜索返回 URL 列表
- [ ] 对值得分析的 URL 用 httpx 抓全文，markdownify 转 markdown
- [ ] 结果拼成结构化文本（含标题/URL/内容）
- [ ] 异常处理：网络失败、空结果、抓取失败不崩溃
- [ ] 单测：mock Tavily client 与 httpx，验证拼接与异常分支（tests/test_tools.py）

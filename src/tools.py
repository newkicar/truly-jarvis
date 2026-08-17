"""自定义工具。

分层搜索（三档，LLM 按问题复杂度选工具）：
- tavily_quick_search：fast 深度 + AI 摘要（~1-2s），简单事实问题。
- tavily_search：basic 深度 + 相关片段（~2-3s），一般查询。
- tavily_deep_search：advanced 深度 + 全文 raw_content（~5-10s），深度调研。

不再用 httpx 抓全文：Tavily 的 include_raw_content 已完成页面清洗，
更稳定（不反爬、不超时），省去自研抓取层。
"""
from typing import Literal

from langchain_core.tools import tool
from tavily import TavilyClient


def _search(
    tavily_key: str,
    query: str,
    *,
    search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic",
    max_results: int = 5,
    include_answer: bool = False,
    include_raw_content: bool = False,
    topic: Literal["general", "news", "finance"] = "general",
) -> str:
    """通用 Tavily 搜索 → 结构化 markdown。"""
    try:
        client = TavilyClient(api_key=tavily_key)
        resp = client.search(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            topic=topic,
            timeout=30,
        )
    except Exception:
        return f"搜索失败: 无法连接搜索服务（query={query}），请稍后重试。"

    results = resp.get("results", [])
    if not results:
        return "未找到相关搜索结果。"

    lines = [f"# 搜索结果: {query}\n"]
    answer = resp.get("answer")
    if answer:
        lines.append(f"**AI 摘要**: {answer}\n")

    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        lines.append(f"## {i}. {title}\n- URL: {url}\n- 摘要: {content}")
        raw = r.get("raw_content")
        if raw:
            lines.append(f"- 正文节选:\n{raw[:2500]}")
        lines.append("")
    return "\n".join(lines)


def make_quick_search_tool(tavily_key: str):
    """轻量搜索：fast 深度 + AI 摘要，约 1-2 秒。"""

    @tool
    def quick_search(query: str) -> str:
        """快速搜索互联网，返回 AI 生成的答案摘要 + 相关片段（约 1-2 秒，轻量）。

        适用于：简单事实问题（天气、时间、定义、人物简介、一句话能回答的事实）。
        不适合：需要深入分析、多角度对比或全面调研的问题（用 search / deep_search）。
        """
        return _search(
            tavily_key, query, search_depth="fast", include_answer=True, max_results=3
        )

    return quick_search


def make_search_tool(tavily_key: str):
    """标准搜索：basic 深度 + 相关片段，约 2-3 秒。"""

    @tool
    def search(query: str, max_results: int = 5) -> str:
        """搜索互联网，返回相关网页的标题 + URL + 摘要片段（约 2-3 秒）。

        适用于：一般信息查询（技术问题、产品对比、新闻动态、背景信息）。
        需要全文深入阅读时用 deep_search；简单事实可先用 quick_search。
        """
        return _search(tavily_key, query, search_depth="basic", max_results=max_results)

    return search


def make_deep_search_tool(tavily_key: str):
    """深度搜索：advanced 深度 + 全文内容，约 5-10 秒。"""

    @tool
    def deep_search(query: str, max_results: int = 5) -> str:
        """深度搜索互联网，返回最相关来源的标题 + URL + 摘要 + 正文全文（约 5-10 秒，较重）。

        适用于：调研报告、行业分析、需要全面深入阅读的复杂主题、多角度对比。
        简单问题别用本工具（用 quick_search / search 更快）。
        """
        return _search(
            tavily_key,
            query,
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=True,
        )

    return deep_search


def make_tavily_tool(tavily_key: str):
    """兼容旧接口：返回标准 search 工具。"""
    return make_search_tool(tavily_key)
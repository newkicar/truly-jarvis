"""自定义工具。

tavily_search（Tavily 找 URL → httpx 抓全文 → markdownify 转 md）。
"""
import httpx
import markdownify
from langchain_core.tools import tool
from tavily import TavilyClient


def _fetch_url(url: str) -> str:
    """抓取网页全文并转为 markdown。"""
    resp = httpx.get(url, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return markdownify.markdownify(resp.text, strip=["script", "style"])


def tavily_search(query: str, max_results: int = 5, tavily_key: str = "") -> str:
    """搜索互联网，返回带来源的结构化 markdown。

    用于获取时效信息、行业动态、外部事实调研。
    """
    try:
        client = TavilyClient(api_key=tavily_key)
        results = client.search(query=query, max_results=max_results).get("results", [])
    except Exception:
        return f"搜索失败: 无法连接搜索服务（query={query}），请稍后重试。"

    if not results:
        return "未找到相关搜索结果。"

    lines = [f"# 搜索结果: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        summary = r.get("content", "")
        lines.append(f"## {i}. {title}\n- URL: {url}\n- 摘要: {summary}")
        try:
            body = _fetch_url(url)
            lines.append(f"- 正文节选:\n{body[:2000]}")
        except (httpx.HTTPError, httpx.RequestError):
            lines.append("- 正文抓取失败（仅提供摘要）")
        lines.append("")
    return "\n".join(lines)


def make_tavily_tool(tavily_key: str):
    """以给定 key 构造绑定后的 langchain tool。"""

    @tool
    def search(query: str, max_results: int = 5) -> str:
        """搜索互联网，返回带来源的结构化 markdown（时效信息/行业动态/外部调研）。"""
        return tavily_search(query, max_results, tavily_key)

    return search
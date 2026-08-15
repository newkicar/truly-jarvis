"""工具层测试。

Seam: src.tools.tavily_search（输入 query → 输出结构化 markdown 文本）。
mock TavilyClient 与 httpx，验证拼接与异常分支，不触网。
"""
import httpx
import pytest


def test_tavily_search_returns_structured_markdown(tmp_path, monkeypatch):
    from src import tools

    search_results = {
        "results": [
            {"title": "标题A", "url": "https://example.com/a", "content": "摘要A"},
            {"title": "标题B", "url": "https://example.com/b", "content": "摘要B"},
        ]
    }

    class FakeTavily:
        def search(self, query, max_results):
            assert query == "大模型 最新动态"
            assert max_results == 5
            return search_results

    monkeypatch.setattr(tools, "TavilyClient", lambda api_key: FakeTavily())

    def fake_fetch(url):
        return f"<html><body><h1>{url}</h1><p>正文内容</p></body></html>"

    monkeypatch.setattr(tools, "_fetch_url", fake_fetch)

    out = tools.tavily_search(query="大模型 最新动态", max_results=5, tavily_key="tvly-test")
    assert "标题A" in out
    assert "https://example.com/a" in out
    assert "正文内容" in out


def test_tavily_search_handles_empty_results(monkeypatch):
    from src import tools

    monkeypatch.setattr(tools, "TavilyClient", lambda api_key: type("F", (), {"search": lambda self, query, max_results: {"results": []}})())

    out = tools.tavily_search(query="不存在的东西", max_results=3, tavily_key="tvly-test")
    assert "未找到" in out or "没有" in out or "无" in out


def test_tavily_search_handles_fetch_failure(tmp_path, monkeypatch):
    from src import tools

    search_results = {"results": [{"title": "A", "url": "https://example.com/a", "content": "摘要"}]}
    monkeypatch.setattr(tools, "TavilyClient", lambda api_key: type("F", (), {"search": lambda self, query, max_results: search_results})())
    monkeypatch.setattr(tools, "_fetch_url", lambda url: (_ for _ in ()).throw(httpx.HTTPError("boom")))

    out = tools.tavily_search(query="x", max_results=1, tavily_key="tvly-test")
    assert "抓取失败" in out or "https://example.com/a" in out


def test_tavily_search_handles_search_failure(monkeypatch):
    from src import tools

    class BrokenTavily:
        def search(self, query, max_results):
            raise RuntimeError("network down")

    monkeypatch.setattr(tools, "TavilyClient", lambda api_key: BrokenTavily())

    out = tools.tavily_search(query="x", max_results=1, tavily_key="tvly-test")
    assert "搜索失败" in out


def test_tavily_search_is_a_tool():
    from src import tools

    assert callable(tools.tavily_search)
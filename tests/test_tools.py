"""工具层测试（分层搜索）。

Seam: src.tools._search（输入 → 结构化 markdown）。mock TavilyClient，
验证 quick/search/deep 三档深度参数、AI 摘要、全文 raw_content、异常分支。
"""
import pytest


class _FakeTavily:
    """记录调用参数并返回固定结果。"""

    def __init__(self, results=None, answer=None, raw_content=None):
        self._results = results or [
            {"title": "标题A", "url": "https://example.com/a", "content": "摘要A"},
            {"title": "标题B", "url": "https://example.com/b", "content": "摘要B"},
        ]
        self._answer = answer
        self._raw = raw_content
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        out = {"results": self._results}
        if self._answer:
            out["answer"] = self._answer
        if self._raw:
            for i, r in enumerate(self._results):
                self._results[i]["raw_content"] = self._raw
        return out


@pytest.fixture
def fake_tavily(monkeypatch):
    from src import tools

    fake = _FakeTavily()

    def _client(api_key):
        return fake

    monkeypatch.setattr(tools, "TavilyClient", _client)
    return fake


def test_quick_search_uses_fast_depth_and_answer(fake_tavily):
    from src.tools import _search

    fake_tavily._answer = "今天晴，25 度。"
    out = _search("tvly-x", "今天天气", search_depth="fast", include_answer=True, max_results=3)
    assert fake_tavily.calls[0]["search_depth"] == "fast"
    assert fake_tavily.calls[0]["include_answer"] is True
    assert "AI 摘要" in out and "今天晴" in out


def test_standard_search_uses_basic_depth(fake_tavily):
    from src.tools import _search

    out = _search("tvly-x", "大模型 最新动态")
    assert fake_tavily.calls[0]["search_depth"] == "basic"
    assert fake_tavily.calls[0]["include_raw_content"] is False
    assert "标题A" in out and "https://example.com/a" in out


def test_deep_search_uses_advanced_and_raw_content(fake_tavily):
    from src.tools import _search

    fake_tavily._raw = "这是一篇长文正文……" * 10
    out = _search("tvly-x", "行业调研", search_depth="advanced", include_raw_content=True)
    assert fake_tavily.calls[0]["search_depth"] == "advanced"
    assert fake_tavily.calls[0]["include_raw_content"] is True
    assert "正文节选" in out


def test_search_handles_empty_results(fake_tavily):
    from src.tools import _search

    fake_tavily._results = []
    out = _search("tvly-x", "不存在")
    assert "未找到" in out


def test_search_handles_failure(monkeypatch):
    from src import tools

    class Broken:
        def search(self, query, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(tools, "TavilyClient", lambda api_key: Broken())
    out = tools._search("tvly-x", "x")
    assert "搜索失败" in out


def test_make_tools_are_callable():
    from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool

    for maker in (make_quick_search_tool, make_search_tool, make_deep_search_tool):
        t = maker("tvly-x")
        assert hasattr(t, "invoke")
        assert t.name in ("quick_search", "search", "deep_search")
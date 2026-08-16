"""增量 RAG 语义增强测试（src.rag）。

Seam: RagIndex / make_semantic_search_tool。用 fake embedding 替换 Ollama 调用
（确定性，不依赖本地服务），验证增量 hash、增删索引、语义检索、工具输出。
"""
import pytest

from src.rag import RagIndex, _content_hash, _chunk_note, make_semantic_search_tool


def _mk_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AI.md").write_text("关于深度学习与大模型的笔记", encoding="utf-8")
    (vault / "金融.md").write_text("股票、基金、投资理财的讨论", encoding="utf-8")
    (vault / "Inbox").mkdir()
    (vault / "Inbox" / "待归档.md").write_text("临时笔记内容", encoding="utf-8")
    return vault


class _FakeEmbed:
    """确定性 fake embedding：词袋式（字符 bigram 哈希分布），使字符重叠文本向量相近。

    近似真实语义：查询与笔记共享越多 bigram，余弦越近；否则近正交。
    """

    def __init__(self, dim=512):
        self.dim = dim

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            bigrams = [t[i : i + 2] for i in range(max(0, len(t) - 1))]
            for bg in bigrams:
                idx = abs(hash(bg)) % self.dim
                vec[idx] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


@pytest.fixture
def fake_embed(monkeypatch):
    fe = _FakeEmbed()

    def _embed(texts, base_url=""):
        return fe.embed(texts)

    monkeypatch.setattr("src.rag._embed_texts", _embed)
    return fe


def test_chunk_note_splits_long_text():
    text = "长" * 2000
    chunks = _chunk_note(text)
    assert len(chunks) > 1
    assert all(len(c) <= 710 for c in chunks)


def test_hash_is_deterministic():
    assert _content_hash("abc") == _content_hash("abc")
    assert _content_hash("abc") != _content_hash("abd")


def test_refresh_indexes_all_md_files(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    stats = index.refresh()
    assert stats["added"] == 3  # AI / 金融 / Inbox 待归档
    assert index.collection.count() >= 3


def test_refresh_is_incremental(tmp_path, fake_embed):
    """未变更文件不重算（unchanged 计数），变更文件才重建。"""
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    stats1 = index.refresh()
    assert stats1["added"] == 3

    stats2 = index.refresh()
    assert stats2["added"] == 0 and stats2["unchanged"] == 3

    # 变更一个文件 → 只重建它
    (vault / "金融.md").write_text("改了内容：关于金融的最新观点", encoding="utf-8")
    stats3 = index.refresh()
    assert stats3["updated"] == 1 and stats3["unchanged"] == 2


def test_refresh_removes_deleted_file(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    index.refresh()
    (vault / "金融.md").unlink()
    stats = index.refresh()
    assert stats["removed"] == 1
    assert index.collection.count() == 2


def test_search_finds_semantically_close_note(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    index.refresh()
    hits = index.search("深度学习与人工智能的关系", k=2)
    assert hits, "应返回语义相近结果"
    assert hits[0]["path"].endswith("AI.md")
    assert hits[0]["snippet"]


def test_search_returns_empty_when_no_index(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    assert index.search("任意查询") == []


def test_search_empty_query_returns_empty(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    index = RagIndex(tmp_path / "rag", vault)
    index.refresh()
    assert index.search("   ") == []


def test_semantic_search_tool_output(tmp_path, fake_embed):
    vault = _mk_vault(tmp_path)
    tool = make_semantic_search_tool(vault, tmp_path / "rag")
    out = tool.invoke({"query": "深度学习与人工智能的关系", "k": 2})
    assert "语义相近笔记" in out
    assert "/vault/AI.md" in out
    assert "深度学习" in out
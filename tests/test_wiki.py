"""WIKI 导航工具测试（src.wiki）。

验证 wikilink 解析、标题/别名/大小写匹配、出链/反链工具。零外部依赖。
"""
import pytest

from src.wiki import (
    extract_wikilinks,
    make_wiki_tools,
    resolve_link,
    _vault_links,
    _vault_backlinks,
)


def _mk_vault(tmp_path):
    """构造临时 vault：笔记 + 目录层级 + 别名。"""
    vault = tmp_path / "vault"
    (vault / "AI").mkdir(parents=True)
    (vault / "AI" / "大模型.md").write_text(
        "# 大模型\n\n参考 [[智能体]] 和 [[Agent 综述|Agent Overview]]。\n"
        "见 [[AI/深度学习]]。\n",
        encoding="utf-8",
    )
    (vault / "AI" / "深度学习.md").write_text("# 深度学习\n\n- [[大模型]] 依赖它\n", encoding="utf-8")
    (vault / "智能体.md").write_text(
        "---\ntitle: 智能体\n---\n# 智能体\n\n- [[大模型]]\n",
        encoding="utf-8",
    )
    (vault / "Agent 综述.md").write_text(
        "---\naliases:\n  - Agent Overview\n---\n# Agent 综述\n\n反链测试目标。\n",
        encoding="utf-8",
    )
    return vault


def test_extract_wikilinks_basic():
    links = extract_wikilinks("看 [[笔记A]] 和 [[笔记B|显示B]] 与 [[笔记C#小节]]")
    targets = [l.target for l in links]
    assert targets == ["笔记A", "笔记B", "笔记C"]
    assert links[1].display == "显示B"
    assert links[2].section == "小节"


def test_extract_wikilinks_ignores_internal_anchor():
    links = extract_wikilinks("见 [[#内部]] 和 [[目标]]")
    assert [l.target for l in links] == ["目标"]


def test_resolve_link_by_title_case_insensitive(tmp_path):
    vault = _mk_vault(tmp_path)
    p = resolve_link(vault, "大模型")
    assert p is not None and p.name == "大模型.md"
    p2 = resolve_link(vault, "大模型.md")
    assert p2 is not None and p2.name == "大模型.md"


def test_resolve_link_by_path(tmp_path):
    vault = _mk_vault(tmp_path)
    p = resolve_link(vault, "AI/深度学习")
    assert p is not None and p.name == "深度学习.md"


def test_resolve_link_by_alias(tmp_path):
    vault = _mk_vault(tmp_path)
    p = resolve_link(vault, "Agent Overview")
    assert p is not None and p.name == "Agent 综述.md"


def test_resolve_link_missing_returns_none(tmp_path):
    vault = _mk_vault(tmp_path)
    assert resolve_link(vault, "不存在的笔记") is None


def test_vault_links_lists_outgoing(tmp_path):
    vault = _mk_vault(tmp_path)
    out = _vault_links(vault, "/vault/AI/大模型.md")
    assert "智能体" in out
    assert "Agent 综述" in out
    assert "深度学习" in out
    assert "未找到" not in out  # 全部可解析


def test_vault_links_dangling_detected(tmp_path):
    vault = _mk_vault(tmp_path)
    (vault / "AI" / "大模型.md").write_text(
        "# 大模型\n\n看 [[不存在笔记]]\n", encoding="utf-8"
    )
    out = _vault_links(vault, "AI/大模型.md")
    assert "不存在笔记" in out and "未找到" in out


def test_vault_backlinks_finds_referencing_notes(tmp_path):
    vault = _mk_vault(tmp_path)
    out = _vault_backlinks(vault, "AI/大模型.md")
    assert "智能体.md" in out
    assert "深度学习.md" in out


def test_vault_backlinks_resolves_alias(tmp_path):
    vault = _mk_vault(tmp_path)
    out = _vault_backlinks(vault, "/vault/Agent 综述.md")
    assert "大模型.md" in out  # 通过 [[Agent 综述|Agent Overview]] 反链命中


def test_make_wiki_tools_returns_two_tools(tmp_path):
    vault = _mk_vault(tmp_path)
    tools = make_wiki_tools(vault)
    names = {t.name for t in tools}
    assert names == {"vault_links", "vault_backlinks"}
    # 工具可用 .invoke 调用
    for t in tools:
        assert hasattr(t, "invoke")
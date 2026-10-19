"""skill_discovery 单元测试。"""
from pathlib import Path

from src.config import Config
from src.skill_discovery import (
    SkillMeta,
    build_skill_use_message,
    discover_skill_catalog,
    fuzzy_filter_skills,
    manual_only_skill_names,
    summarize_skill_catalog,
)


def _cfg(tmp_path: Path) -> Config:
    skills_dir = tmp_path / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: demo\n"
        "description: Do demo things when user asks demo.\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    return Config(
        project_root=tmp_path,
        base_url="http://x",
        api_key="k",
        model_id="m",
        tavily_key="t",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(tmp_path / "skills",),
        mcps={},
        permissions={},
        hooks={},
        agents={},
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="embed",
        execution_max_steps=200,
        tui={},
    )


def test_discover_skill_catalog_finds_skill_md(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = _cfg(tmp_path)
    catalog = discover_skill_catalog(cfg)
    assert len(catalog) >= 1
    demo = next(s for s in catalog if s.name == "demo")
    assert "demo things" in demo.description
    assert "SKILL.md" in demo.virtual_path


def test_summarize_skill_catalog_empty():
    text = summarize_skill_catalog([])
    assert "skills: 0" in text


def _write_manual_skill(tmp_path: Path) -> None:
    """#09: 写一个 manual-only skill（disable-model-invocation: true）。"""
    sk = tmp_path / "skills" / "manual-skill"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\n"
        "name: manual-skill\n"
        "description: 手动专用 skill。\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        "# 手动 skill\n"
        "步骤一：做点事\n",
        encoding="utf-8",
    )


def test_manual_only_detection_and_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    _write_manual_skill(tmp_path)
    cfg = _cfg(tmp_path)
    catalog = discover_skill_catalog(cfg)
    demo = next(s for s in catalog if s.name == "demo")
    manual = next(s for s in catalog if s.name == "manual-skill")
    assert demo.manual_only is False
    assert demo.fs_path is not None
    assert manual.manual_only is True
    assert manual.fs_path.name == "SKILL.md"
    assert manual_only_skill_names(cfg) == {"manual-skill"}


def test_summarize_tags_manual_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    _write_manual_skill(tmp_path)
    cfg = _cfg(tmp_path)
    text = summarize_skill_catalog(discover_skill_catalog(cfg))
    assert "- manual-skill [manual]:" in text
    assert "- demo [manual]" not in text


def test_build_skill_use_message_expands_body_and_task(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    _write_manual_skill(tmp_path)
    cfg = _cfg(tmp_path)
    msg = build_skill_use_message(cfg, "manual-skill", "请执行")
    assert msg is not None
    assert msg.startswith("[skill:manual-skill]")
    assert "步骤一：做点事" in msg
    assert "任务：请执行" in msg
    assert "disable-model-invocation" not in msg  # frontmatter 已剥


def test_build_skill_use_message_case_insensitive_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    _write_manual_skill(tmp_path)
    cfg = _cfg(tmp_path)
    assert build_skill_use_message(cfg, "MANUAL-SKILL") is not None
    assert build_skill_use_message(cfg, "no-such-skill") is None


def _skill(name: str, desc: str = "", manual: bool = False) -> SkillMeta:
    """tui-ux9 fixture: 直构 SkillMeta，无文件系统依赖。"""
    return SkillMeta(
        name=name,
        description=desc,
        virtual_path="/skills/x/SKILL.md",
        layer="project",
        manual_only=manual,
    )


def test_fuzzy_bkmtg_hits_book_meeting_room():
    catalog = [_skill("alpha"), _skill("book-meeting-room"), _skill("zeta")]
    assert [s.name for s in fuzzy_filter_skills(catalog, "bkmtg")] == [
        "book-meeting-room",
    ]


def test_fuzzy_bookmtg_prefers_shorter_name():
    catalog = [_skill("book-meeting-room"), _skill("book-meeting")]
    assert [s.name for s in fuzzy_filter_skills(catalog, "bookmtg")] == [
        "book-meeting", "book-meeting-room",
    ]


def test_fuzzy_case_insensitive():
    catalog = [_skill("Book-Meeting")]
    assert [s.name for s in fuzzy_filter_skills(catalog, "BOOKMTG")] == [
        "Book-Meeting",
    ]


def test_fuzzy_four_tiers_ordered():
    catalog = [_skill("m-a-l-p-h-a"), _skill("my-alpha"), _skill("alphabet"), _skill("alpha")]
    assert [s.name for s in fuzzy_filter_skills(catalog, "alpha")] == [
        "alpha", "alphabet", "my-alpha", "m-a-l-p-h-a",
    ]


def test_fuzzy_subsequence_blocks_then_length():
    catalog = [_skill("axbxc"), _skill("axbc"), _skill("axxb"), _skill("axb")]
    assert [s.name for s in fuzzy_filter_skills(catalog, "abc")] == ["axbc", "axbxc"]
    assert [s.name for s in fuzzy_filter_skills(catalog, "ab")] == [
        "axb", "axbc", "axxb", "axbxc",
    ]


def test_fuzzy_empty_query_first_20_by_name():
    catalog = [_skill(f"s{i:02d}") for i in range(25)]
    assert [s.name for s in fuzzy_filter_skills(catalog, "")] == [
        f"s{i:02d}" for i in range(20)
    ]


def test_fuzzy_no_match_empty():
    catalog = [_skill("alpha"), _skill("beta")]
    assert fuzzy_filter_skills(catalog, "zz") == []


def test_fuzzy_limit_applied():
    catalog = [_skill(f"s{i:02d}") for i in range(25)]
    assert len(fuzzy_filter_skills(catalog, "", limit=5)) == 5

"""skill_discovery 单元测试。"""
from pathlib import Path

from src.config import Config
from src.skill_discovery import (
    build_skill_use_message,
    discover_skill_catalog,
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

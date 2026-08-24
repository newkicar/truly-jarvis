"""skill_discovery 单元测试。"""
from pathlib import Path

from src.config import Config
from src.skill_discovery import discover_skill_catalog, summarize_skill_catalog


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

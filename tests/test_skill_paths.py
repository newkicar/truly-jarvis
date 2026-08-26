"""skill_paths 与 session 日期注入测试。"""
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from tests.conftest import make_fake_config
from src.agent import build_main_prompt, session_date_line
from src.project_paths import ensure_user_home, user_home
from src.skill_paths import (
    BUILTIN_SKILLS_VPATH,
    USER_SKILLS_VPATH,
    discover_skill_layers,
    skill_backend_routes,
    skill_virtual_sources,
)


def test_user_home_default_uses_dot_javis(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_HOME", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert user_home() == (fake_home / ".jarvis").resolve()


def test_user_home_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "my-javis"
    monkeypatch.setenv("JARVIS_HOME", str(custom))
    assert user_home() == custom.resolve()


def test_ensure_user_home_creates_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    home = ensure_user_home()
    assert home.is_dir()
    assert (home / "skills").is_dir()


def test_discover_skill_layers_order(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "user-javis"))
    project = tmp_path / "proj"
    project_skills = project / "skills"
    project_skills.mkdir(parents=True)
    (project_skills / "proj-skill").mkdir()
    (project_skills / "proj-skill" / "SKILL.md").write_text("---\nname: p\ndescription: d\n---\n", encoding="utf-8")

    user_skills = ensure_user_home() / "skills"
    (user_skills / "user-skill").mkdir()
    (user_skills / "user-skill" / "SKILL.md").write_text("---\nname: u\ndescription: d\n---\n", encoding="utf-8")

    cfg = replace(make_fake_config(project), skills=(project_skills,))
    layers = discover_skill_layers(cfg)
    vpaths = [layer.virtual_path for layer in layers]
    assert BUILTIN_SKILLS_VPATH in vpaths
    assert USER_SKILLS_VPATH in vpaths
    assert "/workspace/skills/" in vpaths
    assert vpaths.index(BUILTIN_SKILLS_VPATH) < vpaths.index(USER_SKILLS_VPATH) < vpaths.index("/workspace/skills/")


def test_skill_backend_routes_excludes_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    ensure_user_home()
    cfg = make_fake_config(tmp_path / "proj")
    routes = skill_backend_routes(cfg)
    assert USER_SKILLS_VPATH in routes
    assert all(not k.startswith("/workspace/") for k in routes)


def test_skill_virtual_sources_includes_user_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    ensure_user_home()
    cfg = make_fake_config(tmp_path)
    sources = skill_virtual_sources(cfg)
    assert USER_SKILLS_VPATH in sources


def test_session_date_line():
    line = session_date_line(now=datetime(2026, 8, 20, 15, 30, 0))
    assert line.startswith("今天是 2026-08-20 星期四。")
    assert "可直接用本行作答" in line


def test_build_main_prompt_includes_date_not_time():
    prompt = build_main_prompt(now=datetime(2026, 8, 20, 15, 30, 0))
    assert "今天是 2026-08-20 星期四。" in prompt
    assert "可直接用本行作答" in prompt
    assert "15:30" not in prompt
    assert "get_system_context" not in prompt
    assert "execute" in prompt
    assert "quick_search" in prompt
    assert "环境与可核实事实" in prompt
    assert "停止规则" not in prompt


def test_backend_lists_user_skill(tmp_path, monkeypatch):
    from deepagents.middleware.skills import _list_skills

    from src.agent import _make_backend

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    user_skills = ensure_user_home() / "skills"
    (user_skills / "demo-skill").mkdir(parents=True)
    (user_skills / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )
    cfg = make_fake_config(tmp_path / "proj")
    backend = _make_backend(cfg)
    names = [s["name"] for s in _list_skills(backend, USER_SKILLS_VPATH)]
    assert "demo-skill" in names

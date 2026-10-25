"""skill_paths 与 session 日期注入测试。"""
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from tests.conftest import make_fake_config
from src.agent import build_main_prompt, session_date_line
from src.project_paths import ensure_user_home, user_home
from src.skill_paths import (
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
    assert USER_SKILLS_VPATH in vpaths
    assert "/workspace/skills/" in vpaths
    assert vpaths.index(USER_SKILLS_VPATH) < vpaths.index("/workspace/skills/")


def test_skill_backend_routes_includes_project_layer(tmp_path, monkeypatch):
    """#03 fix: 项目 skill 层（/workspace/ 前缀）也必须单独挂虚拟后端，不再排除。"""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    ensure_user_home()
    project = tmp_path / "proj"
    project_skills = project / "skills"
    project_skills.mkdir(parents=True)
    cfg = replace(make_fake_config(project), skills=(project_skills,))
    routes = skill_backend_routes(cfg)
    assert USER_SKILLS_VPATH in routes
    assert "/workspace/skills/" in routes
    assert routes["/workspace/skills/"] == project_skills


def test_backend_lists_project_skill_clean_paths(tmp_path, monkeypatch):
    """#03 regression: /workspace/skills/ 经 _make_backend 的 CompositeBackend 返回干净路径。

    修前：unrestricted 的 /workspace/ 默认后端 virtual_mode=False 返回真实绝对路径，
    CompositeBackend 重新前缀化（route_prefix 直接拼 entry_path）产出坏路径，使
    deepagents skill 发现 download 报 OSError 并中断整轮。
    """
    from deepagents.middleware.skills import _list_skills

    from src.agent import _make_backend

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    ensure_user_home()
    project = tmp_path / "proj"
    project_skills = project / "skills"
    (project_skills / "proj-skill").mkdir(parents=True)
    (project_skills / "proj-skill" / "SKILL.md").write_text(
        "---\nname: proj-skill\ndescription: d\n---\n", encoding="utf-8"
    )
    cfg = replace(make_fake_config(project), skills=(project_skills,))
    backend = _make_backend(cfg)
    ls = backend.ls("/workspace/skills/")
    assert ls.error is None
    for entry in ls.entries or []:
        assert entry["path"].startswith("/workspace/skills/"), entry["path"]
    names = [s["name"] for s in _list_skills(backend, "/workspace/skills/")]
    assert "proj-skill" in names


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


def test_seed_builtin_skills_never_overwrites_user_edited_files(monkeypatch):
    """回归（2026-10-25 覆盖 bug）：seed 必须是非破坏性合并——

    用户已编辑的 ~/.jarvis/skills/<同名>/SKILL.md 不得被内置版覆盖；
    内置版有而用户没有的新文件应补入。
    """
    import os
    import shutil
    import tempfile
    import uuid

    import src.skill_paths as sp

    base = Path(tempfile.gettempdir()) / ("jarvis_seedtest_" + uuid.uuid4().hex[:12])
    try:
        install_dir = base / "install"
        user_dir = base / "user"
        builtin_skill = install_dir / "skills" / "demo-skill"
        ref_dir = builtin_skill / "references"
        os.makedirs(ref_dir)
        (builtin_skill / "SKILL.md").write_text("BUILTIN-v1", encoding="utf-8")
        (ref_dir / "flow.md").write_text("BUILTIN-ref", encoding="utf-8")

        user_skill = user_dir / "skills" / "demo-skill"
        os.makedirs(user_skill)
        (user_skill / "SKILL.md").write_text("USER-EDITED", encoding="utf-8")

        monkeypatch.setenv("JARVIS_HOME", str(user_dir))
        monkeypatch.setattr(sp, "install_root", lambda: install_dir)
        sp.seed_builtin_skills()

        # 用户编辑的内容必须保留（当前 copytree 行为 = 红灯）
        assert (user_skill / "SKILL.md").read_text(encoding="utf-8") == "USER-EDITED"
        # 内置新增文件应补入
        assert (user_skill / "references" / "flow.md").read_text(encoding="utf-8") == "BUILTIN-ref"
    finally:
        shutil.rmtree(base, ignore_errors=True)

"""Issue #12: 共享 agent skill 根 ~/.agents/skills（最低优先级第三层）。

设计（ADR-0018）：
- 三层 skill 发现：shared（~/.agents/skills，AGENTS_HOME 可覆盖）
  → user（~/.jarvis/skills）→ project（.jarvis/skills 等）；
  同名 skill 后层覆盖前层（既有 by_name 语义，零额外代码）。
- share_agent_skills 开关（jarvis.json 顶层键，默认 True，项目覆盖全局）；False 时不挂 shared 层。
- 共享层只读挂载：仅 is_dir() 时挂载、绝不 mkdir；ensure_user_home 不触碰 .agents 目录。

测试纪律（repo AGENTS.md）：勿用 tmp_path / tempfile.mkdtemp（基 temp 目录中毒，WinError 5）；
自建目录；隔离 JARVIS_HOME/AGENTS_HOME 不碰真实用户主目录。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from src.config import Config

_SEQ = 0


def _fresh_dir() -> Path:
    """自建临时目录（pid + ms + seq 保证唯一）。"""
    global _SEQ
    _SEQ += 1
    d = Path(tempfile.gettempdir()) / f"jx_shared_skills_{os.getpid()}_{int(time.time() * 1000)}_{_SEQ}"
    d.mkdir(parents=True)
    return d


def _isolate_envs(base: Path, agents_root: Path | None = None) -> dict:
    """JARVIS_HOME/AGENTS_HOME 隔离到 base 下；返回旧值（None=原本未设）。"""
    jh = base / "jh"
    jh.mkdir()
    old: dict = {}
    pairs = (("JARVIS_HOME", str(jh)), ("AGENTS_HOME", str(agents_root or base / "ah")))
    for name, val in pairs:
        old[name] = os.environ.get(name)
        os.environ[name] = val
    return old


def _restore_envs(old: dict) -> None:
    for name, val in old.items():
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val


def _write_min_env(base: Path) -> Path:
    p = base / ".env"
    p.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    return p


def _write_json(base: Path, data: dict, name: str = "jarvis.json") -> Path:
    p = base / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _write_skill(root: Path, name: str, description: str = "d") -> Path:
    """写 <root>/<name>/SKILL.md（frontmatter name/description）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\nbody\n", encoding="utf-8")
    return p


def _fake_config(project_root: Path, skills: tuple[Path, ...] = ()) -> Config:
    root = project_root.resolve()
    return Config(
        project_root=root,
        base_url="https://fake/v1",
        api_key="sk",
        model_id="m",
        tavily_key="tvly",
        vault_path=None,
        memory_dir=root / "memory",
        checkpoint_db=root / "cp.sqlite",
        schedules_dir=root / "schedules",
        skills=skills,
        mcps={},
        permissions={},
        hooks={},
        agents={},
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="quentinz/bge-small-zh-v1.5",
        execution_max_steps=200,
        tui={"copy_on_select": True},
    )


def test_agents_home_default_under_home(monkeypatch):
    from src.project_paths import ENV_AGENTS_HOME, agents_home

    base = _fresh_dir()
    monkeypatch.delenv(ENV_AGENTS_HOME, raising=False)
    fake_home = base / "fh"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    try:
        assert agents_home() == fake_home / ".agents"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_agents_home_env_override():
    from src.project_paths import agents_home

    base = _fresh_dir()
    old = _isolate_envs(base, agents_root=base / "agents_root")
    try:
        target = Path(os.environ["AGENTS_HOME"]).resolve()
        assert agents_home() == target
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_ensure_user_home_does_not_create_agents_dir():
    from src.project_paths import ensure_user_home

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        home = ensure_user_home()
        assert home == Path(os.environ["JARVIS_HOME"]).resolve()
        assert (base / "jh" / "skills").is_dir()
        assert not (base / "ah").exists()
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_discover_skill_layers_shared_lowest_order():
    from src.project_paths import agents_home
    from src.skill_paths import (
        SHARED_SKILLS_VPATH,
        USER_SKILLS_VPATH,
        discover_skill_layers,
    )

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        shared = agents_home() / "skills"
        _write_skill(shared, "shared-skill")
        user_skills = Path(os.environ["JARVIS_HOME"]) / "skills"
        _write_skill(user_skills, "user-skill")
        proj_root = base / "proj"
        proj_skills = proj_root / ".jarvis" / "skills"
        _write_skill(proj_skills, "proj-skill")
        cfg = _fake_config(proj_root, skills=(proj_skills,))
        vpaths = [layer.virtual_path for layer in discover_skill_layers(cfg)]
        assert vpaths.index(SHARED_SKILLS_VPATH) < vpaths.index(USER_SKILLS_VPATH)
        assert vpaths.index(USER_SKILLS_VPATH) < vpaths.index("/workspace/.jarvis/skills/")
        shared_layer = next(layer for layer in discover_skill_layers(cfg) if layer.virtual_path == SHARED_SKILLS_VPATH)
        assert shared_layer.fs_path == shared.resolve()
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_discover_skill_layers_shared_missing_skipped_no_mkdir():
    from src.project_paths import ENV_AGENTS_HOME
    from src.skill_paths import SHARED_SKILLS_VPATH, discover_skill_layers

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        agents = Path(os.environ[ENV_AGENTS_HOME])
        agents.mkdir()
        cfg = _fake_config(base / "proj")
        vpaths = [layer.virtual_path for layer in discover_skill_layers(cfg)]
        assert SHARED_SKILLS_VPATH not in vpaths
        assert not (agents / "skills").exists()
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_discover_skill_layers_share_agent_skills_false():
    from src.project_paths import agents_home
    from src.skill_paths import (
        SHARED_SKILLS_VPATH,
        USER_SKILLS_VPATH,
        discover_skill_layers,
    )

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        _write_skill(agents_home() / "skills", "shared-skill")
        cfg = _fake_config(base / "proj")
        vpaths = [layer.virtual_path for layer in discover_skill_layers(cfg)]
        assert SHARED_SKILLS_VPATH in vpaths
        cfg_off = replace(cfg, share_agent_skills=False)
        vpaths_off = [layer.virtual_path for layer in discover_skill_layers(cfg_off)]
        assert SHARED_SKILLS_VPATH not in vpaths_off
        assert USER_SKILLS_VPATH in vpaths_off
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_skill_backend_routes_and_sources_include_shared():
    from src.project_paths import agents_home
    from src.skill_paths import (
        SHARED_SKILLS_VPATH,
        skill_backend_routes,
        skill_virtual_sources,
    )

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        shared = agents_home() / "skills"
        _write_skill(shared, "codex-shared")
        cfg = _fake_config(base / "proj")
        assert skill_backend_routes(cfg)[SHARED_SKILLS_VPATH] == shared.resolve()
        assert SHARED_SKILLS_VPATH in skill_virtual_sources(cfg)
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_catalog_project_overrides_user_overrides_shared():
    from src.project_paths import agents_home
    from src.skill_discovery import discover_skill_catalog

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        shared = agents_home() / "skills"
        _write_skill(shared, "dup", "shared-dup")
        _write_skill(shared, "shared-only")
        user_skills = Path(os.environ["JARVIS_HOME"]) / "skills"
        _write_skill(user_skills, "dup", "user-dup")
        proj_root = base / "proj"
        proj_skills = proj_root / ".jarvis" / "skills"
        _write_skill(proj_skills, "dup", "proj-dup")
        cfg = _fake_config(proj_root, skills=(proj_skills,))
        by = {m.name: m for m in discover_skill_catalog(cfg)}
        assert by["dup"].description == "proj-dup"
        assert by["dup"].layer == "/workspace/.jarvis/skills/"
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_catalog_user_overrides_shared_and_shared_only_visible():
    from src.project_paths import agents_home
    from src.skill_discovery import discover_skill_catalog
    from src.skill_paths import SHARED_SKILLS_VPATH, USER_SKILLS_VPATH

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        shared = agents_home() / "skills"
        _write_skill(shared, "dup", "shared-dup")
        _write_skill(shared, "shared-only")
        user_skills = Path(os.environ["JARVIS_HOME"]) / "skills"
        _write_skill(user_skills, "dup", "user-dup")
        cfg = _fake_config(base / "proj")
        by = {m.name: m for m in discover_skill_catalog(cfg)}
        assert by["dup"].description == "user-dup"
        assert by["dup"].layer == USER_SKILLS_VPATH
        assert by["shared-only"].layer == SHARED_SKILLS_VPATH
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_backend_lists_shared_skill():
    from deepagents.middleware.skills import _list_skills

    from src.agent import _make_backend
    from src.project_paths import agents_home
    from src.skill_paths import SHARED_SKILLS_VPATH

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        _write_skill(agents_home() / "skills", "codex-shared")
        proj_root = base / "proj"
        proj_root.mkdir()
        cfg = _fake_config(proj_root)
        backend = _make_backend(cfg)
        names = [s["name"] for s in _list_skills(backend, SHARED_SKILLS_VPATH)]
        assert "codex-shared" in names
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_config_share_agent_skills_defaults_true():
    from src.config import GLOBAL_DEFAULTS, load_config

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        assert GLOBAL_DEFAULTS["share_agent_skills"] is True
        cfg = load_config(env_file=_write_min_env(base), json_file=_write_json(base, {}))
        assert cfg.share_agent_skills is True
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_config_share_agent_skills_global_false():
    from src.config import load_config

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        jh = Path(os.environ["JARVIS_HOME"])
        (jh / "jarvis.json").write_text(json.dumps({"share_agent_skills": False}), encoding="utf-8")
        cfg = load_config(env_file=_write_min_env(base), json_file=_write_json(base, {}))
        assert cfg.share_agent_skills is False
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_config_share_agent_skills_project_overrides_global():
    from src.config import load_config

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        jh = Path(os.environ["JARVIS_HOME"])
        (jh / "jarvis.json").write_text(json.dumps({"share_agent_skills": False}), encoding="utf-8")
        cfg = load_config(
            env_file=_write_min_env(base),
            json_file=_write_json(base, {"share_agent_skills": True}),
        )
        assert cfg.share_agent_skills is True
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)


def test_config_share_agent_skills_non_bool_falls_back_true():
    from src.config import load_config

    base = _fresh_dir()
    old = _isolate_envs(base)
    try:
        cfg = load_config(
            env_file=_write_min_env(base),
            json_file=_write_json(base, {"share_agent_skills": "yes"}),
        )
        assert cfg.share_agent_skills is True
    finally:
        _restore_envs(old)
        shutil.rmtree(base, ignore_errors=True)

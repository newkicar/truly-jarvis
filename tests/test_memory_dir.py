"""dotdir: config sentinel 语义（缺省/哨兵 → 项目级 .jarvis/memory）+ 一次性 memory 迁移与 copy-seed 测试。"""

import json
import shutil
import tempfile
import uuid
from pathlib import Path

from src.config import load_config
from src.memory_dir import maybe_migrate_memory
from src.project_paths import ENV_JARVIS_HOME, user_home


def _workdir():
    base = Path(tempfile.gettempdir())
    d = base / ("jarvis-memtest-" + uuid.uuid4().hex[:8])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fake_config(memory_dir, project_root):
    import types

    return types.SimpleNamespace(memory_dir=Path(memory_dir), project_root=Path(project_root))


def _mk_project(home, with_memory=True):
    project = home / "proj"
    project.mkdir()
    global_mem = home / "memory"
    global_mem.mkdir()
    if with_memory:
        mem = project / "memory"
        mem.mkdir()
        (mem / "agent-memory.md").write_text("# project memory", encoding="utf-8")
    return project, global_mem


def _run_migrate(monkeypatch, home, project):
    monkeypatch.setenv(ENV_JARVIS_HOME, str(home))
    assert user_home().resolve() == home.resolve()
    cfg = _fake_config(project / ".jarvis" / "memory", project)
    return maybe_migrate_memory(cfg)


def test_migrate_moves_top_level_md(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home)
        notes = _run_migrate(monkeypatch, home, project)
        assert (project / ".jarvis" / "memory" / "agent-memory.md").is_file()
        assert not (project / "memory").exists()
        assert any("moved agent-memory.md" in n for n in notes)
        # 全局为空 → 无 copy-seed 日志
        assert not any("copy-seed" in n for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_same_content_is_idempotent(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home)
        (project / ".jarvis" / "memory" / "agent-memory.md").parent.mkdir(parents=True)
        (project / ".jarvis" / "memory" / "agent-memory.md").write_text("# project memory", encoding="utf-8")
        notes1 = _run_migrate(monkeypatch, home, project)
        # 同名同内容：源留原地、不 move、不更名
        assert (project / "memory/agent-memory.md").is_file()
        assert not (project / ".jarvis" / "memory" / "agent-memory__proj.md").exists()
        assert any("同名同内容" in n for n in notes1)
        notes2 = _run_migrate(monkeypatch, home, project)
        assert notes2 == notes1
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_same_name_diff_content_renames(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home)
        target_dir = project / ".jarvis" / "memory"
        target_dir.mkdir(parents=True)
        (target_dir / "agent-memory.md").write_text("# target other", encoding="utf-8")
        notes = _run_migrate(monkeypatch, home, project)
        assert (target_dir / "agent-memory.md").read_text(encoding="utf-8") == "# target other"
        assert (target_dir / "agent-memory__proj.md").read_text(encoding="utf-8") == "# project memory"
        assert any("同名异容" in n for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_dream_subdir_per_file(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        dream = project / "memory/dream"
        dream.mkdir(parents=True)
        (dream / "knowledge.md").write_text("# dream", encoding="utf-8")
        _run_migrate(monkeypatch, home, project)
        assert (project / ".jarvis" / "memory" / "dream/knowledge.md").is_file()
        assert not (project / "memory/dream").exists()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_rag_index_moved_when_target_absent(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        rag = project / "memory/rag-index"
        rag.mkdir(parents=True)
        (rag / "index.sqlite").write_text("x", encoding="utf-8")
        notes = _run_migrate(monkeypatch, home, project)
        assert (project / ".jarvis" / "memory" / "rag-index/index.sqlite").is_file()
        assert any("moved rag-index/" in n for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_rag_index_kept_when_target_exists(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        rag = project / "memory/rag-index"
        rag.mkdir(parents=True)
        (rag / "index.sqlite").write_text("old", encoding="utf-8")
        target = project / ".jarvis" / "memory" / "rag-index"
        target.mkdir(parents=True)
        (target / "index.sqlite").write_text("new", encoding="utf-8")
        notes = _run_migrate(monkeypatch, home, project)
        assert (target / "index.sqlite").read_text(encoding="utf-8") == "new"
        assert (rag / "index.sqlite").is_file()
        assert any("目标已存在" in n for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_explicit_dir_not_touched(monkeypatch):
    home = _workdir()
    try:
        project = home / "proj"
        project.mkdir()
        custom = home / "custom-memory"
        custom.mkdir()
        mem = project / "memory"
        mem.mkdir()
        (mem / "agent-memory.md").write_text("m", encoding="utf-8")
        monkeypatch.setenv(ENV_JARVIS_HOME, str(home))
        notes = maybe_migrate_memory(_fake_config(custom, project))
        assert notes == []
        assert (mem / "agent-memory.md").is_file()
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_migrate_no_project_memory_dir_noop(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        notes = _run_migrate(monkeypatch, home, project)
        assert notes == []
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_copy_seed_applies_when_target_empty(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        (global_mem / "shared-pref.md").write_text("# shared", encoding="utf-8")
        notes = _run_migrate(monkeypatch, home, project)
        # 播种落位，全局原件仍在（拷贝而非移动）
        assert (project / ".jarvis" / "memory" / "shared-pref.md").is_file()
        assert (global_mem / "shared-pref.md").is_file()
        assert any("copy-seed" in n for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_copy_seed_skipped_when_target_nonempty(monkeypatch):
    home = _workdir()
    try:
        project, global_mem = _mk_project(home, with_memory=False)
        (global_mem / "shared-pref.md").write_text("# shared", encoding="utf-8")
        target_dir = project / ".jarvis" / "memory"
        target_dir.mkdir(parents=True)
        (target_dir / "local.md").write_text("# local", encoding="utf-8")
        notes = _run_migrate(monkeypatch, home, project)
        assert not (target_dir / "shared-pref.md").exists()
        assert any(("copy-seed" in n and "跳过" in n) for n in notes)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _load_cfg(tmp, json_dict, monkeypatch):
    tmp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(ENV_JARVIS_HOME, str(tmp / "home"))
    env = tmp / ".env"
    env.write_text("base_url:https://x\napi_key:k\nmodel_id:m\ntavily_key:t\n",
                   encoding="utf-8")
    jf = tmp / "jarvis.json"
    jf.write_text(json.dumps(json_dict, ensure_ascii=False), encoding="utf-8")
    return load_config(env_file=env, json_file=jf)


def test_config_missing_memory_dir_defaults_project_dotdir(monkeypatch):
    base = _workdir()
    try:
        cfg = _load_cfg(base, {}, monkeypatch)
        expected = (base / ".jarvis" / "memory").resolve()
        assert cfg.memory_dir == expected
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_config_sentinel_memory_string_defaults_project_dotdir(monkeypatch):
    base = _workdir()
    try:
        cfg = _load_cfg(base, {"memory_dir": "memory"}, monkeypatch)
        expected = (base / ".jarvis" / "memory").resolve()
        assert cfg.memory_dir == expected
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_config_explicit_relative_resolves_to_project_root(monkeypatch):
    base = _workdir()
    try:
        cfg = _load_cfg(base, {"memory_dir": "my-mem"}, monkeypatch)
        assert cfg.memory_dir == (base / "my-mem").resolve()
        assert cfg.memory_dir != (base / ".jarvis" / "memory").resolve()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_config_explicit_absolute_kept_as_is(monkeypatch):
    base = _workdir()
    try:
        abs_dir = (base / "abs-mem").resolve()
        cfg = _load_cfg(base, {"memory_dir": str(abs_dir)}, monkeypatch)
        assert cfg.memory_dir == abs_dir
    finally:
        shutil.rmtree(base, ignore_errors=True)

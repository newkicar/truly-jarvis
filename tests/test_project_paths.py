"""project_paths 测试。"""
from pathlib import Path

from src.project_paths import (
    discover_project_root,
    get_project_root,
    install_root,
    resolve_env_file,
    resolve_javis_json,
    set_runtime_project_root,
)


def test_discover_project_root_finds_javis_in_parent(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    project = tmp_path / "my-app"
    nested = project / "sub"
    nested.mkdir(parents=True)
    (project / "javis.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(nested)
    assert discover_project_root() == project.resolve()


def test_discover_project_root_uses_cwd_when_no_javis(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert discover_project_root() == empty.resolve()


def test_discover_project_root_env_override(tmp_path, monkeypatch):
    forced = tmp_path / "forced"
    forced.mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(forced))
    assert discover_project_root() == forced.resolve()


def test_resolve_javis_json_prefers_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "javis.json").write_text("{}", encoding="utf-8")
    assert resolve_javis_json(project) == project / "javis.json"


def test_runtime_project_root(monkeypatch):
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    set_runtime_project_root(Path("/tmp/javis-test-root"))
    try:
        assert get_project_root() == Path("/tmp/javis-test-root").resolve()
    finally:
        set_runtime_project_root(install_root())


def test_resolve_env_file_project_before_install(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("BASE_URL:https://x.com\n", encoding="utf-8")
    assert resolve_env_file(project) == project / ".env"


# ---------------------------------------------------------------- JARVIS.md 项目指令层


def test_load_project_instructions_empty_when_missing(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    assert load_project_instructions(tmp_path) == ""


def test_load_project_instructions_project_level(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    (tmp_path / "JARVIS.md").write_text("测试命令是 pytest -q\n", encoding="utf-8")
    text = load_project_instructions(tmp_path)
    assert "pytest -q" in text
    assert "本项目约定" in text
    assert "全局用户约定" not in text


def test_load_project_instructions_global_plus_project(tmp_path, monkeypatch):
    from src.project_paths import load_project_instructions

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    (home / "JARVIS.md").write_text("全局：回复用中文\n", encoding="utf-8")
    (tmp_path / "JARVIS.md").write_text("项目：包管理器用 pnpm\n", encoding="utf-8")
    text = load_project_instructions(tmp_path)
    assert text.index("全局用户约定") < text.index("本项目约定"), "全局在前"
    assert "回复用中文" in text and "pnpm" in text

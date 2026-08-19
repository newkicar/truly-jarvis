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

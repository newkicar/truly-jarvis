"""project_init 测试。"""
from pathlib import Path

from src.project_init import init_project, suggest_init_if_missing


def test_init_project_creates_layout(tmp_path: Path):
    created, skipped, messages = init_project(tmp_path, vault_path="D:/vault")
    assert (tmp_path / "javis.json").is_file()
    assert (tmp_path / ".env").is_file()
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / "vault" / "Inbox").is_dir()
    assert (tmp_path / "run-javis.cmd").is_file()
    data = (tmp_path / "javis.json").read_text(encoding="utf-8")
    assert "D:/vault" in data
    assert "copy_on_select" in data
    assert created
    assert any("API" in m for m in messages)


def test_init_project_skips_existing_javis_json(tmp_path: Path):
    (tmp_path / "javis.json").write_text("{}", encoding="utf-8")
    created, skipped, _ = init_project(tmp_path)
    assert str(tmp_path / "javis.json") in skipped
    assert (tmp_path / "javis.json").read_text(encoding="utf-8") == "{}"


def test_init_project_force_overwrites_javis_json(tmp_path: Path):
    (tmp_path / "javis.json").write_text("{}", encoding="utf-8")
    init_project(tmp_path, force=True)
    assert '"obsidian_vault"' in (tmp_path / "javis.json").read_text(encoding="utf-8")


def test_suggest_init_if_missing(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    hint = suggest_init_if_missing()
    assert hint is not None
    assert "--init" in hint

    (empty / "javis.json").write_text("{}", encoding="utf-8")
    assert suggest_init_if_missing() is None

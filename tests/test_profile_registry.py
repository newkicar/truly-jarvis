"""Tests for src/profiles/registry.py and db.py.

Covers three-layer discovery, merge with security narrowing, legacy
virtual profiles, AGENTS.md layering, BOM tolerance, db upsert, and
JARVIS_HOME redirection. Scratch state lives under .scratch/
profile-test-tmp (gitignored); no tmp_path fixtures in this repo.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
import yaml

from src.profiles import ProfileError
from src.profiles.db import connect, list_profile_rows, meta_db_path
from src.profiles.registry import ProfileRegistry

_ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = _ROOT / ".scratch" / "profile-test-tmp"

BUILTIN_SKILLS = {
    "researcher": ("web-research",),
    "secretary": ("vault-nav", "local-facts"),
    "developer": ("docx", "xlsx", "pdf"),
}


@pytest.fixture(autouse=True)
def _clean_scratch():
    yield
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def _new_home() -> Path:
    home = _SCRATCH / f"home-{uuid.uuid4().hex[:12]}"
    home.mkdir(parents=True)
    return home


def _new_workspace() -> Path:
    ws = _SCRATCH / f"ws-{uuid.uuid4().hex[:12]}"
    ws.mkdir(parents=True)
    return ws


def _user_yaml(home: Path, pid: str, data: dict) -> Path:
    d = home / "agents" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return d


def _project_yaml(ws: Path, pid: str, data: dict) -> Path:
    d = ws / ".jarvis" / "agents" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return d


def _registry(home: Path, ws: Path | None = None, legacy: dict | None = None) -> ProfileRegistry:
    return ProfileRegistry(user_home=home, workspace=ws, jarvis_json_agents=legacy)


class TestList:
    def test_builtin_user_project_legacy_sorted(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "writer", {"id": "writer", "name": "Writer"})
        _project_yaml(ws, "qa", {"id": "qa"})
        reg = _registry(home, ws, legacy={"legacy1": "legacy agent"})
        assert reg.list() == [
            "developer", "legacy1", "qa", "researcher", "secretary", "writer",
        ]

    def test_no_workspace_skips_project_layer(self):
        home, ws = _new_home(), _new_workspace()
        _project_yaml(ws, "qa", {"id": "qa"})
        reg = _registry(home, None)
        assert "qa" not in reg.list()
        assert len(reg.list()) == 3  # builtin only


class TestGet:
    def test_unknown_raises(self):
        reg = _registry(_new_home())
        with pytest.raises(ProfileError, match="unknown profile"):
            reg.get("nope")

    def test_builtin_skill_mappings(self):
        reg = _registry(_new_home())
        for pid, skills in BUILTIN_SKILLS.items():
            p = reg.get(pid)
            assert p.skills.include == skills
            assert p.memory.namespace == pid
            assert p.is_legacy is False

    def test_legacy_str_entry(self):
        reg = _registry(_new_home(), legacy={"l1": "does things"})
        p = reg.get("l1")
        assert p.is_legacy is True
        assert p.description == "does things"
        assert p.name == "l1"

    def test_legacy_dict_entry(self):
        reg = _registry(_new_home(), legacy={"l2": {"description": "desc2"}})
        p = reg.get("l2")
        assert p.is_legacy is True
        assert p.description == "desc2"


class TestMerge:
    def test_three_layer_merge(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "researcher",
                   {"name": "Custom Researcher", "identity": {"role": "sr"}})
        _project_yaml(ws, "researcher",
                     {"description": "project desc",
                      "permissions": {"approvals": {"external_network": "required"}}})
        p = _registry(home, ws).get("researcher")
        assert p.name == "Custom Researcher"
        assert p.description == "project desc"
        assert p.identity.role == "sr"
        assert p.permissions.approvals.external_network == "required"

    def test_loosening_execute_rejected(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "researcher", {"name": "n"})
        _project_yaml(ws, "researcher",
                     {"permissions": {"approvals": {"execute": "optional"}}})
        with pytest.raises(ProfileError, match="loosening"):
            _registry(home, ws).get("researcher")

    def test_loosening_workspace_only_rejected(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "researcher",
                   {"permissions": {"filesystem": {"workspace_only": True}}})
        _project_yaml(ws, "researcher",
                     {"permissions": {"filesystem": {"workspace_only": False}}})
        with pytest.raises(ProfileError, match="loosening"):
            _registry(home, ws).get("researcher")

    def test_loosening_can_delegate_rejected(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "researcher",
                   {"permissions": {"can_delegate": False}})
        _project_yaml(ws, "researcher",
                     {"permissions": {"can_delegate": True}})
        with pytest.raises(ProfileError, match="loosening"):
            _registry(home, ws).get("researcher")

    def test_tightening_allowed_end_to_end(self):
        home, ws = _new_home(), _new_workspace()
        _user_yaml(home, "researcher",
                   {"permissions": {"approvals": {"external_network": "required"}}})
        _project_yaml(ws, "researcher",
                     {"permissions": {"filesystem": {"workspace_only": True}}})
        p = _registry(home, ws).get("researcher")
        assert p.permissions.approvals.external_network == "required"
        assert p.permissions.filesystem.workspace_only is True


class TestEncodingTolerance:
    def test_bom_yaml_and_agents_md(self):
        home = _new_home()
        d = home / "agents" / "bomco"
        d.mkdir(parents=True)
        body = yaml.safe_dump({"id": "bomco", "name": "Bom"})
        (d / "agent.yaml").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        (d / "AGENTS.md").write_bytes(b"\xef\xbb\xbf" + "hello md".encode("utf-8"))
        out = _registry(home).load("bomco")
        assert out.profile.name == "Bom"
        assert out.agents_md_text == "hello md"
        assert not out.agents_md_text.startswith("\ufeff")

    def test_top_level_list_yaml_raises(self):
        home = _new_home()
        d = home / "agents" / "evil"
        d.mkdir(parents=True)
        (d / "agent.yaml").write_text(yaml.safe_dump(["a", "b"]), encoding="utf-8")
        with pytest.raises(ProfileError, match="mapping"):
            _registry(home).get("evil")


class TestInstructionsLayering:
    def test_project_md_beats_user_md(self):
        home, ws = _new_home(), _new_workspace()
        ud = _user_yaml(home, "writer", {"id": "writer"})
        ud.joinpath("AGENTS.md").write_text("user md", encoding="utf-8")
        pd = _project_yaml(ws, "writer", {"name": "W"})
        pd.joinpath("AGENTS.md").write_text("project md", encoding="utf-8")
        assert _registry(home, ws).load("writer").agents_md_text == "project md"
        pd.joinpath("AGENTS.md").unlink()
        assert _registry(home, ws).load("writer").agents_md_text == "user md"


class TestDbUpsert:
    def test_load_upserts_single_row(self):
        home = _new_home()
        out = _registry(home).load("developer")
        rows = list_profile_rows(home)
        assert len(rows) == 1
        row = rows[0]
        assert row["profile_id"] == "developer"
        assert row["enabled"] == 1
        assert row["schema_version"] == 1
        assert row["profile_version"] == 1
        assert row["profile_hash"] == out.profile_hash
        assert len(row["profile_hash"]) == 64
        assert row["source_path"].endswith("agent.yaml")
        _registry(home).load("developer")
        assert len(list_profile_rows(home)) == 1

    def test_load_legacy_writes_no_db(self):
        home = _new_home()
        out = _registry(home, legacy={"l1": "desc"}).load("l1")
        assert out.profile_hash == ""
        assert out.agents_md_text == ""
        assert out.source_path == ""
        assert not meta_db_path(home).exists()

    def test_load_all_hashes(self):
        home = _new_home()
        allp = _registry(home, legacy={"l1": "desc"}).load_all()
        by_id = {o.profile.id: o for o in allp}
        assert by_id["l1"].profile_hash == ""
        for pid in ("researcher", "secretary", "developer"):
            assert len(by_id[pid].profile_hash) == 64


class TestDbConnect:
    def test_connect_idempotent_creates_tables(self):
        home = _new_home()
        conn = connect(home)
        conn.close()
        conn = connect(home)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            expected = {
                "agent_profiles", "agent_runs", "memory_entries",
                "memory_candidates", "schema_migrations",
            }
            assert expected <= tables
            versions = [r[0] for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()]
            assert versions == [1]
        finally:
            conn.close()


class TestJarvisHomeEnv:
    def test_env_rebuilds_default_user_home(self, monkeypatch):
        home = _new_home()
        monkeypatch.setenv("JARVIS_HOME", str(home))
        out = ProfileRegistry().load("developer")
        assert out.profile.name == "Developer"
        assert meta_db_path(home).exists()
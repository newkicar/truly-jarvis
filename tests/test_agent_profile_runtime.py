"""Agent Profile runtime integration tests (ticket 02).

Covers the pure bake_spec behavior (suffix, permissions, memory dirs,
snapshot, cache), the default-path no-behavior-difference gate,
build_agent(profile_spec=...), and create_jarvis(profile_id=...) e2e.
Scratch state under .scratch/profile-test-tmp (gitignored); no tmp_path
fixtures in this repo.
"""
from __future__ import annotations

import dataclasses
import shutil
import uuid
from pathlib import Path

import pytest
import yaml
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import src.agent as agent_mod
from src.agent import build_agent, build_main_prompt, create_jarvis
from src.profiles.schema import (
    AgentProfile,
    Approvals,
    Identity,
    Memory,
    Permissions,
    Runtime,
    Session,
    Tools,
)
from src.profiles.spec import (
    PROFILE_CONFLICT_NOTE,
    _reset_bake_cache,
    bake_cache_stats,
    bake_spec,
)
from tests.conftest import make_fake_config
from tests.test_agent import ToolCapableFake

_ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = _ROOT / ".scratch" / "profile-test-tmp"


@pytest.fixture(autouse=True)
def _clean_scratch():
    yield
    _reset_bake_cache()
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def _new_home() -> Path:
    home = _SCRATCH / f"home-{uuid.uuid4().hex[:12]}"
    home.mkdir(parents=True)
    return home


def _new_workspace() -> Path:
    ws = _SCRATCH / f"ws-{uuid.uuid4().hex[:12]}"
    ws.mkdir(parents=True)
    return ws


def _profile(**kw) -> AgentProfile:
    return AgentProfile(
        id="test-prof",
        name=kw.get("name", "Test Prof"),
        description="test profile",
        identity=Identity(role="tester", mission="do tests", principles=("pr1", "pr2")),
        runtime=Runtime(engine="deepagents", model=kw.get("model", "")),
        memory=Memory(enabled=kw.get("memory_enabled", True), namespace=kw.get("namespace", "")),
        tools=Tools(allow=tuple(kw.get("allow", ())), deny=tuple(kw.get("deny", ()))),
        permissions=Permissions(approvals=kw.get("approvals", Approvals())),
        session=Session(),
    )


_ALL_OPTIONAL = Approvals(execute="optional", external_network="optional", destructive_operations="optional")


def _cfg(monkeypatch, home: Path, ws: Path):
    monkeypatch.setenv("JARVIS_HOME", str(home))
    return make_fake_config(ws)


def _spy_build(monkeypatch):
    from src.agent import create_deep_agent

    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    return captured


def _mcp_tool(name: str) -> StructuredTool:
    class _Args(BaseModel):
        query: str = Field(description="q")

    return StructuredTool(
        name=name,
        description=f"fake {name}",
        args_schema=_Args,
        func=lambda **_kw: "ok",
    )


def _names(tools) -> list[str]:
    return [getattr(t, "name", "") for t in tools]


class TestBakeSpec:
    def test_none_profile_returns_none(self):
        assert bake_spec(None, None, "ws") is None

    def test_default_suffix_content(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        p = _profile()
        spec = bake_spec(cfg, p, str(ws))
        s = spec.prompt_suffix
        assert "## Agent Profile: test-prof (Test Prof)" in s
        assert "Description: test profile" in s
        assert "Role: tester" in s
        assert "Mission: do tests" in s
        assert "Principles:" in s
        assert "- pr1" in s
        assert "- pr2" in s
        assert "Profile Instructions" not in s

    def test_agents_md_appended_only_when_nonempty(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        p = _profile()
        spec = bake_spec(cfg, p, str(ws), agents_md_text="use the vault")
        assert "## Profile Instructions (AGENTS.md)" in spec.prompt_suffix
        assert "use the vault" in spec.prompt_suffix
        spec2 = bake_spec(cfg, p, str(ws), agents_md_text="   ")
        assert "Profile Instructions" not in spec2.prompt_suffix

    def test_skill_routes_empty_in_ticket_02(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws))
        assert spec.skill_routes == ()

    def test_model_fallback_and_override(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        assert bake_spec(cfg, _profile(), str(ws)).model_id == cfg.model_id
        assert bake_spec(cfg, _profile(model="m2"), str(ws)).model_id == "m2"

    def test_permission_rules_default_approvals(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws))
        assert spec.permission_extra_rules == {
            "execute": "ask",
            "write_file": "ask",
            "edit_file": "ask",
            "delete": "ask",
            "quick_search": "ask",
            "search": "ask",
            "deep_search": "ask",
        }

    def test_permission_rules_all_optional_empty(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(approvals=_ALL_OPTIONAL), str(ws))
        assert spec.permission_extra_rules == {}

    def test_permission_rules_execute_only(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        p = _profile(approvals=Approvals(execute="required", external_network="optional", destructive_operations="optional"))
        spec = bake_spec(cfg, p, str(ws))
        assert spec.permission_extra_rules == {"execute": "ask"}

    def test_memory_dirs_namespace_fallback(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws))
        assert spec.memory_dirs == ((home / "agents" / "test-prof" / "memory").as_posix(),)

    def test_memory_dirs_explicit_namespace(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(namespace="sec"), str(ws))
        assert spec.memory_dirs == ((home / "agents" / "sec" / "memory").as_posix(),)

    def test_memory_dirs_task_and_project(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws), task_id="t1", project_id="p1")
        assert spec.memory_dirs == (
            (home / "agents" / "test-prof" / "memory").as_posix(),
            (home / "tasks" / "t1").as_posix(),
            (home / "projects" / "p1" / "memory").as_posix(),
        )

    def test_memory_disabled_still_task_project(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(memory_enabled=False), str(ws), task_id="t1", project_id="p1")
        assert spec.memory_dirs == (
            (home / "tasks" / "t1").as_posix(),
            (home / "projects" / "p1" / "memory").as_posix(),
        )

    def test_snapshot_fields(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws), task_id="t1", session_id="s1")
        d = spec.snapshot.to_dict()
        assert d["profile_id"] == "test-prof"
        assert d["profile_version"] == str(spec.profile_version)
        assert d["engine"] == "deepagents"
        assert d["task_id"] == "t1"
        assert d["session_id"] == "s1"
        assert d["workspace"] == str(ws)
        assert len(d["profile_hash"]) == 64

    def test_cache_identity_and_stats(self, monkeypatch):
        _reset_bake_cache()
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        p = _profile()
        s1 = bake_spec(cfg, p, str(ws))
        s2 = bake_spec(cfg, p, str(ws))
        assert s1 is s2
        stats = bake_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_cache_miss_on_key_change(self, monkeypatch):
        _reset_bake_cache()
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        base = bake_spec(cfg, _profile(), str(ws))
        assert base is not bake_spec(cfg, _profile(), str(ws), agents_md_text="x")
        assert base is not bake_spec(cfg, _profile(), str(ws), skill_manifest_hash="mm")
        assert base is not bake_spec(cfg, _profile(), str(ws), task_id="t9")
        assert base is not bake_spec(cfg, _profile(), str(ws), project_id="p9")
        assert base is not bake_spec(cfg, _profile(), str(ws), session_id="s9")
        assert base is not bake_spec(cfg, _profile(), str(ws / "other"))


class TestDefaultPathGate:
    def test_default_tools_and_prompt(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        captured = _spy_build(monkeypatch)
        agent = build_agent(cfg, model=ToolCapableFake(reply="ok"))
        assert _names(captured["tools"]) == ["quick_search", "create_goal", "complete_goal", "get_goal"]
        assert captured["system_prompt"] == build_main_prompt(config=cfg)
        assert agent is not None

    def test_default_with_mcp_tools(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), mcp_tools=[_mcp_tool("git_status")])
        assert _names(captured["tools"]) == ["quick_search", "git_status", "create_goal", "complete_goal", "get_goal"]

    def test_default_memory_files(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        (cfg.memory_dir).mkdir(parents=True, exist_ok=True)
        (cfg.memory_dir / "notes.md").write_text("n", encoding="utf-8")
        (cfg.memory_dir / "dream").mkdir(parents=True, exist_ok=True)
        (cfg.memory_dir / "dream" / "knowledge.md").write_text("k", encoding="utf-8")
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"))
        mem = captured["memory"]
        assert (cfg.memory_dir / "notes.md").as_posix() in mem
        assert (cfg.memory_dir / "dream" / "knowledge.md").as_posix() in mem

    def test_default_snapshot_none(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        _spy_build(monkeypatch)
        agent = build_agent(cfg, model=ToolCapableFake(reply="ok"))
        assert getattr(agent, "_jarvis_profile_snapshot", "missing") is None

    def test_default_harness_registered(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"))
        assert agent_mod.harness_profile_loaded(cfg.model_id)


class TestBuildAgentWithSpec:
    def test_prompt_exact_composition(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(), str(ws))
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), profile_spec=spec)
        assert captured["system_prompt"] == (
            build_main_prompt(config=cfg) + "\n" + spec.prompt_suffix + "\n" + PROFILE_CONFLICT_NOTE
        )

    def test_model_override_via_make_model_spy(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(model="m2"), str(ws))
        recorded = []

        def spy_make(config, model_id=None):
            recorded.append(model_id)
            return ToolCapableFake(reply="ok")

        monkeypatch.setattr(agent_mod, "_make_model", spy_make)
        _spy_build(monkeypatch)
        build_agent(cfg, model=None, profile_spec=spec)
        assert recorded == ["m2"]

    def test_harness_registered_for_spec_model(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(model="prof-m2"), str(ws))
        _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), profile_spec=spec)
        assert agent_mod.harness_profile_loaded("prof-m2")
        assert "prof-m2" in agent_mod._HARNESS_REGISTERED

    def test_spec_memory_dirs_injected(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        p = _profile(namespace="ns1")
        spec = bake_spec(cfg, p, str(ws), task_id="t1")
        agent_dir = home / "agents" / "ns1" / "memory"
        agent_dir.mkdir(parents=True)
        (agent_dir / "a.md").write_text("a", encoding="utf-8")
        task_dir = home / "tasks" / "t1"
        task_dir.mkdir(parents=True)
        (task_dir / "b.md").write_text("b", encoding="utf-8")
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), profile_spec=spec)
        mem = captured["memory"]
        assert agent_dir.joinpath("a.md").as_posix() in mem
        assert task_dir.joinpath("b.md").as_posix() in mem

    def test_tool_deny_removes(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(deny=("quick_search", "git_status")), str(ws))
        captured = _spy_build(monkeypatch)
        build_agent(
            cfg,
            model=ToolCapableFake(reply="ok"),
            mcp_tools=[_mcp_tool("git_status"), _mcp_tool("other_tool")],
            profile_spec=spec,
        )
        assert _names(captured["tools"]) == ["other_tool", "create_goal", "complete_goal", "get_goal"]

    def test_tool_allow_restricts(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(allow=("git_status",)), str(ws))
        captured = _spy_build(monkeypatch)
        build_agent(
            cfg,
            model=ToolCapableFake(reply="ok"),
            mcp_tools=[_mcp_tool("git_status"), _mcp_tool("other_tool")],
            profile_spec=spec,
        )
        assert _names(captured["tools"]) == ["git_status"]

    def test_all_optional_deny_execute_is_false(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = _cfg(monkeypatch, home, ws)
        spec = bake_spec(cfg, _profile(approvals=_ALL_OPTIONAL, deny=("execute",)), str(ws))
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), profile_spec=spec)
        assert captured["interrupt_on"]["execute"] is False
        wf = captured["interrupt_on"]["write_file"]
        assert isinstance(wf, dict)
        assert "edit" in wf["allowed_decisions"]

    def test_allow_default_still_asks_gated(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        cfg = dataclasses.replace(make_fake_config(ws), permissions={"*": "allow"})
        monkeypatch.setenv("JARVIS_HOME", str(home))
        p = _profile()
        spec = bake_spec(cfg, p, str(ws))
        captured = _spy_build(monkeypatch)
        build_agent(cfg, model=ToolCapableFake(reply="ok"), profile_spec=spec)
        for tool in ("execute", "write_file", "edit_file", "delete"):
            entry = captured["interrupt_on"][tool]
            assert isinstance(entry, dict), tool
            assert entry["allowed_decisions"] == ["approve", "reject", "edit"]
        # ticket 05: profile-scoped (fail-closed) tools are gated as ask too,
        # a wildcard allow in config must not leak through to them.
        entry = captured["interrupt_on"]["quick_search"]
        assert isinstance(entry, dict)
        assert entry["allowed_decisions"] == ["approve", "reject", "edit"]


class TestCreateJarvis:
    ENV_OVERRIDES = {
        "BASE_URL": "https://fake/v1",
        "API_KEY": "sk",
        "MODEL_ID": "m",
        "TAVILY_KEY": "tvly",
    }

    def test_profile_none_default(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        monkeypatch.setenv("JARVIS_HOME", str(home))
        _spy_build(monkeypatch)
        agent = create_jarvis(ws, model=ToolCapableFake(reply="ok"), env_overrides=dict(self.ENV_OVERRIDES))
        assert getattr(agent, "_jarvis_profile_snapshot", "missing") is None

    def test_profile_id_e2e(self, monkeypatch):
        home, ws = _new_home(), _new_workspace()
        monkeypatch.setenv("JARVIS_HOME", str(home))
        sec_dir = home / "agents" / "sec"
        sec_dir.mkdir(parents=True)
        (sec_dir / "agent.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "sec",
                    "name": "Secretary",
                    "permissions": {"approvals": {
                        "execute": "optional",
                        "external_network": "optional",
                        "destructive_operations": "optional",
                    }},
                }
            ),
            encoding="utf-8",
        )
        (sec_dir / "AGENTS.md").write_text("secretary rules text", encoding="utf-8")
        captured = _spy_build(monkeypatch)
        agent = create_jarvis(
            ws,
            model=ToolCapableFake(reply="ok"),
            env_overrides=dict(self.ENV_OVERRIDES),
            profile_id="sec",
        )
        snap = getattr(agent, "_jarvis_profile_snapshot", None)
        assert snap is not None
        assert snap.to_dict()["profile_id"] == "sec"
        assert "secretary rules text" in captured["system_prompt"]
        for tool in ("execute", "write_file", "edit_file", "delete"):
            entry = captured["interrupt_on"][tool]
            assert isinstance(entry, dict), tool

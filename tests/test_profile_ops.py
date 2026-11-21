"""Ticket 07: ops observability + diagnostics tests.

Covered:
  - src/profiles/observability.py: 20-kind JSONL event emit, secret-key
    redaction, 200-char string truncation, 4096-byte line cap, fail-safe
    no-op (unknown kinds / unwritable home), tail reader (chronological
    order, default limit, bad-line skip, 256 KB window first-line drop)
  - src/profiles/diagnostics.py: list_profiles / validate_profile /
    profiles_cli / skill_manifest_report / memory_namespace_view /
    permission_diagnose
  - spec.bake_spec ops wiring: skills_resolved / cache_hit / cache_miss

Scratch state under .scratch/profile-test-tmp (gitignored); no tmp_path
fixtures in this repo. Chinese assertion strings are written as \\uXXXX
escapes so this file stays pure ASCII (PowerShell/CP936 delivery-safe).
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
import yaml

from src.profiles import diagnostics as dg
from src.profiles import observability as ob
from src.profiles.registry import ProfileRegistry
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
from tests.conftest import make_fake_config

_ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = _ROOT / ".scratch" / "profile-test-tmp"

# --- diagnostics CJK literals, \u-escaped to keep this file ASCII ------
Z_UNK = "\u672a\u77e5"
Z_PARSE_FAIL = "\u89e3\u6790\u5931\u8d25"
Z_PARSE_VALIDATE = "\u89e3\u6790/\u6821\u9a8c\u5931\u8d25"
Z_PERM_DIAG = "\u6743\u9650\u8bca\u65ad"
Z_SKILL_LIST = "\u6e05\u5355"
Z_MEM_NS = "\u8bb0\u5fc6\u547d\u540d\u7a7a\u95f4"
Z_DIR_MISSING = "\u76ee\u5f55\u4e0d\u5b58\u5728"
Z_CAND = "\u5019\u9009"
Z_DB_ROWS = "db agent_profiles \u884c"
Z_NONGATED = "\u975e gated \u5de5\u5177"
Z_DEFAULT_ALLOW = "\u9ed8\u8ba4\u653e\u884c"
Z_ASK_RULE = "\u89e6\u53d1 ask \u89c4\u5219"
Z_EACH_APPROVE = "\u6bcf\u6b21\u5ba1\u6279"
Z_NOT_FORCED = "\u4e0d\u5f3a\u5236"
Z_STILL_BOUND = "\u4ecd\u53d7 jarvis.json permissions \u6bb5\u7ea6\u675f"
Z_USAGE = "\u7528\u6cd5"

EXPECTED_KINDS = (
    "profile_loaded",
    "profile_validation_failed",
    "runtime_created",
    "cache_hit",
    "cache_miss",
    "skills_resolved",
    "tools_resolved",
    "memory_recall",
    "memory_candidate_created",
    "memory_candidate_promoted",
    "memory_candidate_rejected",
    "tool_permission_denied",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "worker_started",
    "worker_completed",
    "worker_failed",
    "worker_cancelled",
    "checkpoint_resumed",
)


@pytest.fixture(autouse=True)
def _clean_scratch():
    yield
    from src.profiles.spec import _reset_bake_cache

    _reset_bake_cache()
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def _new_home() -> Path:
    home = _SCRATCH / ("home-" + uuid.uuid4().hex[:12])
    home.mkdir(parents=True)
    return home


@pytest.fixture()
def ops_home(monkeypatch):
    """Scratch home with JARVIS_HOME redirected, so ops_event targets it."""
    home = _new_home()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    return home


def _events_file(home: Path) -> Path:
    return home / "ops" / "events.jsonl"


def _all_events(home: Path):
    return ob.read_ops_events(home, limit=None)


def _put_events(home: Path, lines) -> None:
    p = _events_file(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


class TestOpsEmit:
    def test_expected_20_kinds(self):
        assert len(ob.OPS_EVENT_KINDS) == 20
        assert ob.OPS_EVENT_KINDS == EXPECTED_KINDS

    def test_emit_writes_jsonl_record(self, ops_home):
        assert ob.ops_event("profile_loaded", profile_id="developer") is None
        lines = _events_file(ops_home).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["kind"] == "profile_loaded"
        assert rec["profile_id"] == "developer"
        assert "ts" in rec

    def test_unknown_kind_is_noop(self, ops_home):
        assert ob.ops_event("no_such_kind", a=1) is None
        assert not _events_file(ops_home).exists()

    def test_all_known_kinds_emit(self, ops_home):
        for kind in ob.OPS_EVENT_KINDS:
            assert ob.ops_event(kind) is None
        assert [e["kind"] for e in _all_events(ops_home)] == list(ob.OPS_EVENT_KINDS)

    def test_secret_keys_redacted(self, ops_home):
        ob.ops_event(
            "approval_requested",
            api_key="SECRET",
            auth_token="T",
            my_secret="S",
            password="P",
            credentials={"u": 1},
            response_content="C",
            prompt_text="PT",
            tool_args={"x": 1},
            nested=[{"secret_in_list": 1}],
            normal="keep-me",
        )
        rec = _all_events(ops_home)[0]
        for key in (
            "api_key",
            "auth_token",
            "my_secret",
            "password",
            "credentials",
            "response_content",
            "prompt_text",
            "tool_args",
        ):
            assert rec[key] == "<redacted>"
        assert rec["nested"] == [{"secret_in_list": "<redacted>"}]
        assert rec["normal"] == "keep-me"

    def test_long_string_truncated(self, ops_home):
        ob.ops_event("cache_hit", longstr="x" * 300)
        rec = _all_events(ops_home)[0]
        assert rec["longstr"] == "x" * 200 + "\u2026(+100 chars)"
        assert len(rec["longstr"]) == 213

    def test_line_cap_4096_bytes(self, ops_home):
        ob.ops_event("cache_hit", value="a" * 100000)
        raw = _events_file(ops_home).read_text(encoding="utf-8").splitlines()[-1]
        assert len(raw.encode("utf-8")) <= 4096
        rec = json.loads(raw)
        assert rec["kind"] == "cache_hit"
        assert len(rec["value"]) < 100000

    def test_unwritable_home_never_raises(self, monkeypatch):
        blocker = _new_home() / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setenv("JARVIS_HOME", str(blocker))
        assert ob.ops_event("cache_hit") is None


class TestOpsRead:
    def test_read_absent_file_returns_empty(self):
        assert ob.read_ops_events(_new_home()) == []

    def test_read_chronological_and_default_limit(self, ops_home):
        for i in range(60):
            ob.ops_event("cache_hit", idx=i)
        evs = ob.read_ops_events(ops_home)
        assert [e["idx"] for e in evs] == list(range(10, 60))

    def test_read_limit_none_returns_all(self, ops_home):
        for i in range(5):
            ob.ops_event("cache_hit", idx=i)
        assert len(_all_events(ops_home)) == 5

    def test_read_skips_bad_and_non_dict_lines(self):
        home = _new_home()
        _put_events(
            home,
            [
                json.dumps({"kind": "cache_hit", "n": 1}),
                "not json at all",
                json.dumps([1, 2, 3]),
                json.dumps({"kind": "cache_hit", "n": 2}),
            ],
        )
        evs = ob.read_ops_events(home, limit=None)
        assert [e["n"] for e in evs] == [1, 2]

    def test_read_window_drops_first_in_window_line(self):
        home = _new_home()
        fillers = [
            json.dumps(
                {
                    "kind": "cache_hit",
                    "seq": i,
                    "pad": "z" * (599 - len(str(i)) - 12),
                }
            )
            for i in range(500)
        ]
        fillers.append(json.dumps({"kind": "cache_hit", "tag": "good"}))
        _put_events(home, fillers)
        assert _events_file(home).stat().st_size > 256 * 1024
        evs = _all_events(home)
        assert evs[-1]["tag"] == "good"
        assert evs[0]["seq"] > 0
        assert len(evs) < 501


def _profile(**kw):
    return AgentProfile(
        id="p",
        name="P",
        identity=Identity(),
        runtime=Runtime(),
        memory=Memory(),
        tools=Tools(),
        permissions=Permissions(approvals=kw.get("approvals", Approvals())),
        session=Session(),
    )


class TestDiagnostics:
    def test_list_shows_builtin_ids(self):
        home = _new_home()
        text = dg.list_profiles(user_home=home)
        assert "- developer" in text
        assert "- researcher" in text
        assert "- secretary" in text

    def test_list_shows_user_profile_description(self):
        home = _new_home()
        pdir = home / "agents" / "demo"
        pdir.mkdir(parents=True)
        (pdir / "agent.yaml").write_text(
            yaml.safe_dump({"id": "demo", "name": "Demo", "description": "demo desc"}),
            encoding="utf-8",
        )
        text = dg.list_profiles(user_home=home)
        assert "- demo" in text
        assert "demo desc" in text

    def test_list_shows_db_rows_after_validate(self):
        home = _new_home()
        assert Z_DB_ROWS not in dg.list_profiles(user_home=home)
        code, text = dg.validate_profile("developer", user_home=home, strict=False)
        assert code == 0
        text2 = dg.list_profiles(user_home=home)
        assert Z_DB_ROWS in text2
        assert "- developer schema-v1 v1" in text2

    def test_validate_unknown_profile_exit_2(self):
        code, text = dg.validate_profile("nope", user_home=_new_home())
        assert code == 2
        assert Z_UNK in text
        assert "nope" in text

    def test_validate_malformed_yaml_exit_1(self):
        home = _new_home()
        pdir = home / "agents" / "badprof"
        pdir.mkdir(parents=True)
        (pdir / "agent.yaml").write_text("id: [unclosed", encoding="utf-8")
        code, text = dg.validate_profile("badprof", user_home=home)
        assert code == 1
        assert Z_PARSE_VALIDATE in text
        listing = dg.list_profiles(user_home=home)
        assert ("- badprof  " + Z_PARSE_FAIL) in listing

    def test_validate_strict_sections(self):
        home = _new_home()
        code, text = dg.validate_profile("developer", user_home=home)
        assert code == 0
        assert Z_SKILL_LIST in text
        assert "entries=" in text
        assert Z_MEM_NS in text
        assert "approvals.execute=required" in text
        assert Z_ASK_RULE in text
        assert "approvals.external_network=required" in text

    def test_validate_nonstrict_skips_strict_sections(self):
        home = _new_home()
        code, text = dg.validate_profile("developer", user_home=home, strict=False)
        assert code == 0
        assert Z_PERM_DIAG not in text
        assert Z_SKILL_LIST not in text
        assert "hash" in text

    def test_profiles_cli_no_args_lists(self):
        home = _new_home()
        code, text = dg.profiles_cli([], user_home=home)
        assert code == 0
        assert "developer" in text

    def test_profiles_cli_strips_command_prefixes(self):
        home = _new_home()
        assert dg.profiles_cli(["/profiles"], user_home=home)[0] == 0
        assert dg.profiles_cli(["--profiles", "developer"], user_home=home)[0] == 0

    def test_profiles_cli_validate_flag_strict(self):
        home = _new_home()
        code, text = dg.profiles_cli(["developer", "--validate"], user_home=home)
        assert code == 0
        assert Z_PERM_DIAG in text

    def test_profiles_cli_two_ids_rejected(self):
        code, text = dg.profiles_cli(["a", "b"], user_home=_new_home())
        assert code == 2
        assert Z_USAGE in text

    def test_profiles_cli_unknown_id(self):
        code, _ = dg.profiles_cli(["nope"], user_home=_new_home())
        assert code == 2

    def test_skill_manifest_report_unknown_profile(self):
        text = dg.skill_manifest_report("ghost", user_home=_new_home())
        assert Z_UNK in text

    def test_memory_namespace_view_lists_files(self):
        home = _new_home()
        memdir = home / "agents" / "memns" / "memory"
        (memdir / "sub").mkdir(parents=True)
        (memdir / "a.md").write_text("hello", encoding="utf-8")
        (memdir / "sub" / "b.md").write_text("xy", encoding="utf-8")
        text = dg.memory_namespace_view("memns", user_home=home)
        assert "a.md (5 B)" in text
        assert "sub/b.md (2 B)" in text
        assert Z_CAND in text

    def test_memory_namespace_view_missing_dir(self):
        text = dg.memory_namespace_view("ghost", user_home=_new_home())
        assert Z_DIR_MISSING in text
        assert "ghost" in text

    def test_permission_diagnose_matrix(self):
        p_req = _profile()
        assert "approvals.execute=required" in dg.permission_diagnose(p_req, "execute")
        assert Z_ASK_RULE in dg.permission_diagnose(p_req, "execute")
        for tool in ("write_file", "edit_file", "delete"):
            text = dg.permission_diagnose(p_req, tool)
            assert "approvals.destructive_operations=required" in text
            assert Z_EACH_APPROVE in text
        for tool in ("quick_search", "search", "deep_search"):
            text = dg.permission_diagnose(p_req, tool)
            assert "approvals.external_network=required" in text
            assert Z_ASK_RULE in text
        plain = dg.permission_diagnose(p_req, "ls")
        assert Z_NONGATED in plain
        assert Z_DEFAULT_ALLOW in plain
        p_opt = _profile(approvals=Approvals(execute="optional"))
        text = dg.permission_diagnose(p_opt, "execute")
        assert "approvals.execute=optional" in text
        assert Z_NOT_FORCED in text
        assert Z_STILL_BOUND in text


class TestBakeSpecOpsWiring:
    def test_bake_emits_skill_and_cache_events(self, ops_home):
        from src.profiles.spec import _reset_bake_cache, bake_spec

        _reset_bake_cache()
        reg = ProfileRegistry(user_home=ops_home)
        prof = reg.get("developer")
        cfg = make_fake_config(ops_home)
        s1 = bake_spec(cfg, prof, str(ops_home))
        s2 = bake_spec(cfg, prof, str(ops_home))
        assert s1 is not None
        assert s2 is s1
        kinds = [
            e["kind"]
            for e in _all_events(ops_home)
            if e["kind"] in ("skills_resolved", "cache_hit", "cache_miss")
        ]
        assert kinds == [
            "skills_resolved",
            "cache_miss",
            "skills_resolved",
            "cache_hit",
        ]

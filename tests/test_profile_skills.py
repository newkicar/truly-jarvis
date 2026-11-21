from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from src import profile_skills as ps
from src.profiles import spec as spec_mod
from src.profiles.schema import ProfileError, namespace_segment, parse_profile


# ---------------------------------------------------------------------------
# helpers (repo discipline: no pytest tmp_path; self-built dirs)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _home(tag: str):
    p = Path(tempfile.gettempdir()) / f"jarvis_profile_skills_{os.getpid()}_{tag}"
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir()
    try:
        yield p
    finally:
        shutil.rmtree(p, ignore_errors=True)


def _write_skill(root, rel: str, *, name: str = "", fm: dict | None = None) -> Path:
    d = Path(root) / rel
    d.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    lines.append(f"name: {name or d.name}")
    lines.append("description: d")
    for k, v in (fm or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("body")
    p = d / "SKILL.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@dataclass
class _FakeConfig:
    model_id: str = "m"


def _dev_profile(**over) -> "ps.AgentProfile":
    return parse_profile({"id": "developer", "name": "Developer", **over})


def _agent_dir(home: Path) -> Path:
    return home / "agents" / "developer" / "skills"


def _common_dir(home: Path) -> Path:
    return home / "skills" / "common"


def _project_dir(home: Path, project_id: str) -> Path:
    return home / "projects" / project_id / "skills"


# ---------------------------------------------------------------------------
# 1. tier precedence + conflicts + routes
# ---------------------------------------------------------------------------

def test_tier_precedence_conflicts_routes():
    with _home("tiers") as home:
        task_dir = home / "taskskills"
        for d in (_common_dir(home), _agent_dir(home), _project_dir(home, "p1"), task_dir):
            _write_skill(d, "dup")
        _write_skill(_common_dir(home), "solo-common")
        _write_skill(_agent_dir(home), "solo-agent")
        _write_skill(_project_dir(home, "p1"), "solo-project")
        _write_skill(task_dir, "solo-task")

        ctx = ps.TaskContext(task_id="t1", skills_dir=task_dir)
        man = ps.resolve("developer", "ws", ctx, profile=_dev_profile(), project_id="p1", user_home_=home)

        assert (man.profile_id, man.project_id, man.task_id) == ("developer", "p1", "t1")

        # winners: 1 dup (task tier) + 4 solo skills
        names = [e.name for e in man.entries]
        assert sorted(names) == ["dup", "solo-agent", "solo-common", "solo-project", "solo-task"]
        dup = next(e for e in man.entries if e.name == "dup")
        assert dup.tier == "task"
        assert dup.fs_path == str(task_dir / "dup" / "SKILL.md")

        # solo-common rides the existing /skills/ vpath but mounts no route
        solo_common = next(e for e in man.entries if e.name == "solo-common")
        assert solo_common.vpath == "/skills/"
        assert "/skills/" not in man.skill_vpaths

        # routes: only the non-common tiers that kept an entry
        assert set(man.skill_vpaths) == {"/agent-skills/", "/project-skills/", "/task-skills/"}
        assert dict(man.skill_routes) == {
            "/agent-skills/": str(_agent_dir(home)),
            "/project-skills/": str(_project_dir(home, "p1")),
            "/task-skills/": str(task_dir),
        }

        # 3 loser conflicts: agent>common, project>agent, task>project
        assert len(man.conflicts) == 3
        by_winner = {c.winner_tier: c for c in man.conflicts}
        assert set(by_winner) == {"agent", "project", "task"}
        assert by_winner["agent"].loser_tier == "common"
        assert by_winner["project"].loser_tier == "agent"
        assert by_winner["task"].loser_tier == "project"
        conflict_excluded = [x for x in man.excluded if x.reason == "conflict"]
        assert sorted(x.tier for x in conflict_excluded) == ["agent", "common", "project"]
        assert all(x.name == "dup" for x in conflict_excluded)


# ---------------------------------------------------------------------------
# 2. same tier same name: later rglob path wins, no cross-tier conflict
# ---------------------------------------------------------------------------

def test_same_tier_same_name_no_conflict():
    with _home("same_tier") as home:
        _write_skill(_agent_dir(home), "aaa", name="dup")
        _write_skill(_agent_dir(home), "zzz", name="dup")
        man = ps.resolve("developer", "ws", user_home_=home)
        assert man.conflicts == ()
        dup = [e for e in man.entries if e.name == "dup"]
        assert len(dup) == 1
        assert dup[0].fs_path == str(_agent_dir(home) / "zzz" / "SKILL.md")


# ---------------------------------------------------------------------------
# 3. include / exclude filters (active profile)
# ---------------------------------------------------------------------------

def test_include_exclude_filters():
    with _home("filters_a") as home:
        _write_skill(_agent_dir(home), "keep")
        _write_skill(_agent_dir(home), "drop")
        prof = _dev_profile(skills={"include": ["keep", "drop"], "exclude": ["drop"]})
        man = ps.resolve("developer", "ws", profile=prof, user_home_=home)
        assert [e.name for e in man.entries] == ["keep"]
        dropped = [x for x in man.excluded if x.reason == "exclude"]
        assert [x.name for x in dropped] == ["drop"]


def test_include_only_drops_rest():
    with _home("filters_b") as home:
        _write_skill(_agent_dir(home), "a")
        _write_skill(_agent_dir(home), "b")
        prof = _dev_profile(skills={"include": ["a"]})
        man = ps.resolve("developer", "ws", profile=prof, user_home_=home)
        assert [e.name for e in man.entries] == ["a"]
        dropped = [x for x in man.excluded if x.reason == "include"]
        assert [x.name for x in dropped] == ["b"]


# ---------------------------------------------------------------------------
# 4/5. filter source: active profile first, legacy fallback
# ---------------------------------------------------------------------------

def test_active_profile_filters_win_over_legacy():
    with _home("active_first") as home:
        _write_skill(_agent_dir(home), "a")
        _write_skill(_agent_dir(home), "b")
        active = _dev_profile(skills={"include": ["a"]})
        legacy = _dev_profile(skills={"include": ["b"]})
        man = ps.resolve("developer", "ws", profile=active, legacy_profile=legacy, user_home_=home)
        assert [e.name for e in man.entries] == ["a"]
        dropped = [x for x in man.excluded if x.reason == "include"]
        assert [x.name for x in dropped] == ["b"]


def test_legacy_profile_filters_fallback():
    with _home("legacy_only") as home:
        _write_skill(_agent_dir(home), "a")
        _write_skill(_agent_dir(home), "b")
        legacy = _dev_profile(skills={"include": ["b"]})
        man = ps.resolve("developer", "ws", profile=None, legacy_profile=legacy, user_home_=home)
        assert [e.name for e in man.entries] == ["b"]
        dropped = [x for x in man.excluded if x.reason == "include"]
        assert [x.name for x in dropped] == ["a"]


# ---------------------------------------------------------------------------
# 6. no task_context -> no task tier
# ---------------------------------------------------------------------------

def test_no_task_context_no_task_tier():
    with _home("no_task") as home:
        task_dir = home / "taskskills"
        _write_skill(task_dir, "taskskill")
        man = ps.resolve("developer", "ws", user_home_=home)
        assert man.entries == ()
        assert "/task-skills/" not in man.skill_vpaths
        assert man.task_id == ""


# ---------------------------------------------------------------------------
# 7. manifest hash stable + content sensitive
# ---------------------------------------------------------------------------

def test_manifest_hash_stable_and_sensitive():
    with _home("hash_stable") as home:
        _write_skill(_agent_dir(home), "s1")
        _write_skill(_agent_dir(home), "s2")
        m1 = ps.resolve("developer", "ws", user_home_=home)
        m2 = ps.resolve("developer", "ws", user_home_=home)
        assert m1.manifest_hash == m2.manifest_hash
        _write_skill(_agent_dir(home), "s2", fm={"note": "changed"})
        m3 = ps.resolve("developer", "ws", user_home_=home)
        assert m3.manifest_hash != m1.manifest_hash


# ---------------------------------------------------------------------------
# 8. _manifest_hash direct verification against the documented payload
# ---------------------------------------------------------------------------

def test_manifest_hash_direct():
    entries = [
        ps.SkillEntry(name="a", tier="agent", fs_path="/x/a/SKILL.md", content_hash="h1", vpath="/agent-skills/")
    ]
    conflicts = [
        ps.SkillConflict(name="b", winner_tier="task", winner_fs_path="/t/b", loser_tier="agent", loser_fs_path="/a/b")
    ]
    excluded = [ps.ExcludedSkill(name="b", tier="agent", reason="conflict")]
    routes = [("/agent-skills/", "/a"), ("/task-skills/", "/t")]
    vpaths = ("/agent-skills/", "/task-skills/")
    payload = {
        "profile_id": "p",
        "project_id": "pj",
        "task_id": "t",
        "entries": [dict(e.__dict__) for e in entries],
        "conflicts": [dict(c.__dict__) for c in conflicts],
        "excluded": [dict(x.__dict__) for x in excluded],
        "skill_routes": [list(r) for r in routes],
        "skill_vpaths": list(vpaths),
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert ps._manifest_hash("p", "pj", "t", entries, conflicts, excluded, routes, vpaths) == expected
    # resolve() builds the hash through the same payload shape
    with _home("hash_direct") as home:
        man = ps.resolve("p", "ws", project_id="pj", user_home_=home)
        payload2 = man.to_dict()
        expected2 = hashlib.sha256(
            json.dumps(
                {
                    "profile_id": payload2["profile_id"],
                    "project_id": payload2["project_id"],
                    "task_id": payload2["task_id"],
                    "entries": payload2["entries"],
                    "conflicts": payload2["conflicts"],
                    "excluded": payload2["excluded"],
                    "skill_routes": payload2["skill_routes"],
                    "skill_vpaths": payload2["skill_vpaths"],
                },
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert man.manifest_hash == expected2


# ---------------------------------------------------------------------------
# 9. resolve is purely read-only
# ---------------------------------------------------------------------------

def test_resolve_read_only():
    with _home("read_only") as home:
        man = ps.resolve("developer", "ws", project_id="p1", user_home_=home)
        assert man.entries == ()
        assert man.skill_vpaths == ()
        for sub in ("agents", "projects", "skills"):
            assert not (home / sub).exists(), sub


# ---------------------------------------------------------------------------
# 10. namespace normalization: 'agents/<id>', default, backslash spelling
# ---------------------------------------------------------------------------

def test_namespace_normalization_same_dir():
    with _home("ns_norm") as home:
        _write_skill(_agent_dir(home), "alpha")
        variants = [
            _dev_profile(memory={"namespace": "agents/developer"}),
            _dev_profile(),  # default namespace = profile id
            _dev_profile(memory={"namespace": "agents\\developer"}),
        ]
        hashes = set()
        entries_sets = set()
        for prof in variants:
            man = ps.resolve("developer", "ws", profile=prof, user_home_=home)
            assert [e.name for e in man.entries] == ["alpha"]
            assert man.entries[0].fs_path == str(_agent_dir(home) / "alpha" / "SKILL.md")
            hashes.add(man.manifest_hash)
            entries_sets.add(tuple(e.fs_path for e in man.entries))
        assert len(hashes) == 1
        assert len(entries_sets) == 1


# ---------------------------------------------------------------------------
# 11. namespace fail-closed at parse time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["..", "a/b", "agents/", ".", "a/../b"])
def test_bad_namespace_fails_closed(bad):
    with pytest.raises(ProfileError):
        parse_profile({"id": "developer", "memory": {"namespace": bad}})


# ---------------------------------------------------------------------------
# 12. namespace_segment unit behaviour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("ns", "pid", "expected"),
    [
        ("developer", "developer", "developer"),
        ("agents/developer", "developer", "developer"),
        ("agents\\developer", "developer", "developer"),
        ("  developer  ", "developer", "developer"),
        ("", "fallback", "fallback"),
        (None, "fallback", "fallback"),
    ],
)
def test_namespace_segment(ns, pid, expected):
    assert namespace_segment(ns, pid) == expected


# ---------------------------------------------------------------------------
# 13. scan_manual_only
# ---------------------------------------------------------------------------

def test_scan_manual_only():
    with _home("manual") as home:
        d = _common_dir(home)
        _write_skill(d, "m1", fm={"disable-model-invocation": "true"})
        _write_skill(d, "m2", fm={"disable-model-invocation": "yes"})
        _write_skill(d, "m3", fm={"disable-model-invocation": "1"})
        _write_skill(d, "m4", fm={"disable-model-invocation": "True"})
        _write_skill(d, "free", fm={"description": "no flag"})
        _write_skill(d, "off", fm={"disable-model-invocation": "false"})
        assert ps.scan_manual_only([d, str(home / "nonexistent")]) == {"m1", "m2", "m3", "m4"}
        assert ps.scan_manual_only([home / "does-not-exist"]) == set()


# ---------------------------------------------------------------------------
# 14. bake_spec wiring + JARVIS_HOME redirect + cache
# ---------------------------------------------------------------------------

def test_bake_spec_wiring(monkeypatch):
    with _home("bake") as home:
        _write_skill(_agent_dir(home), "agent-skill")
        _write_skill(_project_dir(home, "p1"), "project-skill")
        monkeypatch.setenv("JARVIS_HOME", str(home))
        spec_mod._reset_bake_cache()
        try:
            prof = _dev_profile()
            cfg = _FakeConfig()
            spec = spec_mod.bake_spec(cfg, prof, "ws", project_id="p1", session_id="s1")
            assert spec is not None

            man = ps.resolve(prof.id, "ws", project_id="p1", profile=prof, user_home_=home)
            assert spec.skill_vpaths == man.skill_vpaths
            assert spec.skill_routes == man.skill_routes
            assert spec.skill_manifest_hash == man.manifest_hash
            assert len(spec.skill_manifest_hash) == 64
            assert all(c in "0123456789abcdef" for c in spec.skill_manifest_hash)

            # memory dirs follow the JARVIS_HOME-redirected user home
            assert spec.memory_dirs[0] == (home / "agents" / "developer" / "memory").as_posix()
            assert spec.memory_dirs[1] == (home / "projects" / "p1" / "memory").as_posix()

            # cached: same params -> same object, hits +1
            stats_before = spec_mod.bake_cache_stats()["hits"]
            spec2 = spec_mod.bake_spec(cfg, prof, "ws", project_id="p1", session_id="s1")
            assert spec2 is spec
            assert spec_mod.bake_cache_stats()["hits"] == stats_before + 1

            # None profile -> None
            assert spec_mod.bake_spec(cfg, None, "ws") is None
        finally:
            spec_mod._reset_bake_cache()
            monkeypatch.delenv("JARVIS_HOME", raising=False)


# ---------------------------------------------------------------------------
# 15. NameError regression: positional AgentProfile + bare id both work
# ---------------------------------------------------------------------------

def test_resolve_accepts_positional_profile_nameerror_regression():
    with _home("nameerror") as home:
        _write_skill(_agent_dir(home), "alpha")
        prof = _dev_profile()
        man_pos = ps.resolve(prof, "ws", user_home_=home)
        man_id = ps.resolve("developer", "ws", user_home_=home)
        assert man_pos.entries == man_id.entries
        assert man_pos.manifest_hash == man_id.manifest_hash
        assert [e.name for e in man_pos.entries] == ["alpha"]

"""Tests for src/profiles/schema.py: parsing, validation, merge, narrowing, hashing."""
from __future__ import annotations

import dataclasses
import logging

import pytest

from src.profiles.schema import (
    AgentProfile,
    ProfileError,
    check_security_narrowing,
    deep_merge,
    parse_profile,
    profile_hash,
    validate_unique_ids,
)

LOGGER = "src.profiles.schema"


def _p(**over) -> dict:
    d = {"id": "x"}
    d.update(over)
    return d


class TestParseDefaults:
    def test_minimal_defaults(self):
        p = parse_profile(_p())
        assert p.id == "x"
        assert p.name == ""
        assert p.description == ""
        assert p.schema_version == 1
        assert p.identity.role == ""
        assert p.identity.mission == ""
        assert p.identity.principles == ()
        assert p.runtime.engine == "deepagents"
        assert p.runtime.model == ""
        assert p.instructions.file == "AGENTS.md"
        assert p.skills.include == ()
        assert p.skills.exclude == ()
        assert p.memory.enabled is True
        assert p.memory.namespace == "x"  # defaults to id
        assert p.memory.recall.enabled is True
        assert p.memory.recall.max_items == 20
        assert p.memory.write.mode == "propose"
        assert p.memory.write.auto_promote is False
        assert p.tools.allow == ()
        assert p.tools.deny == ()
        assert p.permissions.filesystem.workspace_only is False
        assert p.permissions.approvals.execute == "required"
        assert p.permissions.approvals.external_network == "required"
        assert p.permissions.approvals.destructive_operations == "required"
        assert p.permissions.can_delegate is False
        assert p.session.checkpoint_enabled is True
        assert p.session.checkpoint_policy == "thread"
        assert p.lifecycle.persistent_profile is True
        assert p.lifecycle.worker_default is False
        assert p.profile_version == 1
        assert p.is_legacy is False
        assert p.source_path == ""

    def test_source_path_is_registry_metadata(self):
        p = parse_profile(_p(), source_path="/some/agent.yaml")
        assert p.source_path == "/some/agent.yaml"

    def test_full_fields_round_trip(self):
        p = parse_profile(_p(
            name="Sec",
            description="a secretary",
            schema_version=1,
            identity={"role": "sec", "mission": "m", "principles": ["p1", "p2"]},
            runtime={"engine": "deepagents", "model": "mimo"},
            instructions={"file": "NOTES.md"},
            skills={"include": ["a", "b"], "exclude": ["c"]},
            memory={
                "enabled": True,
                "namespace": "sec",
                "recall": {"enabled": False, "max_items": 5},
                "write": {"mode": "auto", "auto_promote": True},
            },
            tools={"allow": ["grep"], "deny": ["execute"]},
            permissions={
                "filesystem": {"workspace_only": True},
                "approvals": {
                    "execute": "optional",
                    "external_network": "required",
                    "destructive_operations": "optional",
                },
                "can_delegate": True,
            },
            session={"checkpoint_enabled": False, "checkpoint_policy": "task"},
            lifecycle={"persistent_profile": False, "worker_default": True},
        ))
        assert p.name == "Sec"
        assert p.identity.principles == ("p1", "p2")
        assert p.runtime.model == "mimo"
        assert p.instructions.file == "NOTES.md"
        assert p.skills.include == ("a", "b")
        assert p.skills.exclude == ("c",)
        assert p.memory.recall.max_items == 5
        assert p.memory.write.mode == "auto"
        assert p.tools.allow == ("grep",)
        assert p.permissions.filesystem.workspace_only is True
        assert p.permissions.approvals.execute == "optional"
        assert p.permissions.can_delegate is True
        assert p.session.checkpoint_policy == "task"
        assert p.lifecycle.worker_default is True


class TestParseCoercions:
    def test_int_id_coerced_to_str(self):
        assert parse_profile({"id": 42}).id == "42"

    def test_bool_coercions(self):
        p = parse_profile(_p(permissions={"can_delegate": 1}))
        assert p.permissions.can_delegate is True
        p = parse_profile(_p(permissions={"can_delegate": "false"}))
        assert p.permissions.can_delegate is False
        p = parse_profile(_p(memory={"recall": {"enabled": "true"}}))
        assert p.memory.recall.enabled is True

    def test_id_whitespace_stripped(self):
        assert parse_profile({"id": "  x  "}).id == "x"


class TestParseErrors:
    def test_non_mapping_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(["id", "x"])
        with pytest.raises(ProfileError):
            parse_profile("x")

    def test_missing_id_raises(self):
        with pytest.raises(ProfileError):
            parse_profile({})

    def test_empty_id_raises(self):
        with pytest.raises(ProfileError):
            parse_profile({"id": "   "})

    def test_null_id_raises(self):
        with pytest.raises(ProfileError):
            parse_profile({"id": None})

    @pytest.mark.parametrize("sv", [0, "1", True, -1, 1.5])
    def test_bad_schema_version_raises(self, sv):
        with pytest.raises(ProfileError):
            parse_profile(_p(schema_version=sv))

    def test_null_schema_version_defaults(self):
        assert parse_profile(_p(schema_version=None)).schema_version == 1

    def test_role_non_string_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(identity={"role": 7}))

    def test_max_items_string_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(memory={"recall": {"max_items": "20"}}))

    def test_max_items_bool_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(memory={"recall": {"max_items": True}}))

    def test_bad_approval_value_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(permissions={"approvals": {"execute": "maybe"}}))

    def test_bad_bool_string_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(permissions={"can_delegate": "yes"}))

    def test_section_non_dict_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(permissions="all"))

    def test_skills_include_non_string_item_raises(self):
        with pytest.raises(ProfileError):
            parse_profile(_p(skills={"include": [1, 2]}))

    @pytest.mark.parametrize("where", [
        {"permissions": {"sneaky": True}},
        {"permissions": {"approvals": {"bogus": "optional"}}},
        {"permissions": {"filesystem": {"strict": True}}},
    ])
    def test_unknown_security_key_fails_closed(self, where):
        with pytest.raises(ProfileError, match="unknown security key"):
            parse_profile(_p(**where))


class TestParseTolerance:
    def test_unknown_top_level_key_tolerated(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            p = parse_profile(_p(custom={"a": 1}))
        assert p.id == "x"
        assert any("unknown top-level" in r.getMessage() for r in caplog.records)

    def test_unknown_nested_key_tolerated(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            p = parse_profile(_p(identity={"role": "sec", "tone": "calm"}))
        assert p.identity.role == "sec"
        assert any("tone" in r.getMessage() for r in caplog.records)

    def test_unverified_skill_reference_tolerated(self, caplog):
        with caplog.at_level(logging.INFO, logger=LOGGER):
            p = parse_profile(_p(skills={"include": ["does-not-exist"]}))
        assert p.skills.include == ("does-not-exist",)
        assert any("not verified" in r.getMessage() for r in caplog.records)


class TestUniqueIds:
    def test_duplicate_raises(self):
        with pytest.raises(ProfileError, match="duplicate"):
            validate_unique_ids([AgentProfile(id="a"), AgentProfile(id="a")])

    def test_unique_ok(self):
        validate_unique_ids([AgentProfile(id="a"), AgentProfile(id="b")])


class TestProfileHash:
    def test_deterministic(self):
        p = parse_profile(_p(name="n"))
        assert profile_hash(p, "md") == profile_hash(p, "md")

    def test_field_sensitivity(self):
        p = parse_profile(_p(name="n"))
        assert profile_hash(p) != profile_hash(dataclasses.replace(p, name="other"))

    def test_agents_md_sensitivity(self):
        p = parse_profile(_p())
        assert profile_hash(p, "A") != profile_hash(p, "B")

    def test_metadata_excluded(self):
        p = parse_profile(_p())
        alt = dataclasses.replace(p, is_legacy=True, source_path="/elsewhere")
        assert profile_hash(p) == profile_hash(alt)


class TestDeepMerge:
    def test_recursive_nested(self):
        base = {"a": {"b": 1, "c": 2}}
        out = deep_merge(base, {"a": {"b": 9}})
        assert out == {"a": {"b": 9, "c": 2}}

    def test_list_override_replaces_not_concatenates(self):
        assert deep_merge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}

    def test_none_override_absent(self):
        assert deep_merge({"a": 1}, None) == {"a": 1}
        assert deep_merge({"a": 1, "b": 2}, {"a": None}) == {"a": 1, "b": 2}

    def test_scalar_override_wins(self):
        assert deep_merge(1, 2) == 2
        assert deep_merge(None, 5) == 5

    def test_inputs_not_mutated(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        deep_merge(base, override)
        assert base == {"a": {"b": 1}}
        assert override == {"a": {"c": 2}}


class TestSecurityNarrowing:
    @pytest.mark.parametrize("base, override", [
        # approval loosening: required(default) -> optional
        ({}, {"permissions": {"approvals": {"execute": "optional"}}}),
        ({}, {"permissions": {"approvals": {"external_network": "optional"}}}),
        ({}, {"permissions": {"approvals": {"destructive_operations": "optional"}}}),
        ({"permissions": {"approvals": {"execute": "required"}}},
         {"permissions": {"approvals": {"execute": "optional"}}}),
        # workspace_only True -> False
        ({"permissions": {"filesystem": {"workspace_only": True}}},
         {"permissions": {"filesystem": {"workspace_only": False}}}),
        # can_delegate False(default) -> True
        ({}, {"permissions": {"can_delegate": True}}),
        ({"permissions": {"can_delegate": False}},
         {"permissions": {"can_delegate": True}}),
    ])
    def test_loosening_rejected(self, base, override):
        with pytest.raises(ProfileError, match="loosening"):
            check_security_narrowing(base, override)

    @pytest.mark.parametrize("base, override", [
        # no security keys at all
        ({}, {}),
        ({}, {"name": "n"}),
        # tightening / equal values are legal
        ({"permissions": {"approvals": {"execute": "optional"}}},
         {"permissions": {"approvals": {"execute": "required"}}}),
        ({"permissions": {"approvals": {"execute": "required"}}},
         {"permissions": {"approvals": {"execute": "required"}}}),
        ({}, {"permissions": {"filesystem": {"workspace_only": True}}}),
        ({"permissions": {"filesystem": {"workspace_only": True}}},
         {"permissions": {"filesystem": {"workspace_only": True}}}),
        ({"permissions": {"can_delegate": True}},
         {"permissions": {"can_delegate": False}}),
        # keys absent in override are skipped, not loosening
        ({"permissions": {"approvals": {"execute": "optional"}}},
         {"permissions": {"approvals": {"external_network": "required"}}}),
    ])
    def test_tightening_allowed(self, base, override):
        check_security_narrowing(base, override)
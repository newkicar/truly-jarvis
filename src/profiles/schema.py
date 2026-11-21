"""Agent Profile schema: dataclass, parsing, validation, hashing.

All values are strict: unknown security fields raise ProfileError (fail-closed).
Unknown non-security fields are tolerated (forward-compat) with a log.info.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
APPROVAL_LEVELS = ("optional", "required")
DEFAULT_APPROVAL = "required"
DEFAULTS: dict[str, Any] = {
    "workspace_only": False,
    "can_delegate": False,
    "execute": "required",
    "external_network": "required",
    "destructive_operations": "required",
}
_APPROVAL_RANK = {"optional": 0, "required": 1}

# Keys under these sections: unknown = ProfileError (fail-closed security)
_SECURITY_SECTIONS = frozenset({"permissions", "filesystem", "approvals"})
_ALLOWED_SECURITY_KEYS: dict[str, frozenset] = {
    "permissions": frozenset({"filesystem", "approvals", "can_delegate"}),
    "filesystem": frozenset({"workspace_only"}),
    "approvals": frozenset({"execute", "external_network", "destructive_operations"}),
}


class ProfileError(ValueError):
    """Raised when a profile YAML violates schema or security constraints."""


# ---------------------------------------------------------------------------
# Helper coercers
# ---------------------------------------------------------------------------

def _as_dict(v: Any, where: str) -> dict:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ProfileError(f"{where}: expected mapping, got {type(v).__name__}")
    return v


def _as_str(v: Any, where: str, default: str = "") -> str:
    if v is None:
        return default
    if not isinstance(v, str):
        raise ProfileError(f"{where}: expected string, got {type(v).__name__}")
    return v


def _as_bool(v: Any, where: str, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    raise ProfileError(f"{where}: expected boolean, got {v!r}")


def _as_str_tuple(v: Any, where: str) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, (list, tuple)):
        return tuple(_as_str(item, f"{where}[{i}]") for i, item in enumerate(v))
    raise ProfileError(f"{where}: expected list/tuple, got {type(v).__name__}")


def _approval_value(v: Any, where: str, default: str = DEFAULT_APPROVAL) -> str:
    if v is None:
        return default
    if v not in APPROVAL_LEVELS:
        raise ProfileError(f"{where}: approval must be one of {APPROVAL_LEVELS}, got {v!r}")
    return v


def _tolerate_unknown_keys(d: dict, section: str, allowed: frozenset, where: str) -> None:
    """Log unknown keys in non-security sections (forward-compatible)."""
    unknown = set(d.keys()) - set(allowed)
    if unknown:
        log.info("%s: unknown key(s) %s tolerated (forward-compat)", where, sorted(unknown))


def _reject_unknown_security_keys(d: dict, section: str, where: str) -> None:
    """Fail-closed: unknown keys in security sections raise ProfileError."""
    allowed = _ALLOWED_SECURITY_KEYS.get(section, frozenset())
    unknown = set(d.keys()) - set(allowed)
    if unknown:
        raise ProfileError(
            f"{where}: unknown security key(s) {sorted(unknown)} in '{section}' "
            f"(fail-closed; remove or update schema)"
        )


# ---------------------------------------------------------------------------
# Nested dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    role: str = ""
    mission: str = ""
    principles: tuple[str, ...] = ()


@dataclass(frozen=True)
class Runtime:
    engine: str = "deepagents"
    model: str = ""


@dataclass(frozen=True)
class Instructions:
    file: str = "AGENTS.md"


@dataclass(frozen=True)
class Skills:
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryRecall:
    enabled: bool = True
    max_items: int = 20


@dataclass(frozen=True)
class MemoryWrite:
    mode: str = "propose"
    auto_promote: bool = False


@dataclass(frozen=True)
class Memory:
    enabled: bool = True
    namespace: str = ""
    recall: MemoryRecall = field(default_factory=MemoryRecall)
    write: MemoryWrite = field(default_factory=MemoryWrite)


@dataclass(frozen=True)
class Tools:
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()


@dataclass(frozen=True)
class Filesystem:
    workspace_only: bool = False


@dataclass(frozen=True)
class Approvals:
    execute: str = "required"
    external_network: str = "required"
    destructive_operations: str = "required"


@dataclass(frozen=True)
class Permissions:
    filesystem: Filesystem = field(default_factory=Filesystem)
    approvals: Approvals = field(default_factory=Approvals)
    can_delegate: bool = False


@dataclass(frozen=True)
class Session:
    checkpoint_enabled: bool = True
    checkpoint_policy: str = "thread"


@dataclass(frozen=True)
class Lifecycle:
    persistent_profile: bool = True
    worker_default: bool = False


@dataclass(frozen=True)
class AgentProfile:
    """Top-level Agent Profile (parsed from agent.yaml + AGENTS.md)."""

    schema_version: int = SCHEMA_VERSION
    id: str = ""
    name: str = ""
    description: str = ""
    identity: Identity = field(default_factory=Identity)
    runtime: Runtime = field(default_factory=Runtime)
    instructions: Instructions = field(default_factory=Instructions)
    skills: Skills = field(default_factory=Skills)
    memory: Memory = field(default_factory=Memory)
    tools: Tools = field(default_factory=Tools)
    permissions: Permissions = field(default_factory=Permissions)
    session: Session = field(default_factory=Session)
    lifecycle: Lifecycle = field(default_factory=Lifecycle)
    # Metadata (not from YAML, set by registry)
    profile_version: int = 1
    is_legacy: bool = False
    source_path: str = ""


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

KNOWN_TOP_LEVEL = frozenset({
    "schema_version", "id", "name", "description",
    "identity", "runtime", "instructions", "skills", "memory",
    "tools", "permissions", "session", "lifecycle",
})
_TOLERATED_SECTIONS = frozenset({
    "identity", "runtime", "instructions", "skills", "memory", "tools", "session", "lifecycle",
})


def parse_profile(d: dict, *, source_path: str = "") -> AgentProfile:
    """Parse and validate a raw dict into an AgentProfile.

    Raises ProfileError on invalid structure or security violations.
    """
    if not isinstance(d, dict):
        raise ProfileError(f"profile must be a mapping, got {type(d).__name__}")

    # --- id ---
    raw_id = d.get("id")
    if raw_id is None or (isinstance(raw_id, str) and not raw_id.strip()):
        raise ProfileError("profile.id is required and non-empty")
    pid = str(raw_id) if isinstance(raw_id, (str, int)) else raw_id
    if not isinstance(pid, str) or not pid.strip():
        raise ProfileError(f"profile.id must be a non-empty string, got {raw_id!r}")
    pid = pid.strip()

    # --- schema_version ---
    sv = d.get("schema_version", SCHEMA_VERSION)
    if sv is None:
        sv = SCHEMA_VERSION
    if isinstance(sv, bool) or not isinstance(sv, int) or sv < 1:
        raise ProfileError(f"profile.schema_version must be int >= 1, got {sv!r}")

    # --- unknown top-level keys ---
    unknown = set(d.keys()) - set(KNOWN_TOP_LEVEL)
    if unknown:
        log.info("profile '%s': unknown top-level key(s) %s tolerated", pid, sorted(unknown))

    # --- name / description ---
    name = _as_str(d.get("name"), "profile.name")
    description = _as_str(d.get("description"), "profile.description")

    # --- identity ---
    identity_raw = _as_dict(d.get("identity"), "identity")
    _tolerate_unknown_keys(identity_raw, "identity", frozenset({"role", "mission", "principles"}), "identity")
    identity = Identity(
        role=_as_str(identity_raw.get("role"), "identity.role"),
        mission=_as_str(identity_raw.get("mission"), "identity.mission"),
        principles=_as_str_tuple(identity_raw.get("principles"), "identity.principles"),
    )

    # --- runtime ---
    runtime_raw = _as_dict(d.get("runtime"), "runtime")
    _tolerate_unknown_keys(runtime_raw, "runtime", frozenset({"engine", "model"}), "runtime")
    runtime = Runtime(
        engine=_as_str(runtime_raw.get("engine"), "runtime.engine", "deepagents"),
        model=_as_str(runtime_raw.get("model"), "runtime.model"),
    )

    # --- instructions ---
    instr_raw = _as_dict(d.get("instructions"), "instructions")
    _tolerate_unknown_keys(instr_raw, "instructions", frozenset({"file"}), "instructions")
    instructions = Instructions(file=_as_str(instr_raw.get("file"), "instructions.file", "AGENTS.md"))

    # --- skills ---
    skills_raw = _as_dict(d.get("skills"), "skills")
    _tolerate_unknown_keys(skills_raw, "skills", frozenset({"include", "exclude"}), "skills")
    skills_include = _as_str_tuple(skills_raw.get("include"), "skills.include")
    skills_exclude = _as_str_tuple(skills_raw.get("exclude"), "skills.exclude")
    if skills_include or skills_exclude:
        log.info("skills references not verified at parse time (include=%s, exclude=%s)", skills_include, skills_exclude)
    skills = Skills(include=skills_include, exclude=skills_exclude)

    # --- memory ---
    mem_raw = _as_dict(d.get("memory"), "memory")
    _tolerate_unknown_keys(mem_raw, "memory", frozenset({"enabled", "namespace", "recall", "write"}), "memory")
    recall_raw = _as_dict(mem_raw.get("recall"), "memory.recall")
    _tolerate_unknown_keys(recall_raw, "recall", frozenset({"enabled", "max_items"}), "memory.recall")
    recall = MemoryRecall(
        enabled=_as_bool(recall_raw.get("enabled"), "memory.recall.enabled", True),
        max_items=_as_int(recall_raw.get("max_items"), "memory.recall.max_items", 20),
    )
    write_raw = _as_dict(mem_raw.get("write"), "memory.write")
    _tolerate_unknown_keys(write_raw, "write", frozenset({"mode", "auto_promote"}), "memory.write")
    write = MemoryWrite(
        mode=_as_str(write_raw.get("mode"), "memory.write.mode", "propose"),
        auto_promote=_as_bool(write_raw.get("auto_promote"), "memory.write.auto_promote", False),
    )
    memory = Memory(
        enabled=_as_bool(mem_raw.get("enabled"), "memory.enabled", True),
        namespace=_as_str(mem_raw.get("namespace"), "memory.namespace", pid),
        recall=recall,
        write=write,
    )

    # --- tools ---
    tools_raw = _as_dict(d.get("tools"), "tools")
    _tolerate_unknown_keys(tools_raw, "tools", frozenset({"allow", "deny"}), "tools")
    tools = Tools(
        allow=_as_str_tuple(tools_raw.get("allow"), "tools.allow"),
        deny=_as_str_tuple(tools_raw.get("deny"), "tools.deny"),
    )

    # --- permissions (SECURITY: fail-closed on unknown keys) ---
    perm_raw = _as_dict(d.get("permissions"), "permissions")
    _reject_unknown_security_keys(perm_raw, "permissions", "permissions")
    fs_raw = _as_dict(perm_raw.get("filesystem"), "permissions.filesystem")
    _reject_unknown_security_keys(fs_raw, "filesystem", "permissions.filesystem")
    approvals_raw = _as_dict(perm_raw.get("approvals"), "permissions.approvals")
    _reject_unknown_security_keys(approvals_raw, "approvals", "permissions.approvals")
    filesystem = Filesystem(
        workspace_only=_as_bool(fs_raw.get("workspace_only"), "permissions.filesystem.workspace_only", DEFAULTS["workspace_only"]),
    )
    approvals = Approvals(
        execute=_approval_value(approvals_raw.get("execute"), "permissions.approvals.execute"),
        external_network=_approval_value(approvals_raw.get("external_network"), "permissions.approvals.external_network"),
        destructive_operations=_approval_value(approvals_raw.get("destructive_operations"), "permissions.approvals.destructive_operations"),
    )
    can_delegate = _as_bool(perm_raw.get("can_delegate"), "permissions.can_delegate", DEFAULTS["can_delegate"])
    permissions = Permissions(filesystem=filesystem, approvals=approvals, can_delegate=can_delegate)

    # --- session ---
    sess_raw = _as_dict(d.get("session"), "session")
    _tolerate_unknown_keys(sess_raw, "session", frozenset({"checkpoint_enabled", "checkpoint_policy"}), "session")
    session = Session(
        checkpoint_enabled=_as_bool(sess_raw.get("checkpoint_enabled"), "session.checkpoint_enabled", True),
        checkpoint_policy=_as_str(sess_raw.get("checkpoint_policy"), "session.checkpoint_policy", "thread"),
    )

    # --- lifecycle ---
    life_raw = _as_dict(d.get("lifecycle"), "lifecycle")
    _tolerate_unknown_keys(life_raw, "lifecycle", frozenset({"persistent_profile", "worker_default"}), "lifecycle")
    lifecycle = Lifecycle(
        persistent_profile=_as_bool(life_raw.get("persistent_profile"), "lifecycle.persistent_profile", True),
        worker_default=_as_bool(life_raw.get("worker_default"), "lifecycle.worker_default", False),
    )

    return AgentProfile(
        schema_version=sv,
        id=pid,
        name=name,
        description=description,
        identity=identity,
        runtime=runtime,
        instructions=instructions,
        skills=skills,
        memory=memory,
        tools=tools,
        permissions=permissions,
        session=session,
        lifecycle=lifecycle,
        source_path=source_path,
    )


def _as_int(v: Any, where: str, default: int) -> int:
    if v is None:
        return default
    if isinstance(v, bool):
        raise ProfileError(f"{where}: expected int, got bool")
    if isinstance(v, int):
        return v
    raise ProfileError(f"{where}: expected int, got {type(v).__name__}")


# ---------------------------------------------------------------------------
# Merge & security narrowing
# ---------------------------------------------------------------------------

def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge base with override. None override = absent (no change)."""
    if override is None:
        return base
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = deep_merge(base.get(key), value)
        return out
    # Non-dict: override wins entirely
    return override


def check_security_narrowing(base_raw: dict, override_raw: dict) -> None:
    """Reject security loosening: high layer may only tighten, never loosen.

    - approval: optional -> required is tightening (allowed); required -> optional is loosening (rejected)
    - workspace_only: False -> True is tightening; True -> False is loosening
    - can_delegate: False -> True is loosening (rejected); True -> False is tightening
    """
    def _leaf(base_dict, override_dict, path):
        base_val = base_dict
        for p in path:
            base_val = base_val.get(p) if isinstance(base_val, dict) else None
            if base_val is None:
                break
        override_val = override_dict
        for p in path:
            override_val = override_val.get(p) if isinstance(override_val, dict) else None
            if override_val is None:
                break
        return base_val, override_val

    # approvals: check each leaf
    for key in ("execute", "external_network", "destructive_operations"):
        path = ("approvals", key)
        base_leaf, override_leaf = _leaf(
            _as_dict((base_raw or {}).get("permissions"), f"base.permissions"),
            _as_dict((override_raw or {}).get("permissions"), f"override.permissions"),
            path,
        )
        # Resolve effective base: if missing, use default
        if base_leaf is None:
            base_leaf = DEFAULTS[key]
        if override_leaf is None:
            continue  # not in override, skip
        base_norm = _approval_value(base_leaf, f"base.permissions.{key}")
        override_norm = _approval_value(override_leaf, f"override.permissions.{key}")
        if _APPROVAL_RANK[override_norm] < _APPROVAL_RANK[base_norm]:
            raise ProfileError(
                f"security loosening rejected: permissions.approvals.{key} "
                f"from '{base_norm}' to '{override_norm}' (high layer may only tighten)"
            )

    # filesystem.workspace_only
    base_fs = _as_dict((base_raw or {}).get("permissions"), "base.permissions").get("filesystem") or {}
    override_fs = _as_dict((override_raw or {}).get("permissions"), "override.permissions").get("filesystem") or {}
    base_wo = _as_bool(base_fs.get("workspace_only"), "base.permissions.filesystem.workspace_only", DEFAULTS["workspace_only"])
    override_wo = override_fs.get("workspace_only")
    if override_wo is not None:
        override_wo = _as_bool(override_wo, "override.permissions.filesystem.workspace_only", DEFAULTS["workspace_only"])
        if base_wo and not override_wo:
            raise ProfileError(
                "security loosening rejected: permissions.filesystem.workspace_only "
                "from True to False (high layer may only tighten)"
            )

    # can_delegate
    base_cd = _as_bool(
        _as_dict((base_raw or {}).get("permissions"), "base.permissions").get("can_delegate"),
        "base.permissions.can_delegate", DEFAULTS["can_delegate"],
    )
    override_cd_raw = _as_dict((override_raw or {}).get("permissions"), "override.permissions").get("can_delegate")
    if override_cd_raw is not None:
        override_cd = _as_bool(override_cd_raw, "override.permissions.can_delegate", DEFAULTS["can_delegate"])
        if not base_cd and override_cd:
            raise ProfileError(
                "security loosening rejected: permissions.can_delegate "
                "from False to True (high layer may only tighten)"
            )


# ---------------------------------------------------------------------------
# Uniqueness & hashing
# ---------------------------------------------------------------------------

def validate_unique_ids(profiles: list[AgentProfile]) -> None:
    """Raise ProfileError if any two profiles share the same id."""
    seen: dict[str, int] = {}
    for p in profiles:
        if p.id in seen:
            raise ProfileError(f"duplicate profile id: '{p.id}' (index {seen[p.id]} and {len(seen)})")
        seen[p.id] = len(seen)


def profile_hash(profile: AgentProfile, agents_md_text: str = "") -> str:
    """Compute sha256 of canonical profile fields + AGENTS.md text."""
    d = dataclasses.asdict(profile)
    # Remove non-content metadata
    d.pop("is_legacy", None)
    d.pop("source_path", None)
    # Recursively prune empty values
    def prune(obj):
        if isinstance(obj, dict):
            return {k: prune(v) for k, v in obj.items() if v not in (None, "", [], {})}
        if isinstance(obj, list):
            return [prune(item) for item in obj]
        return obj
    canonical = prune(d)
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((payload + "\x00" + agents_md_text).encode("utf-8")).hexdigest()
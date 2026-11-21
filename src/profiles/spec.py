"""Bake a parsed AgentProfile into the frozen runtime spec consumed by build_agent.

Ticket 02 of .scratch/agent-profile/. Pure and side-effect free: given a
parsed AgentProfile plus the runtime Config, produce a ProfileSpec carrying
the exact model id, prompt suffix, memory directories, skill route
placeholders (filled in ticket 03), tool allow/deny lists, extra permission
rules and the observability snapshot (ticket 07).

bake_spec returns None when profile is None so callers can gate the
profile path with a single truthiness check and keep the default path
byte-identical.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from dataclasses import dataclass

from src.profiles.schema import AgentProfile, profile_hash, namespace_segment

#: Appended to the system prompt whenever a profile is active. The note
#: states the precedence contract: profile text wins over the base prompt
#: on conflict, but runtime security (HITL permissions, vault guard, ...)
#: is enforced in code, never in prompt text.
PROFILE_CONFLICT_NOTE = (
    "Profile instructions override the base prompt on conflict; "
    "security is enforced by the runtime, not by prompt text."
)

_DESTRUCTIVE_TOOLS = ("write_file", "edit_file", "delete")
_EXTERNAL_NETWORK_TOOLS = ("quick_search", "search", "deep_search")


def _runtime_version() -> str:
    try:
        return importlib.metadata.version("jarvis")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


@dataclass(frozen=True)
class ProfileSnapshot:
    """Immutable observability record attached to the compiled agent.

    Ticket 07 exposes these fields as response metadata for runs.
    profile_version is the string form of the profile schema version.
    """

    profile_id: str
    profile_version: str
    profile_hash: str
    runtime_version: str
    engine: str
    task_id: str
    session_id: str
    workspace: str

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "runtime_version": self.runtime_version,
            "engine": self.engine,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "workspace": self.workspace,
        }
@dataclass(frozen=True)
class ProfileSpec:
    """Everything build_agent needs to switch the default path to a profile.

    memory_dirs are POSIX-style strings; missing directories are skipped by
    the caller. skill_routes is (virtual_prefix, filesystem_path) pairs and
    ticket 03 resolves the tier manifest (common < agent < project < task);
    skill_routes/skill_vpaths/skill_manifest_hash carry its real values.
    """

    profile_id: str
    profile_version: int
    profile_hash: str
    model_id: str
    prompt_suffix: str
    memory_dirs: tuple[str, ...]
    skill_routes: tuple[tuple[str, str], ...]
    skill_vpaths: tuple[str, ...]
    skill_manifest_hash: str
    tool_allow: tuple[str, ...]
    tool_deny: tuple[str, ...]
    permission_extra_rules: dict[str, str]
    checkpoint_enabled: bool
    checkpoint_policy: str
    snapshot: ProfileSnapshot


def _tool_policy_hash(profile: AgentProfile) -> str:
    raw = ",".join(profile.tools.allow) + ";" + ",".join(profile.tools.deny)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _identity_block(profile: AgentProfile) -> str:
    lines = [f"## Agent Profile: {profile.id} ({profile.name or profile.id})"]
    if profile.description:
        lines.append(f"Description: {profile.description}")
    ident = profile.identity
    if ident.role:
        lines.append(f"Role: {ident.role}")
    if ident.mission:
        lines.append(f"Mission: {ident.mission}")
    if ident.principles:
        lines.append("Principles:")
        lines.extend(f"- {p}" for p in ident.principles)
    return "\n".join(lines)
def _memory_dirs(profile: AgentProfile, task_id: str | None, project_id: str | None) -> tuple[str, ...]:
    from src.project_paths import user_home

    home = user_home()
    dirs: list[str] = []
    if profile.memory.enabled:
        namespace = namespace_segment(profile.memory.namespace, profile.id)
        dirs.append((home / "agents" / namespace / "memory").as_posix())
    if task_id:
        dirs.append((home / "tasks" / task_id).as_posix())
    if project_id:
        dirs.append((home / "projects" / project_id / "memory").as_posix())
    return tuple(dirs)


def _permission_extra_rules(profile: AgentProfile) -> dict[str, str]:
    approvals = profile.permissions.approvals
    rules: dict[str, str] = {}
    if approvals.execute == "required":
        rules["execute"] = "ask"
    if approvals.destructive_operations == "required":
        for tool in _DESTRUCTIVE_TOOLS:
            rules[tool] = "ask"
    if approvals.external_network == "required":
        for tool in _EXTERNAL_NETWORK_TOOLS:
            rules[tool] = "ask"
    return rules


_BAKE_CACHE: dict = {}
_BAKE_STATS = {"hits": 0, "misses": 0}


def _cache_key(
    config,
    profile: AgentProfile,
    agents_md_text: str,
    skill_manifest_hash: str,
    task_id: str | None,
    project_id: str | None,
    session_id: str | None,
    workspace: str,
) -> tuple:
    return (
        profile_hash(profile, agents_md_text),
        config.model_id,
        skill_manifest_hash,
        _tool_policy_hash(profile),
        task_id,
        project_id,
        session_id,
        workspace,
    )
def bake_spec(
    config,
    profile: AgentProfile | None,
    workspace: str,
    task_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    agents_md_text: str = "",
    *,
    skill_manifest_hash: str = "",
) -> ProfileSpec | None:
    """Bake a parsed profile into the runtime spec. None profile -> None.

    Missing/empty AGENTS.md text keeps the suffix identity-only (no error).
    Results are cached per content key; the effective skill manifest hash
    (caller override, else the freshly resolved tier manifest) is carried in the
    key so bakes invalidate on manifest change.
    """
    if profile is None:
        return None
    from src.profile_skills import resolve as _resolve_skills

    resolved = _resolve_skills(profile.id, str(workspace), project_id=project_id, profile=profile)
    effective_hash = skill_manifest_hash or resolved.manifest_hash
    key = _cache_key(config, profile, agents_md_text, effective_hash, task_id, project_id, session_id, str(workspace))
    cached = _BAKE_CACHE.get(key)
    if cached is not None:
        _BAKE_STATS["hits"] += 1
        return cached
    _BAKE_STATS["misses"] += 1

    suffix = _identity_block(profile)
    if agents_md_text.strip():
        suffix += "\n\n## Profile Instructions (AGENTS.md)\n" + agents_md_text

    snapshot = ProfileSnapshot(
        profile_id=profile.id,
        profile_version=str(profile.profile_version),
        profile_hash=profile_hash(profile, agents_md_text),
        runtime_version=_runtime_version(),
        engine=profile.runtime.engine,
        task_id=task_id or "",
        session_id=session_id or "",
        workspace=str(workspace),
    )
    spec = ProfileSpec(
        profile_id=profile.id,
        profile_version=profile.profile_version,
        profile_hash=profile_hash(profile, agents_md_text),
        model_id=profile.runtime.model or config.model_id,
        prompt_suffix=suffix,
        memory_dirs=_memory_dirs(profile, task_id, project_id),
        skill_routes=resolved.skill_routes,
        skill_vpaths=resolved.skill_vpaths,
        skill_manifest_hash=effective_hash,
        tool_allow=tuple(profile.tools.allow),
        tool_deny=tuple(profile.tools.deny),
        permission_extra_rules=_permission_extra_rules(profile),
        checkpoint_enabled=profile.session.checkpoint_enabled,
        checkpoint_policy=profile.session.checkpoint_policy,
        snapshot=snapshot,
    )
    _BAKE_CACHE[key] = spec
    return spec


def bake_cache_stats() -> dict:
    """Hit/miss counters plus entry count, for ticket 07 observability."""
    return {"hits": _BAKE_STATS["hits"], "misses": _BAKE_STATS["misses"], "size": len(_BAKE_CACHE)}


def _reset_bake_cache() -> None:
    _BAKE_CACHE.clear()
    _BAKE_STATS["hits"] = 0
    _BAKE_STATS["misses"] = 0
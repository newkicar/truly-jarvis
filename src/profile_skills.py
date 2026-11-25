"""Profile skill tier resolution (ticket 03 of .scratch/agent-profile).

Four tiers, low -> high precedence:

  common   ~/.jarvis/skills/common/   (sub-dir of the user skills root; reuses
             the existing /skills/ source - the resolver only declares the tier,
             it mounts no new route)
  agent    ~/.jarvis/agents/<ns>/skills/   -> route /agent-skills/
  project  ~/.jarvis/projects/<p>/skills/   -> route /project-skills/
  task     optional task dir (TaskContext.skills_dir) -> route /task-skills/

resolve() is a pure, read-only filesystem scan: it returns a
ResolvedSkillManifest describing every discovered SKILL.md, same-name
conflicts (higher tier wins, loser recorded), profile include/exclude
filters, and a stable manifest_hash. Legacy config.skills paths load
unchanged through the existing skill_paths layer (this resolver does not
touch them).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from src.profiles.schema import AgentProfile, Skills, namespace_segment

# Tier ranks, low -> high. Same name: the higher rank wins.
TIER_COMMON = "common"
TIER_AGENT = "agent"
TIER_PROJECT = "project"
TIER_TASK = "task"

_TIER_RANK = {TIER_COMMON: 0, TIER_AGENT: 1, TIER_PROJECT: 2, TIER_TASK: 3}
_TIER_ORDER = (TIER_COMMON, TIER_AGENT, TIER_PROJECT, TIER_TASK)

# vpaths. common reuses the existing user /skills/ source (no new route).
VPATH_COMMON = "/skills/"
VPATH_AGENT = "/agent-skills/"
VPATH_PROJECT = "/project-skills/"
VPATH_TASK = "/task-skills/"
_VPATH_FOR_TIER = {
    TIER_COMMON: VPATH_COMMON,
    TIER_AGENT: VPATH_AGENT,
    TIER_PROJECT: VPATH_PROJECT,
    TIER_TASK: VPATH_TASK,
}


@dataclass(frozen=True)
class TaskContext:
    """Optional task-level skill directory (highest tier)."""

    task_id: str = ""
    skills_dir: str | Path | None = None


@dataclass(frozen=True)
class SkillEntry:
    name: str
    tier: str
    fs_path: str
    content_hash: str
    vpath: str = ""


@dataclass(frozen=True)
class SkillConflict:
    name: str
    winner_tier: str
    winner_fs_path: str
    loser_tier: str
    loser_fs_path: str


@dataclass(frozen=True)
class ExcludedSkill:
    name: str
    tier: str
    reason: str  # "include" | "exclude" | "conflict" | "unreadable"


@dataclass(frozen=True)
class ResolvedSkillManifest:
    profile_id: str
    project_id: str
    task_id: str
    entries: tuple[SkillEntry, ...]
    conflicts: tuple[SkillConflict, ...]
    excluded: tuple[ExcludedSkill, ...]
    skill_routes: tuple[tuple[str, str], ...]
    skill_vpaths: tuple[str, ...]
    manifest_hash: str

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "entries": [dict(e.__dict__) for e in self.entries],
            "conflicts": [dict(c.__dict__) for c in self.conflicts],
            "excluded": [dict(x.__dict__) for x in self.excluded],
            "skill_routes": [list(r) for r in self.skill_routes],
            "skill_vpaths": list(self.skill_vpaths),
        }


def _skills_cfg(profile, legacy_profile) -> Skills:
    """include/exclude filter source: active profile first, legacy fallback, else none."""
    if profile is not None:
        return profile.skills
    if legacy_profile is not None and isinstance(legacy_profile.skills, Skills):
        return legacy_profile.skills
    return Skills()


def _parse_skill_name(skill_md: Path) -> tuple[str, str]:
    """Return (name, content_hash). name = frontmatter name or parent dir.

    An unreadable file yields ("", "") so the caller records it as
    excluded/unreadable.
    """
    from src.skill_discovery import _parse_frontmatter

    try:
        raw = skill_md.read_bytes()
    except OSError:
        return "", ""
    content_hash = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8", errors="replace")
    meta = _parse_frontmatter(text)
    name = (meta.get("name") or skill_md.parent.name or "").strip()
    return name, content_hash


def _scan_tier(tier: str, root: Path) -> tuple[dict[str, SkillEntry], list[ExcludedSkill]]:
    """Scan one tier root. Returns {name: entry} (later path wins) + unreadables."""
    found: dict[str, SkillEntry] = {}
    unreadable: list[ExcludedSkill] = []
    if not root.is_dir():
        return found, unreadable
    vpath = _VPATH_FOR_TIER[tier]
    for skill_md in sorted(root.rglob("SKILL.md")):
        name, content_hash = _parse_skill_name(skill_md)
        if not name or not content_hash:
            unreadable.append(ExcludedSkill(name=name or skill_md.parent.name, tier=tier, reason="unreadable"))
            continue
        found[name] = SkillEntry(name=name, tier=tier, fs_path=str(skill_md), content_hash=content_hash, vpath=vpath)
    return found, unreadable


def _tier_dirs(profile, profile_id, workspace, task_context, project_id, home) -> dict[str, Path]:
    """Map tier -> filesystem root. Missing/optional tiers are omitted.

    workspace is reserved for future project-root-relative tiers; the
    documented tiers are all keyed under the user home.
    """
    _ = workspace  # reserved
    pid = profile.id if profile is not None else profile_id
    ns = ""
    if profile is not None:
        # Normalize the namespace to a single safe segment so the 'agents/<id>'
        # spelling in the design doc cannot double the 'agents/' prefix, and
        # unsafe segments raise ProfileError (fail closed at schema parse time;
        # this guard also protects direct construction of AgentProfile).
        ns = namespace_segment(profile.memory.namespace, profile.id)
    elif pid:
        # No parsed profile available: fall back to the bare profile id so the
        # agent tier still resolves.
        ns = pid
    dirs: dict[str, Path] = {}
    dirs[TIER_COMMON] = home / "skills" / "common"
    if pid:
        dirs[TIER_AGENT] = home / "agents" / (ns or pid) / "skills"
    if project_id:
        dirs[TIER_PROJECT] = home / "projects" / project_id / "skills"
    task_dir = getattr(task_context, "skills_dir", None) if task_context is not None else None
    if task_dir:
        dirs[TIER_TASK] = Path(task_dir)
    return dirs


def _apply_filters(winners, include, exclude) -> tuple[list[SkillEntry], list[ExcludedSkill]]:
    inc = set(include)
    exc = set(exclude)
    kept: list[SkillEntry] = []
    dropped: list[ExcludedSkill] = []
    for entry in winners:
        if entry.name in exc:
            dropped.append(ExcludedSkill(name=entry.name, tier=entry.tier, reason="exclude"))
        elif inc and entry.name not in inc:
            dropped.append(ExcludedSkill(name=entry.name, tier=entry.tier, reason="include"))
        else:
            kept.append(entry)
    return kept, dropped


def _manifest_hash(profile_id, project_id, task_id, entries, conflicts, excluded, routes, vpaths) -> str:
    payload = {
        "profile_id": profile_id,
        "project_id": project_id,
        "task_id": task_id,
        "entries": [dict(e.__dict__) for e in entries],
        "conflicts": [dict(c.__dict__) for c in conflicts],
        "excluded": [dict(x.__dict__) for x in excluded],
        "skill_routes": [list(r) for r in routes],
        "skill_vpaths": list(vpaths),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve(  # noqa: C901
    profile_id: str,
    workspace: str | Path,
    task_context: TaskContext | None = None,
    *,
    profile: AgentProfile | None = None,
    legacy_profile: AgentProfile | None = None,
    project_id: str | None = None,
    user_home_: Path | str | None = None,
) -> ResolvedSkillManifest:
    """Scan the profile skill tiers and build a ResolvedSkillManifest.

    Pure and read-only (never creates directories). A missing tier root is
    skipped. Same-name skills resolve to the highest tier; each loser is
    recorded in conflicts (and in excluded with reason=conflict). The
    include/exclude filters from the active (else legacy) profile apply to
    the winners.
    """
    if isinstance(profile_id, AgentProfile):
        # Defensive: accept a parsed profile passed positionally (bake_spec
        # call style) and derive the id; the parsed object becomes the
        # active profile so its filters/namespace apply.
        profile = profile or profile_id
        profile_id = profile.id

    if user_home_ is not None:
        home = Path(user_home_)
    else:
        from src.project_paths import user_home

        home = user_home()

    skills_cfg = _skills_cfg(profile, legacy_profile)
    task_id = task_context.task_id if task_context is not None else ""
    tier_dirs = _tier_dirs(profile, profile_id, workspace, task_context, project_id, home)

    per_tier: dict[str, dict[str, SkillEntry]] = {}
    excluded: list[ExcludedSkill] = []
    for tier in _TIER_ORDER:
        root = tier_dirs.get(tier)
        if root is None:
            continue
        entries, unreadable = _scan_tier(tier, root)
        per_tier[tier] = entries
        excluded.extend(unreadable)

    # Same name -> highest tier wins; record every loser as a conflict.
    winners: dict[str, SkillEntry] = {}
    conflicts: list[SkillConflict] = []
    for tier in _TIER_ORDER:
        for name, entry in per_tier.get(tier, {}).items():
            prior = winners.get(name)
            if prior is None:
                winners[name] = entry
                continue
            if _TIER_RANK[tier] > _TIER_RANK[prior.tier]:
                conflicts.append(
                    SkillConflict(
                        name=name,
                        winner_tier=tier,
                        winner_fs_path=entry.fs_path,
                        loser_tier=prior.tier,
                        loser_fs_path=prior.fs_path,
                    )
                )
                excluded.append(ExcludedSkill(name=name, tier=prior.tier, reason="conflict"))
                winners[name] = entry
            else:
                conflicts.append(
                    SkillConflict(
                        name=name,
                        winner_tier=prior.tier,
                        winner_fs_path=prior.fs_path,
                        loser_tier=tier,
                        loser_fs_path=entry.fs_path,
                    )
                )
                excluded.append(ExcludedSkill(name=name, tier=tier, reason="conflict"))

    kept, filter_dropped = _apply_filters(list(winners.values()), skills_cfg.include, skills_cfg.exclude)
    excluded.extend(filter_dropped)

    kept_sorted = sorted(kept, key=lambda e: (e.name, _TIER_RANK[e.tier]))
    conflicts_sorted = sorted(
        conflicts, key=lambda c: (c.name, _TIER_RANK[c.winner_tier], _TIER_RANK[c.loser_tier])
    )
    excluded_sorted = sorted(excluded, key=lambda x: (x.name, _TIER_RANK[x.tier], x.reason))

    # routes + vpaths: only the tiers that actually kept an entry.
    route_fs: dict[str, str] = {}
    for entry in kept_sorted:
        if entry.tier != TIER_COMMON:
            root = tier_dirs.get(entry.tier)
            if root is not None:
                route_fs[entry.vpath] = str(root)
    skill_vpaths = tuple(dict.fromkeys(route_fs.keys()))
    skill_routes = tuple((vpath, route_fs[vpath]) for vpath in skill_vpaths)

    manifest_hash = _manifest_hash(
        profile_id,
        project_id or "",
        task_id,
        kept_sorted,
        conflicts_sorted,
        excluded_sorted,
        skill_routes,
        skill_vpaths,
    )

    return ResolvedSkillManifest(
        profile_id=profile_id,
        project_id=project_id or "",
        task_id=task_id,
        entries=tuple(kept_sorted),
        conflicts=tuple(conflicts_sorted),
        excluded=tuple(excluded_sorted),
        skill_routes=skill_routes,
        skill_vpaths=skill_vpaths,
        manifest_hash=manifest_hash,
    )


def scan_manual_only(dirs) -> set[str]:
    """Names of skills flagged disable-model-invocation across the given dirs.

    Keeps manual-only skills out of the model context when a profile tier
    ships them. Read-only; unreadable SKILL.md files are skipped.
    """
    from src.skill_discovery import _parse_frontmatter

    names: set[str] = set()
    for d in dirs:
        root = Path(d)
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            meta = _parse_frontmatter(text)
            flag = meta.get("disable-model-invocation", "").strip().casefold()
            if flag in ("true", "yes", "1"):
                name = (meta.get("name") or skill_md.parent.name or "").strip()
                if name:
                    names.add(name)
    return names


__all__ = [
    "TIER_COMMON",
    "TIER_AGENT",
    "TIER_PROJECT",
    "TIER_TASK",
    "VPATH_COMMON",
    "VPATH_AGENT",
    "VPATH_PROJECT",
    "VPATH_TASK",
    "TaskContext",
    "SkillEntry",
    "SkillConflict",
    "ExcludedSkill",
    "ResolvedSkillManifest",
    "resolve",
    "scan_manual_only",
]

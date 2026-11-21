"""Ticket 07: Agent Profile read-only diagnostics (/profiles, --profiles).

Provides:
  - profiles_cli(tokens, user_home=...)   CLI/TUI entry point -> (exit_code, text)
  - list_profiles(user_home=...)          all profile ids + db agent_profiles rows
  - validate_profile(pid, strict=...)     per-profile report (skill/memory/permission)
  - memory_namespace_view(ns, ...)        memory dir files + db candidate counts
  - skill_manifest_report(pid, ...)       resolved skill tiers/conflicts/excluded
  - permission_diagnose(profile, tool)   approval level explanation for one tool

Read-only: the only disk writes are the pre-existing registry.load() db
upsert and db.connect() schema migration. Diagnostics never emit ops
events themselves (they are the tool for inspecting them).
"""
from __future__ import annotations

from pathlib import Path

from src.profiles.schema import AgentProfile, ProfileError, namespace_segment

#: Gated tools with a dedicated approvals row in the permission diagnosis.
GATED_TOOLS = ("execute", "write_file", "edit_file", "delete")
#: Network-search tools governed by approvals.external_network.
NETWORK_TOOLS = ("quick_search", "search", "deep_search")


def _resolve_home(user_home: Path | str | None) -> Path:
    """Explicit home wins; otherwise the default user home at call time."""
    if user_home is not None:
        return Path(user_home)
    from src.project_paths import user_home as _default_home

    return _default_home()


def _registry(home: Path):
    # Red line: always pass an explicit home (None would fall back to the
    # real user home and leak/become slow in diagnostics and tests).
    from src.profiles.registry import ProfileRegistry

    return ProfileRegistry(user_home=home, workspace=None, jarvis_json_agents={})


def list_profiles(user_home: Path | str | None = None) -> str:
    """List every known profile id (builtin/user layers) + db rows."""
    home = _resolve_home(user_home)
    registry = _registry(home)
    lines: list[str] = []
    try:
        ids = registry.list()
    except Exception:
        ids = []
    if not ids:
        lines.append("（未发现 Agent Profile）")
    for pid in ids:
        try:
            profile = registry.get(pid)
        except ProfileError as exc:
            lines.append(f"- {pid}  解析失败：{exc}")
            continue
        except Exception as exc:  # malformed yaml etc.
            lines.append(f"- {pid}  解析失败：{exc}")
            continue
        tag = " [legacy]" if profile.is_legacy else f" v{profile.profile_version}"
        desc = (profile.description or "").strip().replace("\n", " ")
        if len(desc) > 60:
            desc = desc[:57] + "..."
        lines.append(f"- {pid}{tag}" + (f"  {desc}" if desc else ""))
    # db agent_profiles rows (best-effort)
    try:
        from src.profiles import db as _db

        rows = _db.list_profile_rows(home)
        if rows:
            lines.append("")
            lines.append("db agent_profiles 行：")
            for row in rows:
                lines.append(
                    f"- {row['profile_id']} schema-v{row['schema_version']} "
                    f"v{row['profile_version']} hash={str(row['profile_hash'])[:16]} "
                    f"enabled={row['enabled']}"
                )
    except Exception:
        pass
    return "\n".join(lines)


def skill_manifest_report(profile_id: str, user_home: Path | str | None = None) -> str:
    """Resolved skill tiers for one profile (entries/conflicts/excluded)."""
    home = _resolve_home(user_home)
    registry = _registry(home)
    try:
        profile = registry.get(profile_id)
    except ProfileError as exc:
        return f"  未知 profile：{exc}"
    except Exception as exc:
        return f"  解析失败：{exc}"
    from src.profile_skills import resolve

    try:
        manifest = resolve(profile_id, home, profile=profile, user_home_=home)
    except Exception as exc:
        return f"  skill 解析失败：{exc}"
    lines = [
        f"  entries={len(manifest.entries)} conflicts={len(manifest.conflicts)} "
        f"excluded={len(manifest.excluded)} manifest_hash={manifest.manifest_hash[:16]}",
    ]
    for entry in manifest.entries:
        lines.append(f"  [skill] [{entry.tier}] {entry.name}")
    for conflict in manifest.conflicts:
        lines.append(
            f"  [conflict] {conflict.name}：[{conflict.winner_tier}] 胜出，"
            f"[{conflict.loser_tier}] 落选"
        )
    for item in manifest.excluded:
        lines.append(f"  [excluded] {item.name}（{item.reason}）")
    return "\n".join(lines)


def memory_namespace_view(namespace: str, user_home: Path | str | None = None) -> str:
    """Memory dir files + db memory_candidates counts for one namespace."""
    home = _resolve_home(user_home)
    lines: list[str] = []
    mem_dir = home / "agents" / namespace / "memory"
    if mem_dir.is_dir():
        files = sorted(p for p in mem_dir.rglob("*") if p.is_file())
        if files:
            for f in files:
                try:
                    rel = f.relative_to(mem_dir).as_posix()
                    lines.append(f"  {rel} ({f.stat().st_size} B)")
                except OSError:
                    lines.append(f"  {f.name} (? B)")
        else:
            lines.append("  （目录为空）")
    else:
        lines.append(f"  （目录不存在：{mem_dir.as_posix()}）")
    try:
        from src.profiles import db as _db

        conn = _db.connect(home)
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM memory_candidates "
                "WHERE target_namespace = ? GROUP BY status",
                (f"agents/{namespace}",),
            ).fetchall()
            if rows:
                summary = "，".join(f"{status}={n}" for status, n in rows)
                lines.append(f"  db 候选：{summary}")
            else:
                lines.append("  db 候选：无")
        finally:
            conn.close()
    except Exception:
        lines.append("  db 候选：（读取 db 失败）")
    return "\n".join(lines)


def permission_diagnose(profile: AgentProfile, tool: str) -> str:
    """Explain which approval level governs one tool for this profile."""
    approvals = profile.permissions.approvals
    if tool == "execute":
        level, label = approvals.execute, "approvals.execute"
    elif tool in ("write_file", "edit_file", "delete"):
        level, label = (
            approvals.destructive_operations,
            "approvals.destructive_operations",
        )
    elif tool in NETWORK_TOOLS:
        level, label = approvals.external_network, "approvals.external_network"
    else:
        return "非 gated 工具（默认放行）"
    if level == "required":
        return f"{label}=required → 触发 ask 规则（每次审批）"
    return f"{label}=optional → 不强制，仍受 jarvis.json permissions 段约束"


def validate_profile(
    profile_id: str,
    *,
    user_home: Path | str | None = None,
    strict: bool = True,
) -> tuple[int, str]:
    """Validate one profile; strict adds skill/memory/permission sections.

    Returns (exit_code, report). 0=ok, 1=parse/validate failure, 2=unknown.
    """
    home = _resolve_home(user_home)
    registry = _registry(home)
    try:
        loaded = registry.load(profile_id)
    except ProfileError as exc:
        return 2, f"未知 profile：'{profile_id}'（{exc}）"
    except Exception as exc:
        return 1, f"profile 解析/校验失败：{exc}"

    profile = loaded.profile
    lines = [
        f"profile：{profile.id}",
        f"source：{loaded.source_path or '(builtin/unknown)'}",
        f"hash：{loaded.profile_hash[:16]}",
        f"version：{profile.profile_version}",
        f"AGENTS.md：{('有（' + str(len(loaded.agents_md_text)) + ' 字符）') if loaded.agents_md_text else '无'}",
    ]
    if profile.is_legacy:
        lines.append("kind：legacy（jarvis.json agent）")
    if not strict:
        return 0, "\n".join(lines)

    lines.append("")
    lines.append("skill 清单：")
    lines.append(skill_manifest_report(profile_id, user_home=home))
    lines.append("")
    if profile.memory.enabled:
        try:
            ns = namespace_segment(profile.memory.namespace, profile.id)
        except ProfileError:
            ns = profile.id
        lines.append("记忆命名空间：")
        lines.append(memory_namespace_view(ns, user_home=home))
    else:
        lines.append("记忆：disabled")
    lines.append("")
    lines.append("权限诊断（approvals）：")
    for tool in (*GATED_TOOLS, *NETWORK_TOOLS):
        lines.append(f"  {tool}：{permission_diagnose(profile, tool)}")
    return 0, "\n".join(lines)


_USAGE = "用法：/profiles [id] [--validate]（一次只诊断一个）"


def profiles_cli(
    tokens: list[str] | tuple[str, ...],
    *,
    user_home: Path | str | None = None,
) -> tuple[int, str]:
    """CLI/TUI dispatcher: 0 id -> list; 1 id -> validate (--validate=strict).

    Read-only; returns (exit_code, report_text).
    """
    args = [str(t) for t in tokens]
    while args and args[0] in ("--profiles", "/profiles"):
        args.pop(0)
    strict = "--validate" in args
    ids = [a for a in args if not a.startswith("-")]
    if len(ids) > 1:
        return 2, _USAGE
    home = _resolve_home(user_home)
    if not ids:
        return 0, list_profiles(user_home=home)
    return validate_profile(ids[0], user_home=home, strict=strict)
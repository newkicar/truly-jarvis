"""Skill 发现（Agent Skills 标准 SKILL.md frontmatter，供 /doctor 等只读诊断）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.config import Config
from src.skill_paths import discover_skill_layers

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    virtual_path: str
    layer: str


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _skill_virtual_path(layer_vpath: str, skill_md: Path, layer_fs: Path) -> str:
    rel = skill_md.parent.relative_to(layer_fs).as_posix()
    if layer_vpath.startswith("/workspace/"):
        base = layer_vpath.rstrip("/")
        return f"{base}/{rel}/SKILL.md" if rel != "." else f"{base}/SKILL.md"
    base = layer_vpath.rstrip("/")
    return f"{base}/{rel}/SKILL.md" if rel != "." else f"{base}/SKILL.md"


def discover_skill_catalog(config: Config) -> list[SkillMeta]:
    """扫描各 skill 层的 SKILL.md，返回 name/description（后层覆盖同名）。"""
    by_name: dict[str, SkillMeta] = {}
    for layer in discover_skill_layers(config):
        if not layer.fs_path.is_dir():
            continue
        for skill_md in sorted(layer.fs_path.rglob("SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            meta = _parse_frontmatter(text)
            name = (meta.get("name") or skill_md.parent.name).strip()
            description = (meta.get("description") or "").strip()
            if not name:
                continue
            vpath = _skill_virtual_path(layer.virtual_path, skill_md, layer.fs_path)
            by_name[name] = SkillMeta(
                name=name,
                description=description,
                virtual_path=vpath,
                layer=layer.virtual_path,
            )
    return sorted(by_name.values(), key=lambda s: s.name)


def summarize_skill_catalog(skills: list[SkillMeta]) -> str:
    if not skills:
        return "skills: 0（未发现 SKILL.md；deepagents 需在 skills/*/SKILL.md 写 frontmatter）"
    lines = [f"skills: {len(skills)}"]
    for skill in skills:
        desc = skill.description[:80] + ("…" if len(skill.description) > 80 else "")
        lines.append(f"  - {skill.name}: {desc or '(无 description)'}")
    return "\n".join(lines)

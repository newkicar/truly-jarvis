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
    manual_only: bool = False  # #09: disable-model-invocation (仅手动调用，模型上下文排除)
    fs_path: Path | None = None  # #09: SKILL.md 真实路径（/use 读取源）


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
            # #09: disable-model-invocation: true → 仅手动调用（/use），不进模型上下文
            flag = meta.get("disable-model-invocation", "").strip().casefold()
            manual_only = flag in ("true", "yes", "1")
            if not name:
                continue
            vpath = _skill_virtual_path(layer.virtual_path, skill_md, layer.fs_path)
            by_name[name] = SkillMeta(
                name=name,
                description=description,
                virtual_path=vpath,
                layer=layer.virtual_path,
                manual_only=manual_only,
                fs_path=skill_md,
            )
    return sorted(by_name.values(), key=lambda s: s.name)


def _subsequence_runs(name: str, query: str) -> int | None:
    """tui-ux9: name/query 须已 casefold；贪心左到右子序列命中块数；非子序列返回 None。

    块 = 连续命中游程；首命中开第 1 块，idx != prev+1 时开新块。
    """
    runs = 0
    prev = -2
    pos = 0
    for ch in query:
        idx = name.find(ch, pos)
        if idx < 0:
            return None
        if idx != prev + 1:
            runs += 1
        prev = idx
        pos = idx + 1
    return runs


def fuzzy_filter_skills(catalog: list[SkillMeta], query: str, limit: int = 20) -> list[SkillMeta]:
    """tui-ux9: skill 名模糊过滤（/use 补全唯一数据缝），纯函数、纯 stdlib。

    四档匹配（高档先、不跨档混排）：① 精确 ② 前缀 ③ 子串 ④ 子序列
    （贪心左到右，'-' 与任意字符可跳过）；子序列档内命中块更少（更连续）者先，
    再按名称短者先。空 query → catalog（名称序）前 `limit` 条；无匹配 → []；
    结果一律截断 `limit`。不改 discover_skill_catalog / SkillMeta。
    """
    q = query.casefold()
    if not q:
        return list(catalog[:limit])
    scored: list[tuple[int, int, int, SkillMeta]] = []
    for skill in catalog:
        n = skill.name.casefold()
        if n == q:
            tier, blocks = 0, 0
        elif n.startswith(q):
            tier, blocks = 1, 0
        elif q in n:
            tier, blocks = 2, 0
        else:
            runs = _subsequence_runs(n, q)
            if runs is None:
                continue
            tier, blocks = 3, runs
        scored.append((tier, blocks, len(skill.name), skill))
    scored.sort(key=lambda t: (t[0], t[1], t[2], t[3].name))
    return [entry[3] for entry in scored[:limit]]


def summarize_skill_catalog(skills: list[SkillMeta]) -> str:
    if not skills:
        return "skills: 0（未发现 SKILL.md；deepagents 需在 skills/*/SKILL.md 写 frontmatter）"
    lines = [f"skills: {len(skills)}"]
    for skill in skills:
        desc = skill.description[:80] + ("…" if len(skill.description) > 80 else "")
        tag = " [manual]" if skill.manual_only else ""
        lines.append(f"  - {skill.name}{tag}: {desc or '(无 description)'}")
    return "\n".join(lines)


def build_skill_use_message(config: Config, name: str, extra: str = "") -> str | None:
    """#09: 构建用户 /use 手动调用 skill 时投递给模型的消息。

    读取 skill 的 SKILL.md 全文（剥 frontmatter），前置指令引导语，按需追加任务说明；
    未找到 / 不可读 / 空正文返回 None（查找大小写不敏感）。
    """
    try:
        catalog = discover_skill_catalog(config)
    except Exception:
        catalog = []  # 未装配 Config 的调用面（如 TUI 测试）：按无 skill 处理，由调用方报错
    target = next(
        (s for s in catalog if s.name.casefold() == name.casefold()),
        None,
    )
    if target is None or target.fs_path is None or not target.fs_path.is_file():
        return None
    try:
        text = target.fs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    body = _FRONTMATTER_RE.sub("", text, count=1).strip()
    if not body:
        return None
    msg = f"[skill:{target.name}] 以下是该 skill 完整指令，请严格按其步骤执行:\n{body}"
    if extra:
        msg += f"\n\n任务：{extra}"
    return msg


def manual_only_skill_names(config: Config) -> set[str]:
    """#08: 手动调用 skill（disable-model-invocation: true）名集合，供模型上下文过滤。"""
    return {s.name for s in discover_skill_catalog(config) if s.manual_only}

"""WIKI 导航式知识库工具（wikilink/backlink 程序化支持）。

零索引：每次调用实时扫描 vault（不建持久索引、无维护负担），
与 grep/read_file 原生工具互补，替代「靠 prompt 从文本肉眼找 [[wikilink]]」。

解析规则（Obsidian 兼容子集）：
- [[标题]] / [[标题|显示名]] / [[标题#小节]] / [[标题|显示名#小节]]
- 标题匹配：文件名（stem，去扩展名）、目录内任意层级、大小写不敏感；
  匹配 frontmatter `aliases:` 列表中的别名（aliases 项可含空格）。
- 路径形式：[[目录/笔记]]、[[笔记.md]]。
"""
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")

_ALIAS_BLOCK_RE = re.compile(
    r"^aliases:\s*\n((?:^\s*-\s*.+$\n?)+)", re.MULTILINE
)
_ALIAS_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class WikiLink:
    """一条解析后的 wikilink。"""

    target: str  # 去掉显示名/小节后的目标（[[标题]] 的标题部分）
    display: str | None  # | 后的显示名（无则 None）
    section: str | None  # # 后的小节名（无则 None）
    raw: str  # 原始链接文本（不含外层 [[]]）


def extract_wikilinks(text: str) -> list[WikiLink]:
    """提取文本中所有 [[wikilink]]。

    支持 [[标题]]、[[标题|显示]]、[[标题#小节]]、[[标题|显示#小节]]。
    忽略纯内部锚点 [[#小节]]（无目标）。
    """
    out = []
    for m in WIKILINK_RE.finditer(text):
        raw = m.group(1).strip()
        if not raw:
            continue
        target_part, sep, section = raw.partition("#")
        target_part = target_part.strip()
        if target_part.startswith("|"):
            continue  # 内部锚点 [[#x]] → target 为空，跳过
        display = None
        if "|" in target_part:
            target, _, display = target_part.partition("|")
            target = target.strip()
            display = display.strip() or None
        else:
            target = target_part
        if not target:
            continue
        out.append(
            WikiLink(
                target=target,
                display=display,
                section=section.strip() or None,
                raw=raw,
            )
        )
    return out


def _aliases_from_text(text: str) -> list[str]:
    """提取 frontmatter `aliases:` 列表中的别名。"""
    out = []
    for block in _ALIAS_BLOCK_RE.findall(text):
        for item in _ALIAS_ITEM_RE.findall(block):
            if item:
                out.append(item)
    return out


def _title_variants(target: str) -> list[str]:
    """生成候选标题：去扩展名、去路径层级、保留原始形态。"""
    variants = [target]
    t = target
    if t.lower().endswith(".md"):
        t = t[:-3]
        variants.append(t)
    # 去掉目录层级后取末段（Obsidian 按文件名匹配）
    base = t.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base and base != t:
        variants.append(base)
    return variants


def resolve_link(vault_root: Path, target: str) -> Path | None:
    """把 wikilink 目标解析为 vault 内真实笔记路径。

    匹配优先级：文件名（stem，大小写不敏感）→ 目录内路径 → frontmatter aliases。
    找不到返回 None。
    """
    vault_root = Path(vault_root)
    variants = _title_variants(target)

    # 1) 显式路径形式：[[目录/笔记.md]] 直接文件存在
    for v in variants:
        cand = vault_root / v
        if cand.is_file():
            return cand
        cand = vault_root / f"{v}.md"
        if cand.is_file():
            return cand

    # 2) 遍历扫描：按 stem（大小写不敏感）匹配全部 .md
    lowered = {v.casefold() for v in variants}
    for p in vault_root.rglob("*.md"):
        if p.stem.casefold() in lowered:
            return p

    # 3) frontmatter aliases
    target_lower = target.casefold()
    target_base = target_lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if target_base.endswith(".md"):
        target_base = target_base[:-3]
    for p in vault_root.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for alias in _aliases_from_text(text):
            if alias.casefold() == target_lower or alias.casefold() == target_base:
                return p
    return None


def _vault_path(root: Path, note: Path) -> str:
    """把 vault 内绝对路径转成 /vault/ 开头的逻辑路径。"""
    try:
        rel = note.resolve().relative_to(root.resolve())
    except ValueError:
        rel = note
    return "/vault/" + rel.as_posix()


def _vault_links(vault_root: Path, note_path: str) -> str:
    """返回某笔记的所有出链 wikilink，含解析结果（是否存在 + 逻辑路径）。"""
    root = Path(vault_root)
    note = _resolve_note_path(root, note_path)
    if note is None:
        return f"找不到笔记: {note_path}"
    try:
        text = note.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return f"读取失败: {note_path}"
    links = extract_wikilinks(text)
    if not links:
        return f"{note_path} 没有出链 wikilink。"
    lines = [f"# {note_path} 的出链 wikilink:"]
    for link in links:
        resolved = resolve_link(root, link.target)
        if resolved is None:
            lines.append(f"- [[{link.raw}]] → ❌ 未找到（悬空链接）")
        else:
            shown = link.display if link.display else link.raw
            lines.append(f"- [[{shown}]] → {_vault_path(root, resolved)}")
    return "\n".join(lines)


def _vault_backlinks(vault_root: Path, note_path: str) -> str:
    """返回引用某笔记的所有其他笔记（反向链接）。

    反向匹配：其他笔记里的 [[wikilink]] 解析后指向目标笔记。
    """
    root = Path(vault_root)
    note = _resolve_note_path(root, note_path)
    if note is None:
        return f"找不到笔记: {note_path}"
    note_resolved = note.resolve()

    backlinks = []
    for p in root.rglob("*.md"):
        if p.resolve() == note_resolved:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for link in extract_wikilinks(text):
            resolved = resolve_link(root, link.target)
            if resolved is not None and resolved.resolve() == note_resolved:
                backlinks.append(p)
                break
    if not backlinks:
        return f"没有笔记链接到 {note_path}。"
    lines = [f"# 链接到 {note_path} 的笔记:"]
    for p in sorted(backlinks, key=lambda x: x.as_posix()):
        lines.append(f"- {_vault_path(root, p)}")
    return "\n".join(lines)


def _resolve_note_path(root: Path, note_path: str) -> Path | None:
    """把用户给的 /vault/... 或相对路径解析为 vault 内真实文件。"""
    root = Path(root).resolve()
    raw = note_path.strip()
    for prefix in ("/vault/", "vault/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    cand = root / raw
    if cand.is_file():
        return cand
    if cand.with_suffix(".md").is_file():
        return cand.with_suffix(".md")
    # 兜底：按文件名查找（不含路径）
    return resolve_link(root, Path(raw).name)


def make_wiki_tools(vault_root: Path):
    """构造绑定 vault 根目录的 wikilink 导航工具（langchain tool 形态）。

    返回 (vault_links, vault_backlinks) 两个只读工具：
    - vault_links: 列出某笔记的出链 wikilink 及其解析结果
    - vault_backlinks: 列出引用某笔记的所有笔记（反向链接）
    """
    root = Path(vault_root)

    @tool
    def vault_links(note_path: str) -> str:
        """查看笔记的出链 wikilink：返回该笔记里所有 [[链接]] 及其解析后的 /vault/ 路径。

        用于沿知识链接追关联笔记。参数为 /vault/ 路径或相对路径（如 /vault/Inbox/笔记.md）。
        """
        return _vault_links(root, note_path)

    @tool
    def vault_backlinks(note_path: str) -> str:
        """查看反向链接：返回所有引用了该笔记的 /vault/ 路径。

        用于从一篇笔记找到「谁在讨论它」，补全上下文。
        """
        return _vault_backlinks(root, note_path)

    return [vault_links, vault_backlinks]
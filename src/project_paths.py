"""项目根与安装目录解析（OpenCode 式：运行目录即 workspace）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

JARVIS_JSON = "jarvis.json"
# 0.1.x 遗留布局：checkpoints/ 直接放项目根；下版本起统一进 .jarvis/（迁移见 migrate_project_dotdir）
CHECKPOINTS_DIR = ".jarvis/checkpoints"


def resolve_checkpoint_db(project_root: Path, db_name: str = "checkpoints.sqlite") -> Path:
    """解析 checkpoint 数据库路径（固定到 checkpoints/ 子目录，不可配置）。"""
    path = project_root / CHECKPOINTS_DIR / db_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


ENV_PROJECT_ROOT = "JARVIS_PROJECT_ROOT"
ENV_JARVIS_HOME = "JARVIS_HOME"
DEFAULT_USER_HOME = ".jarvis"


def install_root() -> Path:
    """JARVIS 引擎安装目录（含 src/、内置 skills/）。"""
    # Frozen Nuitka onedir: the exe directory is the install root (skills/ ships
    # next to the exe, flat layout, see packaging/build_gui.ps1); the build-time
    # __file__ points at the source tree on the build machine and must not be used.
    if getattr(sys, "frozen", False):
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent.parent


def _migrate_user_home() -> Path:
    """~/.javis/ → ~/.jarvis/ 自动迁移（旧版用户无感升级）。"""
    old_home = Path.home() / ".javis"
    new_home = Path.home() / DEFAULT_USER_HOME
    if old_home.is_dir() and not new_home.is_dir():
        old_home.rename(new_home)
    return new_home


def discover_project_root(start: Path | None = None) -> Path:
    """从 start（默认 cwd）向上查找 jarvis.json；找不到则返回 start/cwd。

    环境变量 JARVIS_PROJECT_ROOT 可强制指定。
    """
    override = os.environ.get(ENV_PROJECT_ROOT, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / JARVIS_JSON).is_file():
            return directory
    return current


_runtime_project_root: Path | None = None


def set_runtime_project_root(root: Path) -> None:
    """启动时由 load_config / main 设置当前会话项目根。"""
    global _runtime_project_root
    _runtime_project_root = Path(root).resolve()


def get_project_root() -> Path:
    """当前会话项目根；未设置时 discover。"""
    if _runtime_project_root is not None:
        return _runtime_project_root
    return discover_project_root()


def resolve_jarvis_json(project_root: Path | None = None) -> Path:
    root = (project_root or discover_project_root()).resolve()
    candidate = root / JARVIS_JSON
    if candidate.is_file():
        return candidate
    # 仅当未显式指定 project_root 时 fallback（即 cwd 发现模式）
    if project_root is None:
        install_candidate = install_root() / JARVIS_JSON
        if install_candidate.is_file():
            return install_candidate
    return candidate


def resolve_env_file(project_root: Path | None = None) -> Path:
    """解析 .env：项目根优先，否则安装目录。"""
    root = (project_root or discover_project_root()).resolve()
    for candidate in (root / ".env", install_root() / ".env"):
        if candidate.is_file():
            return candidate
    return root / ".env"


def user_home() -> Path:
    """用户全局目录（默认 ~/.jarvis，可用 JARVIS_HOME 覆盖）。"""
    override = os.environ.get(ENV_JARVIS_HOME, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _migrate_user_home()


def ensure_user_home() -> Path:
    """确保用户全局目录存在（全局 jarvis.json 默认配置）。"""
    import json as _json

    from src.config import GLOBAL_DEFAULTS

    home = user_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(parents=True, exist_ok=True)

    global_cfg = home / JARVIS_JSON
    if not global_cfg.is_file():
        global_cfg.write_text(
            _json.dumps(GLOBAL_DEFAULTS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    from src.skill_paths import seed_builtin_skills
    seed_builtin_skills()

    return home


def resolve_user_jarvis_json() -> Path:
    """用户全局 jarvis.json 路径（~/.jarvis/jarvis.json）。"""
    return user_home() / JARVIS_JSON


INSTRUCTIONS_FILENAME = "AGENTS.md"
# 旧版本 /init 生成的指令文件名；加载器作为回落（AGENTS.md 缺失/为空时读取），/init 不自动生成
LEGACY_INSTRUCTIONS_FILENAME = "JARVIS.md"


def _read_instructions_level(base_dir: Path, label: str) -> str | None:
    """读一级指令文件：AGENTS.md 优先，legacy JARVIS.md 回落；该级不存在或全空返回 None。"""
    for name in (INSTRUCTIONS_FILENAME, LEGACY_INSTRUCTIONS_FILENAME):
        f = base_dir / name
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return f"### {label}（{f}）\n{text}"
    return None


def load_project_instructions(project_root: Path | None = None) -> str:
    """发现并读取项目指令文件（AGENTS.md 分层：全局 + 项目级，对齐业界约定）。

    - 全局：~/.jarvis/AGENTS.md（用户跨项目约定）
    - 项目级：{project_root}/AGENTS.md（本项目技术约定）
    - 每级 AGENTS.md 优先；旧版 legacy JARVIS.md 作回落（该级 AGENTS.md 缺失/为空时读取）

    两级都可选；都存在则拼接（全局在前）。文件缺失返回空串。
    build_agent 启动时调用一次（会话中途编辑文件需重启生效）。
    """
    sections: list[str] = []
    global_section = _read_instructions_level(user_home(), "全局用户约定")
    if global_section:
        sections.append(global_section)
    root = (project_root or get_project_root()).resolve()
    project_section = _read_instructions_level(root, "本项目约定")
    if project_section:
        sections.append(project_section)
    return "\n\n".join(sections)


DOTDIR = ".jarvis"


def _merge_session_jsons(old_bytes: bytes, new_bytes: bytes) -> bytes | None:
    """两份 sessions.json 字节 → 合并后的 UTF-8 编码；不可并（非 JSON / 非 dict）返回 None。"""
    import json

    try:
        old = json.loads(old_bytes.decode("utf-8"))
        new = json.loads(new_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(old, dict) or not isinstance(new, dict):
        return None
    merged = dict(old)  # 源独有键保留
    merged.update(new)  # 冲突键目标（.jarvis/ 侧）胜
    return json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")


def migrate_project_dotdir(config) -> list[str]:
    """一次性把遗留的项目级状态文件迁移进 {project_root}/.jarvis/（幂等，绝不覆盖异构目标）。

    - 遗留 checkpoints/（整目录或逐文件）→ .jarvis/checkpoints/
    - 遗留 sessions.json → .jarvis/sessions.json（相同→删源；两边 dict→union 合并后删源；否则留源 warn）
    - 遗留 skills/（整目录 move）→ .jarvis/skills/（同名冲突 .jarvis/ 侧优先，源侧同名内容删除，无备份）；
      jarvis.json 的 skills 条目以 "skills" 开头者改写为 .jarvis/skills 前缀；项目根 == 安装根（开发模式）跳过
    返回人类可读 note 列表（调用方打印、不阻塞）；全新项目无遗留 → []。
    源与目标同名文件字节相同 = 视为已迁移（保留源，下版本清理）。
    """
    root = Path(config.project_root).resolve()
    notes: list[str] = []

    # ---- checkpoints/ 目录 ----
    old_cp = root / "checkpoints"
    new_cp = root / DOTDIR / "checkpoints"
    if old_cp.is_dir():
        if not new_cp.exists():
            new_cp.parent.mkdir(parents=True, exist_ok=True)
            old_cp.rename(new_cp)
            notes.append(f"checkpoints/ 已迁移 → {new_cp.relative_to(root)}")
        else:
            for f in sorted(old_cp.iterdir()):
                dst = new_cp / f.name
                if not f.is_file():
                    continue
                if dst.exists():
                    if dst.read_bytes() == f.read_bytes():
                        continue  # 相同 = 已迁移，跳过（保留源）
                    notes.append(f"checkpoints/{f.name} 两边内容不同，目标未动，请人工合并（源保留）")
                else:
                    f.rename(dst)
                    notes.append(f"checkpoints/{f.name} 已迁移 → {new_cp.relative_to(root)}/{f.name}")
            try:
                old_cp.rmdir()  # 源清空才删；有残留（同字节跳过/冲突保留）则留下
            except OSError:
                pass

    # ---- sessions.json ----
    old_sj = root / "sessions.json"
    new_sj = root / DOTDIR / "sessions.json"
    if old_sj.is_file():
        if not new_sj.exists():
            new_sj.parent.mkdir(parents=True, exist_ok=True)
            old_sj.rename(new_sj)
            notes.append(f"sessions.json 已迁移 → {new_sj.relative_to(root)}")
        else:
            old_bytes = old_sj.read_bytes()
            new_bytes = new_sj.read_bytes()
            if old_bytes == new_bytes:
                old_sj.unlink()
                notes.append("sessions.json 与 .jarvis/ 副本相同，源已删除")
            else:
                merged = _merge_session_jsons(old_bytes, new_bytes)
                if merged is not None:
                    new_sj.write_bytes(merged)
                    old_sj.unlink()
                    notes.append("sessions.json 已并入 .jarvis/（冲突键以 .jarvis/ 为准，源已删除）")
                else:
                    notes.append("sessions.json 两边不可自动合并，目标未动，请人工处理（源保留）")

    # ---- skills/ → .jarvis/skills/（ADR-0016：整目录 move；同名冲突 .jarvis/ 侧优先，源侧同名内容删除，无备份）----
    if root != install_root().resolve():
        import json
        import shutil

        old_sk = root / "skills"
        new_sk = root / DOTDIR / "skills"
        if old_sk.is_dir():
            if new_sk.is_file():
                notes.append(".jarvis/skills 是文件而非目录，请人工处理（源 skills/ 保留）")
            elif not new_sk.exists():
                new_sk.parent.mkdir(parents=True, exist_ok=True)
                old_sk.rename(new_sk)
                notes.append(f"skills/ 已迁移 → {new_sk.relative_to(root)}（整目录 move）")
            else:
                for entry in sorted(old_sk.iterdir()):
                    dst = new_sk / entry.name
                    if dst.exists() or dst.is_symlink():
                        # 目标优先：源侧同名内容永久删除（用户约定，无备份）
                        if entry.is_dir() and not entry.is_symlink():
                            shutil.rmtree(entry)
                        else:
                            entry.unlink()
                        notes.append(f".jarvis/skills/{entry.name} 已存在，目标优先，旧 skills/{entry.name} 已移除")
                    else:
                        entry.rename(dst)
                try:
                    old_sk.rmdir()  # 源清空才删；有残留（rename 失败）则保留
                except OSError:
                    pass

        # jarvis.json skills 条目改写（与目录 move 相互独立：JSON 缺失/损坏不影响目录 move）
        json_path = root / JARVIS_JSON
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict):
            skills_list = data.get("skills")
            if isinstance(skills_list, list):
                changed = 0
                rewritten = []
                for item in skills_list:
                    if not isinstance(item, str):
                        rewritten.append(item)
                        continue
                    norm = item.strip().strip("/").casefold()
                    if norm == "skills":
                        rewritten.append(".jarvis/skills")
                        changed += 1
                    elif norm.startswith("skills/"):
                        suffix = item.strip().strip("/")[len("skills/"):]
                        rewritten.append(f".jarvis/skills/{suffix}")
                        changed += 1
                    else:
                        rewritten.append(item)
                if changed:
                    data["skills"] = rewritten
                    json_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    notes.append(f"jarvis.json skills 条目已改写 → .jarvis/skills（{changed} 条）")

    return notes

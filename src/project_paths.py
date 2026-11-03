"""项目根与安装目录解析（OpenCode 式：运行目录即 workspace）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

JARVIS_JSON = "jarvis.json"
CHECKPOINTS_DIR = "checkpoints"


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

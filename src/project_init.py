"""初始化新的 JARVIS 项目目录（javis init）；/init 生成 JARVIS.md 项目指令草稿（确定性扫描）。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

from src.project_paths import JARVIS_JSON, CHECKPOINTS_DIR, INSTRUCTIONS_FILENAME, discover_project_root, install_root

ENV_EXAMPLE = """\
# JARVIS 环境变量（复制为 .env 并填写）
BASE_URL=https://opencode.ai/zen/go/v1
API_KEY=sk-your-key
MODEL_ID=mimo-v2.5
TAVILY_KEY=tvly-your-key
"""

JARVIS_JSON_TEMPLATE: dict = {
    "model": {
        "base_url_env": "BASE_URL",
        "api_key_env": "API_KEY",
        "model_id_env": "MODEL_ID",
    },
    # 知识库（可选）：填路径启用 /vault/；留空 "" 或删除本键 = 无知识库。
    # 兼容旧键 obsidian_vault（knowledge_base 优先）。
    "knowledge_base": "vault",
    "checkpoint_db": f"{CHECKPOINTS_DIR}/checkpoints.sqlite",
    "skills": ["skills/"],
    "schedules_dir": "schedules",
    "mcps": {"servers": {}},
    "permissions": {
        "*": "ask",
        "execute": "ask",
        "write_file": "ask",
        "edit_file": "ask",
        "delete": "ask",
    },
    "hooks": {"permission": []},
    "rag": {
        "ollama_base_url": "http://localhost:11434",
        "embed_model": "quentinz/bge-small-zh-v1.5",
    },
    "execution": {
        "max_steps": 200,
    },
    "tui": {
        "copy_on_select": True,
    },
    "theme": "flexoki",
}


def write_run_launcher(project_root: Path, engine_root: Path) -> Path:
    """生成 Windows 启动脚本：项目目录只有配置，引擎在安装目录。"""
    launcher = project_root / "run-javis.cmd"
    engine = engine_root.resolve()
    launcher.write_text(
        "@echo off\r\n"
        "set \"JARVIS_PROJECT_ROOT=%~dp0\"\r\n"
        f'cd /d "{engine}"\r\n'
        "python -m src.main %*\r\n",
        encoding="utf-8",
    )
    return launcher


def init_project(
    target: Path,
    *,
    vault_path: str | None = None,
    force: bool = False,
    engine_root: Path | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """在 target 创建 javis.json 与目录结构。

    Returns:
        (created_paths, skipped_paths, messages)
    """
    root = target.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    engine = (engine_root or install_root()).resolve()

    created: list[str] = []
    skipped: list[str] = []
    messages: list[str] = []

    javis_path = root / JARVIS_JSON
    if javis_path.is_file() and not force:
        skipped.append(str(javis_path))
        messages.append(f"已存在 {JARVIS_JSON}，跳过（加 --force 覆盖）")
    else:
        data = dict(JARVIS_JSON_TEMPLATE)
        if vault_path:
            data["knowledge_base"] = vault_path
        javis_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(str(javis_path))

    env_example = root / ".env.example"
    if env_example.is_file() and not force:
        skipped.append(str(env_example))
    else:
        env_example.write_text(ENV_EXAMPLE, encoding="utf-8")
        created.append(str(env_example))

    env_file = root / ".env"
    if not env_file.is_file():
        env_file.write_text(ENV_EXAMPLE, encoding="utf-8")
        created.append(str(env_file))
        messages.append("已生成 .env 模板，请填写 API Key 后再启动。")
    else:
        skipped.append(str(env_file))

    for rel in ("schedules", "skills", "vault", "vault/Inbox", "vault/Reports"):
        path = root / rel
        if path.is_dir():
            skipped.append(str(path))
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))

    readme = root / "vault" / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# 本地知识库占位\n\n"
            "可在 `javis.json` 的 `knowledge_base` 改为你的 Obsidian 路径；"
            "留空（\"\"）或删除该键则禁用知识库。也可在此目录放 markdown 作为本地知识库。\n",
            encoding="utf-8",
        )
        created.append(str(readme))

    launcher = write_run_launcher(root, engine)
    created.append(str(launcher))
    messages.append(
        f"已生成 run-javis.cmd（引擎目录: {engine}）。"
        "请勿在项目目录直接 python -m src.main（那里没有 src 包）。"
    )

    return created, skipped, messages


def format_init_report(root: Path, created: list[str], skipped: list[str], messages: list[str]) -> str:
    lines = [f"JARVIS 项目已初始化：{root}", ""]
    if created:
        lines.append("已创建：")
        lines.extend(f"  + {p}" for p in created)
    if skipped:
        lines.append("已跳过：")
        lines.extend(f"  · {p}" for p in skipped)
    if messages:
        lines.append("")
        lines.extend(messages)
    lines.extend(
        [
            "",
            "下一步：",
            f"  1. 编辑 {root / '.env'} 填写 BASE_URL / API_KEY / MODEL_ID / TAVILY_KEY",
            f"  2. 编辑 {root / JARVIS_JSON}（knowledge_base、permissions 等）",
            f"  3. 双击 {root / 'run-javis.cmd'} 启动 TUI",
            "",
            "或手动指定项目根（从 JARVIS 安装目录运行）：",
            f'  set JARVIS_PROJECT_ROOT={root}',
            "  cd <JARVIS安装目录>",
            "  python -m src.main",
        ]
    )
    return "\n".join(lines)


def run_init_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="javis init", description="初始化 JARVIS 项目目录")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="目标目录（默认当前目录）",
    )
    parser.add_argument(
        "--knowledge-base",
        "--vault",
        dest="vault_path",
        default=None,
        help="知识库路径（写入 javis.json knowledge_base；留空禁用）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的 javis.json / .env.example",
    )
    ns = parser.parse_args(argv)
    root = Path(ns.directory)
    created, skipped, messages = init_project(
        root,
        vault_path=ns.vault_path,
        force=ns.force,
        engine_root=install_root(),
    )
    print(format_init_report(root.resolve(), created, skipped, messages))
    return 0


def suggest_init_if_missing(start: Path | None = None) -> str | None:
    """cwd 及上级均无 jarvis.json 时返回提示文案。"""
    current = (start or Path.cwd()).resolve()
    if (current / JARVIS_JSON).is_file():
        return None
    for directory in (current, *current.parents):
        if (directory / JARVIS_JSON).is_file():
            return None
    return (
        f"当前目录未找到 {JARVIS_JSON}。可先初始化项目：\n"
        f"  jarvis --init\n"
    )


def auto_init_project(root: Path | None = None) -> None:
    """首次运行时自动生成项目级 jarvis.json + skills/（对标 opencode 开箱即用）。

    仅在 jarvis.json 不存在时生成，幂等安全。
    """
    from src.project_paths import ensure_user_home

    project_root = (root or Path.cwd()).resolve()
    jarvis_file = project_root / JARVIS_JSON
    if not jarvis_file.is_file():
        data = dict(JARVIS_JSON_TEMPLATE)
        data["project_name"] = project_root.name
        jarvis_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (project_root / "skills").mkdir(exist_ok=True)
    ensure_user_home()




# ---------------------------------------------------------------------------
# /init 项目指令：确定性扫描草稿（无 LLM；JARVIS.md 启动时注入 system prompt）
# ---------------------------------------------------------------------------

# 扫描时跳过的目录名（噪音/依赖/缓存），全部小写比较。
_SKIP_DIRS = frozenset(
    {
        ".git", "node_modules", ".venv", "venv", "env", "environment",
        "__pycache__", ".idea", ".vscode", ".eclipse",
        "target", "build", "dist", "out", "bin", "obj",
        ".next", ".nuxt", ".mypy_cache", ".pytest_cache", ".tox",
        ".gradle", "vendor", ".terraform", ".cache", ".ruff_cache",
        ".DS_Store",
    }
)

# 语言扩展名 → 展示名
_LANG_EXT: "OrderedDict[str, str]" = OrderedDict(
    (e, n) for e, n in [
        (".py", "Python"), (".js", "JavaScript"), (".ts", "TypeScript"),
        (".jsx", "JSX"), (".tsx", "TSX"), (".go", "Go"), (".rs", "Rust"),
        (".java", "Java"), (".c", "C"), (".cpp", "C++"), (".h", "C/C++ header"),
        (".rb", "Ruby"), (".php", "PHP"), (".cs", "C#"), (".swift", "Swift"),
        (".kt", "Kotlin"), (".sh", "Shell"),
    ]
)

# 构建/测试清单 → 探测出的命令
_MANIFEST_TEST = {
    "pyproject.toml": "python -m pytest",
    "go.mod": "go test ./...",
    "Cargo.toml": "cargo test",
    "pom.xml": "mvn test",
    "build.gradle": "./gradlew test",
}


def _iter_dirs(root: Path, depth: int):
    """有界目录枚举：仅到 depth 层（root=0, root/*=1, root/*/*=2）。

    跳过：.开头隐藏目录（缓存/配置）、以及 _SKIP_DIRS 里明确的噪音目录。
    """
    yield root, 0
    if depth <= 0:
        return

    def _keep(name: str) -> bool:
        return not name.startswith(".") and name not in _SKIP_DIRS

    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        return
    for e in entries:
        if not e.is_dir() or not _keep(e.name):
            continue
        yield e, 1
        if depth > 1:
            try:
                for sub in sorted(e.iterdir(), key=lambda p: p.name.casefold()):
                    if sub.is_dir() and _keep(sub.name):
                        yield sub, 2
            except OSError:
                continue


def _count_langs(root: Path) -> "OrderedDict[str, int]":
    """有界统计 2 层内常规文件按扩展名归类的语言计数。"""
    counts: "OrderedDict[str, int]" = OrderedDict((n, 0) for n in _LANG_EXT.values())
    for _dir, _depth in _iter_dirs(root, 2):
        try:
            files = list(_dir.iterdir())
        except OSError:
            continue
        for f in files:
            if not f.is_file() or f.name.startswith("."):
                continue
            ext = f.suffix.casefold() if f.suffix else ""
            lang = _LANG_EXT.get(ext)
            if lang:
                counts[lang] += 1
    return counts


def _detect_manifests(root: Path) -> tuple[list[str], dict[str, str]]:
    """返回 (manifest 文件名列表, 探测出的命令映射)。"""
    found: list[str] = []
    cmds: dict[str, str] = {}
    top = {p.name.casefold() for p in root.iterdir() if p.is_file()} if _ok(root) else set()

    # package.json 的 scripts（test/build/lint/dev/start）
    pkg = root / "package.json"
    if pkg.is_file():
        found.append("package.json")
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts") if isinstance(data, dict) else {}
            if isinstance(scripts, dict):
                for key in ("test", "build", "lint", "dev", "start"):
                    val = scripts.get(key)
                    if isinstance(val, str) and val.strip():
                        cmds[key] = val.strip()
        except Exception:
            pass

    for name, test_cmd in _MANIFEST_TEST.items():
        if name in top:
            found.append(name)
            cmds.setdefault("test", test_cmd)
    if "requirements.txt" in top:
        found.append("requirements.txt")
    if "Makefile" in top:
        found.append("Makefile")
        cmds.setdefault("test", "make test" if _make_has_target(root, "test") else "make")
    return found, cmds


def _ok(root: Path) -> bool:
    try:
        _ = root.is_dir()
        return True
    except OSError:
        return False


def _make_has_target(root: Path, target: str) -> bool:
    mk = root / "Makefile"
    if not mk.is_file():
        return False
    try:
        text = mk.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    for line in text.splitlines():
        if line.strip().startswith(target + ":"):
            return True
    return False


def _top_tree(root: Path, limit: int = 40) -> list[str]:
    """有界 2 层目录树文本（每目录截断到 limit 行）。"""
    lines: list[str] = []
    rendered = 0
    for d, depth in _iter_dirs(root, 2):
        if depth == 0:
            continue
        rel = d.relative_to(root).as_posix()
        # 只显示本层直接子项（目录）名，便于概览
        try:
            subs = [p.name for p in d.iterdir() if p.is_dir() and p.name not in _SKIP_DIRS]
            subs = subs[:8]
        except OSError:
            subs = []
        label = rel + ("/" + ", ".join(subs) if subs else "")
        lines.append("  " * depth + "- " + label)
        rendered += 1
        if rendered >= limit:
            break
    return lines


def scan_project(root: Path) -> dict:
    """扫描项目：语言统计 + 清单 + 有界目录树。纯只读。"""
    root = root.resolve()
    langs = _count_langs(root)
    manifests, cmds = _detect_manifests(root)
    top_langs = [(n, c) for n, c in langs.items() if c]
    return {
        "root": root,
        "langs": top_langs,
        "manifests": manifests,
        "cmds": cmds,
        "tree": _top_tree(root),
    }


def render_jarvis_md(scan: dict) -> str:
    """把 scan 渲染成 JARVIS.md 脚手架文本（确定性、无 LLM）。"""
    root: Path = scan["root"]
    lines: list[str] = []
    a = lines.append
    a(f"# {root.name} — JARVIS 项目指令")
    a("")
    a("> 本文件由 `/init` 通过确定性项目扫描生成（非 LLM）。启动时自动注入 jarvis 的 system prompt。")
    a("> 请人工补全「约定」节的占位内容；删除不适用的小节。")
    a("")
    a("## 项目概览")
    a("")
    top = scan.get("langs") or []
    if top:
        shown = ", ".join(f"{n}×{c}" for n, c in top[:5])
        a(f"- 主要语言：{shown}")
    else:
        a("- 主要语言：（未检测到源码文件）")
    manifests = scan.get("manifests") or []
    if manifests:
        a(f"- 项目清单：{', '.join(manifests)}")
    a("")
    a("## 构建 / 测试 / 运行")
    a("")
    cmds = scan.get("cmds") or {}
    if cmds:
        order = [("build", "构建"), ("test", "测试"), ("lint", "代码检查"), ("dev", "本地开发"), ("start", "启动")]
        for key, label in order:
            if key in cmds:
                a(f"- {label}：`{cmds[key]}`")
        for key, val in cmds.items():
            if key not in ("build", "test", "lint", "dev", "start"):
                a(f"- {key}：`{val}`")
    else:
        a("- （未探测到明确的构建/测试命令；请在此补充）")
    a("")
    a("## 目录结构")
    a("")
    tree = scan.get("tree") or []
    if tree:
        a("```")
        a(root.name + "/")
        for t in tree:
            a(t)
        a("```")
    else:
        a("（目录为空或未检测到子目录）")
    a("")
    a("## 约定")
    a("")
    a("- （待补充：命名规范、代码风格、测试要求、提交规范等）")
    a("- 新增功能优先参考同类开源工具的成熟做法，避免闭门造车。")
    a("")
    a("## jarvis 使用提示")
    a("")
    a("- 修改前先读相关源码；`/history` `/replay` `/fork` 可回退会话，`/snapshot` `/rollback` 回退文件。")
    a("- 危险/写操作默认走 HITL 审批（可配 `jarvis.json` 的 permissions 段）。")
    a("")
    return "\n".join(lines) + "\n"


def init_project_instructions(root: Path) -> str:
    """在 root 生成 JARVIS.md；已存在则不覆盖并返回提示。"""
    root = root.resolve()
    target = root / INSTRUCTIONS_FILENAME
    if target.is_file():
        return (
            f"{INSTRUCTIONS_FILENAME} 已存在（{target}），未覆盖。"
            "如需重建请先删除该文件再运行 /init；或手工编辑已有文件。"
        )
    if not root.is_dir():
        return f"项目目录不存在或不可访问：{root}，无法生成 {INSTRUCTIONS_FILENAME}。"
    scan = scan_project(root)
    target.write_text(render_jarvis_md(scan), encoding="utf-8")
    langs = scan.get("langs") or []
    top = ", ".join(n for n, _ in langs[:3]) or "未识别"
    return (
        f"已在项目根生成 {INSTRUCTIONS_FILENAME}（确定性扫描草稿）。"
        f"检测到主要语言：{top}。请人工补全「约定」节后提交。"
    )


if __name__ == "__main__":
    sys.exit(run_init_cli())

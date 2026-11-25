"""首启 .env 自动引导（tui-ux27，TUI/CLI 侧）。

问题：jarvis 运行依赖 .env（BASE_URL/API_KEY/MODEL_ID/TAVILY_KEY），缺键时
load_config 抛 KeyError 裸报错；便携包不带 .env（只有 .env.example），首启即卡死。

方案（用户选定）：首启交互引导——缺键时按序提示（API_KEY 隐藏输入），
生成 .env 文件（原子 upsert，复用 src.config.upsert_env_file 内核），用户不操心。
GUI 侧对应 gui-ux26（向导保存 LLM 配置时生成安装目录 .env）；本模块是其
TUI/CLI 等价兜底，main() 在 auto_init_project 之后调用。

语义（与 load_config 对齐）：
- 缺键判定 = 键「不存在」；空值合法（TAVILY_KEY= 即可）。
- 文件选择（_pick_env_file）：项目 .env 存在 → 它；否则安装目录 .env 存在 → 它；
  都不在 → 新建项目 .env。与 load_config 的 resolve_env_file + install 兜底一致。
- 键齐 → 严格 no-op（不写文件，保护 dev/已有 .env 一个字不动）。
- 非交互（CI/管道）→ stderr 打手动指引（guidance_text），不写文件。
"""
import getpass
import sys
from pathlib import Path

from src.config import REQUIRED_ENV_KEYS, parse_env_text, upsert_env_file
from src.project_paths import discover_project_root, install_root

DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_MODEL_ID = "mimo-v2.5"

# 交互提示顺序：地址 → 模型 → key（隐藏）→ tavily（可选）
_PROMPT_ORDER = ("BASE_URL", "MODEL_ID", "API_KEY", "TAVILY_KEY")


def _pick_env_file(root: Path | None = None) -> Path:
    """与 load_config 同源的 .env 选择：既有项目 .env → 既有安装 .env → 新建项目 .env。"""
    project = Path(root).resolve() if root is not None else discover_project_root()
    project_env = project / ".env"
    if project_env.is_file():
        return project_env
    install_env = install_root() / ".env"
    if install_env.is_file():
        return install_env
    return project_env


def missing_env_report(
    project_root: Path | None = None,
    target: Path | None = None,
) -> tuple[Path, list[str]]:
    """(目标 .env 路径, 缺失键列表)。显式 target 优先；缺键 = 键不存在（空值合法）。"""
    target = Path(target) if target is not None else _pick_env_file(project_root)
    env = parse_env_text(target.read_text(encoding="utf-8")) if target.is_file() else {}
    missing = [k for k in REQUIRED_ENV_KEYS if k not in env]
    return target, missing


def guidance_text(target: Path, missing: list[str]) -> str:
    """手动指引（非交互 / 交互 EOF 回落）：创建编辑文件 + 默认值示例 + 重启提醒。"""
    lines = [
        f"[配置] .env 缺键: {', '.join(missing)}",
        f"请手动创建或编辑: {target}",
        "    每行一个键，格式 KEY=VALUE（KEY:VALUE 亦认）:",
        f"        BASE_URL={DEFAULT_BASE_URL}    （已有地址请填自己的）",
        "        API_KEY=<你的 API key>",
        f"        MODEL_ID={DEFAULT_MODEL_ID}    （已有模型请填自己的）",
        "        TAVILY_KEY=            （可选，可留空）",
        "    参考仓库根 .env.example。",
        "修改后重启 jarvis 生效。",
    ]
    return "\n".join(lines)


def bootstrap_missing_env(  # noqa: C901
    values: dict[str, str] | None = None,
    *,
    project_root: Path | None = None,
    target: Path | None = None,
    interactive: bool | None = None,
) -> Path | None:
    """引导补齐 .env 缺键；返回写入的目标路径，no-op / 回落指引时返回 None。

    - 缺键全空 → 严格 no-op（返回 None，不碰文件）；
    - values 覆盖全部缺键 → 直接 upsert 写入（不触发任何提示，供测试/内部调用）；
    - interactive=None 时按 sys.stdin.isatty() 判定；
      非交互且有剩余缺键 → stderr 打 guidance_text，返回 None（不写文件）；
    - 交互按序提示：BASE_URL/MODEL_ID 空回车落默认；API_KEY 用 getpass 隐藏输入
      （空则重试）；TAVILY_KEY 可选（空写 TAVILY_KEY=）；EOFError/KeyboardInterrupt
      回落指引，不写文件。
    """
    target = Path(target) if target is not None else _pick_env_file(project_root)
    _, missing = missing_env_report(project_root=project_root, target=target)
    provided = {str(k).upper(): str(v) for k, v in (values or {}).items()}
    still = [k for k in missing if k not in provided]

    if not still:
        if not missing:
            return None  # 键齐：严格 no-op
        upsert_env_file(
            target,
            {k: provided[k] for k in missing},
            header="# JARVIS 环境变量（首启自动引导生成）",
            ensure_keys=("TAVILY_KEY",),
        )
        print(f"[配置] 已写入 .env: {target}（键: {', '.join(missing)}）")
        return target

    if interactive is None:
        try:
            interactive = bool(sys.stdin and sys.stdin.isatty())
        except (AttributeError, ValueError):
            interactive = False
    if not interactive:
        print(guidance_text(target, still), file=sys.stderr)
        return None

    collected = dict(provided)
    try:
        for key in _PROMPT_ORDER:
            if key in collected:
                continue
            if key == "API_KEY":
                while True:
                    val = getpass.getpass("[env] API_KEY（隐藏输入，空则重输）: ")
                    if val.strip():
                        collected[key] = val
                        break
            else:
                default = (
                    DEFAULT_BASE_URL if key == "BASE_URL"
                    else DEFAULT_MODEL_ID if key == "MODEL_ID"
                    else ""
                )
                suffix = f"（回车 = {default}）" if default else "（可选，回车 = 留空）"
                val = input(f"[env] {key}{suffix}: ").strip()
                collected[key] = val or default
    except (EOFError, KeyboardInterrupt):
        print(guidance_text(target, still), file=sys.stderr)
        return None

    upsert_env_file(
        target,
        {k: collected[k] for k in still},
        header="# JARVIS 环境变量（首启自动引导生成）",
        ensure_keys=("TAVILY_KEY",),
    )
    print(f"[配置] 已写入 .env: {target}（键: {', '.join(still)}）。重启后生效。")
    return target

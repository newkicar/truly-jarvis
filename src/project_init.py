"""初始化新的 JARVIS 项目目录（javis init）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.project_paths import JAVIS_JSON, discover_project_root

ENV_EXAMPLE = """\
# JARVIS 环境变量（复制为 .env 并填写）
BASE_URL=https://opencode.ai/zen/go/v1
API_KEY=sk-your-key
MODEL_ID=mimo-v2.5
TAVILY_KEY=tvly-your-key
"""

JAVIS_JSON_TEMPLATE: dict = {
    "model": {
        "base_url_env": "BASE_URL",
        "api_key_env": "API_KEY",
        "model_id_env": "MODEL_ID",
    },
    "obsidian_vault": "vault",
    "memory_dir": "memory",
    "checkpoint_db": "checkpoints.sqlite",
    "skills": ["skills/"],
    "schedules_dir": "schedules",
    "mcps": {"servers": {}},
    "permissions": {"*": "ask"},
    "rag": {
        "ollama_base_url": "http://localhost:11434",
        "embed_model": "quentinz/bge-small-zh-v1.5",
    },
    "tui": {
        "copy_on_select": True,
    },
    "theme": "flexoki",
}


def init_project(
    target: Path,
    *,
    vault_path: str | None = None,
    force: bool = False,
) -> tuple[list[str], list[str], list[str]]:
    """在 target 创建 javis.json 与目录结构。

    Returns:
        (created_paths, skipped_paths, messages)
    """
    root = target.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    skipped: list[str] = []
    messages: list[str] = []

    javis_path = root / JAVIS_JSON
    if javis_path.is_file() and not force:
        skipped.append(str(javis_path))
        messages.append(f"已存在 {JAVIS_JSON}，跳过（加 --force 覆盖）")
    else:
        data = dict(JAVIS_JSON_TEMPLATE)
        if vault_path:
            data["obsidian_vault"] = vault_path
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

    for rel in ("memory", "schedules", "skills", "vault", "vault/Inbox", "vault/Reports"):
        path = root / rel
        if path.is_dir():
            skipped.append(str(path))
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))

    readme = root / "vault" / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# 本地 Vault 占位\n\n"
            "可在 `javis.json` 的 `obsidian_vault` 改为你的 Obsidian 路径；"
            "或在此目录放 markdown 作为可选知识库。\n",
            encoding="utf-8",
        )
        created.append(str(readme))

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
            f"  2. 编辑 {root / JAVIS_JSON}（obsidian_vault、permissions 等）",
            f"  3. cd {root} && python -m src.main",
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
        "--vault",
        dest="vault_path",
        default=None,
        help="Obsidian vault 路径（写入 javis.json obsidian_vault）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的 javis.json / .env.example",
    )
    ns = parser.parse_args(argv)
    root = Path(ns.directory)
    created, skipped, messages = init_project(root, vault_path=ns.vault_path, force=ns.force)
    print(format_init_report(root.resolve(), created, skipped, messages))
    return 0


def suggest_init_if_missing(start: Path | None = None) -> str | None:
    """cwd 及上级均无 javis.json 时返回提示文案。"""
    root = discover_project_root(start)
    current = (start or Path.cwd()).resolve()
    if (current / JAVIS_JSON).is_file() or (root / JAVIS_JSON).is_file():
        return None
    if (root.parent / JAVIS_JSON).is_file():
        return None
    # discover returns cwd when not found — only hint when truly no javis.json up the tree
    for directory in (current, *current.parents):
        if (directory / JAVIS_JSON).is_file():
            return None
    return (
        f"当前目录未找到 {JAVIS_JSON}。可先初始化项目：\n"
        f"  python -m src.main --init\n"
        f"或在任意目录：python -m src.main --init /path/to/project"
    )


if __name__ == "__main__":
    sys.exit(run_init_cli())

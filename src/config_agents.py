"""从 javis.json 的 agents 段加载可追加子代理。"""
from __future__ import annotations

import logging

from src.permissions import (
    build_permission_deny_middleware,
    build_permission_interrupts,
)
from src.resilience import ToolErrorBoundaryMiddleware

log = logging.getLogger(__name__)

RESERVED_AGENT_NAMES = frozenset({"researcher", "knowledge_keeper", "general-purpose"})

_ERROR_BOUNDARY = ToolErrorBoundaryMiddleware()


def build_config_subagents(
    agents_config: dict | None,
    *,
    default_deny_middleware,
) -> list[dict]:
    """把 javis.json agents 段转为 deepagents SubAgent dict 列表（仅追加）。"""
    if not isinstance(agents_config, dict):
        return []

    specs: list[dict] = []
    for name, raw in agents_config.items():
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if name in RESERVED_AGENT_NAMES:
            log.warning("跳过 agents.%s：与内置子代理同名", name)
            continue
        if not isinstance(raw, dict):
            log.warning("跳过 agents.%s：配置应为对象", name)
            continue

        description = str(raw.get("description") or "").strip()
        system_prompt = str(raw.get("system_prompt") or raw.get("prompt") or "").strip()
        if not description or not system_prompt:
            log.warning("跳过 agents.%s：缺少 description 或 system_prompt", name)
            continue

        middleware: list = [_ERROR_BOUNDARY, default_deny_middleware]
        spec: dict[str, object] = {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "middleware": middleware,
        }

        perms = raw.get("permissions")
        if isinstance(perms, dict) and perms:
            interrupt_on, agent_state = build_permission_interrupts(perms)
            spec["interrupt_on"] = interrupt_on
            spec["middleware"] = [_ERROR_BOUNDARY, build_permission_deny_middleware(agent_state)]

        specs.append(spec)
    return specs

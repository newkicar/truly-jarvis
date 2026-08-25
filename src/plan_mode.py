"""#08 Plan/Act 双模式（对标 opencode Tab 切换 build/plan）。

模式状态存于 permission_state["mode"]（与 PermissionDenyMiddleware 共享同一
state 引用的既有惯例）——TUI 切换只改 state，无需重建 agent。

Plan 模式两道闸：
1. wrap_tool_call：写类工具与 execute 执行前拦截，返回 error ToolMessage
   引导先完成规划；读类文件工具放行。execute 曾按原 brief 留给提示词约束，
   2026-08-25 实测约束不住（弱模型仍发起执行触发 HITL 弹窗），改为硬边界。
2. wrap_model_call：往当轮 system 尾部追加规划约束提示词（StepBudgetMiddleware
   手法），不写入持久历史；其中同步声明 execute 已禁用，双保险引导模型改道。
"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware

MODE_KEY = "mode"
MODES = ("act", "plan")
# execute 一并硬拦（2026-08-25 用户实测：提示词约束不住弱模型，仍发起
# execute 触发 HITL 弹窗——「提示词是建议，代码才是边界」）。Plan 的只读
# 探索由文件工具（ls/read_file/grep/glob）覆盖，shell 整体留待 Act。
PLAN_TOOLS = frozenset({"write_file", "edit_file", "delete", "execute"})

PLAN_MODE_PROMPT = (
    "\n\n[Plan 模式]\n"
    "当前处于 Plan 模式——只做规划和分析，不做任何修改：\n"
    "- 可以：读取文件、搜索代码、列出目录、分析架构、用 write_todos 输出任务分解清单\n"
    "- 不可以：写入/编辑/删除文件；execute 只用于只读命令（查看、检索），禁止任何修改状态的命令\n"
    "- 输出：先给出任务分解清单（write_todos），再逐项分析要点与风险\n"
    "- 完成规划后提醒用户按 Tab 切回 Act 模式再开始执行\n"
)


def current_mode(state: dict) -> str:
    """读取当前模式；未设置时默认 act。"""
    return str((state or {}).get(MODE_KEY) or "act")


def set_mode(state: dict, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode!r}")
    state[MODE_KEY] = mode


class PlanModeMiddleware(AgentMiddleware):
    """Plan 模式闸门：state 驱动，运行时切换即时生效（无需重建 agent）。"""

    def __init__(self, state: dict):
        super().__init__()
        self.state = state

    @property
    def name(self) -> str:
        return "plan-mode"

    def _blocked_message(self, tool: str, tool_call_id: str):
        from langchain_core.messages import ToolMessage

        return ToolMessage(
            content=(
                f"Error: 当前处于 Plan 模式，{tool} 已被禁用。"
                "请完成规划分析（可用 write_todos 记录任务分解），"
                "完成后提示用户按 Tab 切回 Act 模式再执行修改。"
            ),
            name=tool,
            tool_call_id=tool_call_id,
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        if current_mode(self.state) == "plan":
            tool_call = getattr(request, "tool_call", None) or {}
            tool = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
            if tool in PLAN_TOOLS:
                return self._blocked_message(tool, tool_call.get("id", ""))
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        return self.wrap_tool_call(request, handler)

    def _with_plan_prompt(self, request):
        from langchain_core.messages import SystemMessage

        base = getattr(request, "system_message", None)
        text = str(getattr(base, "text", None) or getattr(base, "content", "") or "")
        merged = f"{text}{PLAN_MODE_PROMPT}" if text else PLAN_MODE_PROMPT.strip()
        return request.override(system_message=SystemMessage(content=merged))

    def wrap_model_call(self, request, handler):
        if current_mode(self.state) == "plan":
            request = self._with_plan_prompt(request)
        return handler(request)

    async def awrap_model_call(self, request, handler):
        return self.wrap_model_call(request, lambda r: handler(r))

"""#08 Plan/Act 双模式（对标 opencode Tab 切换 build/plan）。

模式状态存于 permission_state["mode"]（与 PermissionDenyMiddleware 共享同一
state 引用的既有惯例）——TUI 切换只改 state，无需重建 agent。

Plan 模式两道闸：
1. wrap_tool_call：写类工具（write_file/edit_file/delete）执行前拦截，返回
   error ToolMessage 引导先完成规划。execute 不硬拦——agent 需要用它做只读
   探索（如 python -c 读取文件、查看数据）；禁止 execute 中修改状态的行为
   由系统提示词约束。
2. wrap_model_call：往当轮 system 尾部追加规划约束提示词（StepBudgetMiddleware
   手法），不写入持久历史。
"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware

MODE_KEY = "mode"
MODES = ("act", "plan")
# 只拦写操作；execute 不拦——只读探索由 agent 通过 execute + Python 命令完成，
# 禁止修改状态的行为靠提示词约束（不拆命令，命令级白名单不可维护）。
PLAN_TOOLS = frozenset({"write_file", "edit_file", "delete"})

PLAN_MODE_PROMPT = (
    "\n\n[Plan 模式]\n"
    "当前处于 Plan 模式——只做规划和分析，不做任何修改：\n"
    "- 可以：读取文件、搜索代码、列出目录、分析架构、用 write_todos 输出任务分解清单\n"
    "- 可以用 execute 执行只读命令（查看数据、检查文件、浏览目录结构），但禁止用 execute 做任何修改操作（禁止 echo > / cp / mv / rm / mkdir / write / 创建脚本文件等）\n"
    "- 不可以：用 write_file/edit_file/delete 写入任何文件\n"
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

"""#08 Plan/Act 双模式（对标 opencode Tab 切换 build/plan）。

模式状态存于 permission_state["mode"]（与 PermissionDenyMiddleware 共享同一
state 引用的既有惯例）——TUI 切换只改 state，无需重建 agent。

Plan 模式两道闸：
1. wrap_tool_call（GuardMiddleware.block）：写类工具（write_file/edit_file/delete）
   执行前拦截，返回 error ToolMessage 引导先完成规划。execute 不硬拦——agent 需要
   用它做只读探索（如 python -c 读取文件、查看数据）；禁止 execute 中修改状态的
   行为由系统提示词约束。
2. wrap_model_call：往当轮 system 尾部追加规划约束提示词（StepBudgetMiddleware
   手法），不写入持久历史。
3. side 线程（effective_mode）：side_threads 成员即强制 plan（只读），全局
   模式键不因 side 开/关而变——对主线模式零影响（对标 codex 隔离）。
"""
from __future__ import annotations

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView

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


def effective_mode(state: dict, thread_id: str | None) -> str:
    """线程级生效模式：side 成员即永久 plan（只读），非 side 线程跟随全局模式。

    side 隔离（对标 codex）：side 会话只读由 side_threads 成员身份驱动，
    全局 state["mode"] 键不因 side 开/关而变——对主线模式零影响。
    """
    from src.permissions import side_active

    if side_active(state or {}, str(thread_id or "")):
        return "plan"
    return current_mode(state)


class PlanModeMiddleware(GuardMiddleware):
    """Plan 模式闸门：state 驱动，运行时切换即时生效（无需重建 agent）。

    tool 侧由 GuardMiddleware.block() 实现；model 侧由 wrap_model_call 单独实现。
    """

    def __init__(self, state: dict):
        super().__init__()
        self.state = state

    @property
    def name(self) -> str:
        return "plan-mode"

    def block(self, view: ToolCallView) -> str | None:
        tid = str((self.state or {}).get("thread_id") or "")
        if effective_mode(self.state, tid) == "plan" and view.name in PLAN_TOOLS:
            return (
                f"Error: 当前处于 Plan 模式，{view.name} 已被禁用。"
                "请完成规划分析（可用 write_todos 记录任务分解），"
                "完成后提示用户按 Tab 切回 Act 模式再执行修改。"
            )
        return None

    def _with_plan_prompt(self, request):
        from langchain_core.messages import SystemMessage

        base = getattr(request, "system_message", None)
        text = str(getattr(base, "text", None) or getattr(base, "content", "") or "")
        merged = f"{text}{PLAN_MODE_PROMPT}" if text else PLAN_MODE_PROMPT.strip()
        return request.override(system_message=SystemMessage(content=merged))

    def _prepare(self, request):
        tid = str((self.state or {}).get("thread_id") or "")
        if effective_mode(self.state, tid) == "plan":
            request = self._with_plan_prompt(request)
        return request

    def wrap_model_call(self, request, handler):
        return handler(self._prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._prepare(request))

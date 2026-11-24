"""src/goal_tools.py — 模型侧 goal 工具 ×3（create_goal / complete_goal / get_goal）。

对标 codex-rs goals 模型侧三工具面：模型可查询目标（get）、声明目标（create）、
附审计证据标记完成（complete）。pause/resume 是人类命令面（/goal），不给模型。

注入契约（#goal 04）：
- 仅主代理：agent.py build_agent 启动时一次性注入（MCP 同款注入位）；
  researcher / knowledge_keeper / config_agents 自定义子代理 spec 均不含。
- thread_id 调用时从 permission_state 共享引用读取（streaming 每轮开头写入）；
  permission_state 为 None 或缺 thread_id → 友好文本，不抛。
- 存储走 src.goals（goals.json，单进程）；异常族一律转为 str 文本返回（模型可见），
  不 raise（工具层边界）。
"""
from __future__ import annotations

from langchain_core.tools import tool

from src import goals

# 状态 → 中文展示（get_goal 输出用）
_GOAL_STATUS_CN = {
    goals.GOAL_ACTIVE: "进行中",
    goals.GOAL_PAUSED: "已暂停",
    goals.GOAL_BUDGET_LIMITED: "回合预算耗尽",
    goals.GOAL_COMPLETE: "已完成",
}


def build_goal_tools(
    permission_state: dict | None,
    goals_path=None,
    default_max_turns: int | None = None,
) -> list:
    """构造 3 个 goal 工具（闭包捕获 goals_path / default_max_turns / permission_state 引用）。

    - goals_path：显式存储路径（测试注入用）；None → goals.goals_path() 默认（~/.jarvis/goals.json）
    - default_max_turns：create_goal 未显式传 max_turns 时的预算（来自 Config.goals_max_turns）
    - permission_state：与 permissions/vault 共享的同一 state 引用，调用时取 ["thread_id"]
    """

    def _thread_id() -> str:
        return str((permission_state or {}).get("thread_id", ""))

    @tool
    def create_goal(objective: str, max_turns: int | None = None) -> str:
        """为本会话声明一个持久目标（自动续跑依据；一会话一个在途目标）。

        使用条件：
        - 已有在途目标（active/paused）时创建会失败——先 /goal pause 或 /goal clear（人类命令面）；
        - 终态目标（complete/budget_limited）须先 /goal clear 再重建；
        - 目标文本不能为空；预算缺省取 harness 默认（可显式传 max_turns 覆盖，钳 [1,9999]）。
        成功 → 返回目标 #id / 状态 / 回合预算；失败 → 返回失败原因文本（不抛）。
        """
        tid = _thread_id()
        if not tid:
            return "无法创建目标：当前会话缺少 thread_id（permission_state 未提供）"
        n = default_max_turns if max_turns is None else max_turns
        try:
            goal = goals.goal_set(
                path=goals_path,
                thread_id=tid,
                objective=objective,
                max_turns=n,
            )
        except goals.GoalError as exc:
            return str(exc)
        return (
            "目标已创建（#" + str(goal.goal_id) + "）：" + goal.objective
            + " | 状态：进行中 | 回合预算：" + str(goal.turns_used) + "/" + str(goal.max_turns)
        )

    @tool
    def complete_goal(audit_evidence: str) -> str:
        """把本会话当前目标标记为完成（唯一 complete 写路径），必须附审计证据。

        使用条件：
        - audit_evidence 必填（strip 后非空）：命令输出 / 测试结果 / 文件变更清单；
          空证据会被拒绝（"complete 必须附审计证据"）；
        - 无目标 / 目标已终态 → 返回说明文本（不抛）；
        - 成功后目标翻 complete（终态），不再自动续跑。
        """
        tid = _thread_id()
        if not tid:
            return "无法标记完成：当前会话缺少 thread_id（permission_state 未提供）"
        try:
            goal = goals.goal_complete(
                path=goals_path,
                thread_id=tid,
                audit_evidence=audit_evidence,
            )
        except goals.GoalError as exc:
            return str(exc)
        return (
            "目标已标记完成（#" + str(goal.goal_id) + "）"
            + (" | completed_at=" + goal.completed_at if goal.completed_at else "")
            + " | 证据已记录"
        )

    @tool
    def get_goal() -> str:
        """查询本会话持久目标（只读）：objective / 状态 / 已用与最大回合 / 剩余预算。

        无目标 → 返回"本会话无目标"提示；不会创建或修改目标。
        """
        tid = _thread_id()
        if not tid:
            return "本会话无目标（当前会话缺少 thread_id，无法查询）"
        goal = goals.goal_status(goals_path, tid)
        if goal is None:
            return "本会话无目标（可用 create_goal 创建）"
        cn = _GOAL_STATUS_CN.get(goal.status, goal.status)
        lines = [
            "目标 #" + str(goal.goal_id) + "（" + goal.objective + "）",
            "状态：" + cn + "（" + goal.status + "）",
            "回合：" + str(goal.turns_used) + "/" + str(goal.max_turns),
            "剩余预算：" + str(max(goal.max_turns - goal.turns_used, 0)),
        ]
        if goal.audit_evidence:
            lines.append("审计证据：" + goal.audit_evidence)
        if goal.completed_at:
            lines.append("completed_at：" + goal.completed_at)
        return "\n".join(lines)

    return [create_goal, complete_goal, get_goal]

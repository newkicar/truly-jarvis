"""src/goals.py — /goal 持久目标 + 自动续跑纯逻辑（CLI/TUI/GUI 共用，不 import 任何前端）。

设计对标（spec Further Notes 锁定）：codex-rs goals/continuation.md + budget_limit.md。
- 存储：~/.jarvis/goals.json（JARVIS_HOME 可覆盖），顶层 dict 按 thread_id 键，
  原子写（同目录 tmp + rename）；缺文件 / 损坏 / 非 dict → warning + 空 dict（不崩）。
- 状态机：active / paused / budget_limited / complete（后两者为终态）；
  每会话一个目标（goal_set 遇在途目标拒写）；complete 唯一写路径 = goal_complete。
- goal_id 乐观版本：每次 set 新建记录 id+1；写操作可携带 expected_goal_id
  （= 调用方所知"磁盘上现存记录的 goal_id"，认为无记录时传 0），不匹配 →
  StaleGoalVersion 显式失败（不静默覆盖）。
- should_continue / continuation_decision 为纯函数；turn 鸭子类型
  （.outcome/.tool_calls_count），与 streaming.TurnOutcome 结构兼容但本模块
  不 import streaming。ctx 约定：{"thread_id": str, "plan_mode": bool,
  "pending_interrupt": bool}，缺键视为 False/空。
- 纪律（双 prompt）：微调参数≠换方案；harness 拦截的命令不许重发；complete
  必须附审计证据；预算耗尽轮 = 收尾交接轮（禁开新工作）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.project_paths import user_home

GOALS_FILENAME = "goals.json"

GOAL_ACTIVE = "active"
GOAL_PAUSED = "paused"
GOAL_BUDGET_LIMITED = "budget_limited"
GOAL_COMPLETE = "complete"
TERMINAL_STATUSES = frozenset({GOAL_BUDGET_LIMITED, GOAL_COMPLETE})
DEFAULT_GOAL_MAX_TURNS = 5


# #goal 05: 续跑轮输入前缀（与 continuation_prompt/budget_prompt 字面量对应），
# 前端展示层据此把自动续跑输入渲染成 dim 系统行而非用户消息行。
_GOAL_INPUT_RE = re.compile(r"^\[目标(续跑|预算耗尽) (\d+)/(\d+)\]")


def goal_input_label(text: str | None) -> str | None:
    """text 以 [目标续跑 n/m] / [目标预算耗尽 n/m] 开头 → 短标签，否则 None。

    纯函数（前端展示层共用，CLI/TUI/GUI 不重复实现）：
    - [目标续跑 n/m] → "目标续跑 n/m"
    - [目标预算耗尽 n/m] → "目标收尾 n/m"
    """
    if not isinstance(text, str):
        return None
    m = _GOAL_INPUT_RE.match(text)
    if m is None:
        return None
    verb = "目标续跑" if m.group(1) == "续跑" else "目标收尾"
    return f"{verb} {m.group(2)}/{m.group(3)}"


class GoalError(RuntimeError):
    """goal 状态机/存储错误（消息自带可操作指引）。"""


class NoGoalError(GoalError):
    """该线程无 goal 记录，须先 /goal <objective> 创建。"""


class GoalExistsError(GoalError):
    """该会话已有在途目标（一会话一目标），须先 pause 或 clear。"""


class TerminalGoalError(GoalError):
    """goal 已终态（budget_limited/complete），须 clear 后重建。"""


class StaleGoalVersion(GoalError):
    """乐观版本不符（引用过期或并发写），显式失败不静默覆盖。"""


class EvidenceRequiredError(GoalError):
    """complete 未附审计证据。"""


def _as_int(value, default: int) -> int:
    """容错 int 转换（损坏记录不炸）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Goal:
    """单个会话的持久目标记录（goals.json 值 shape）。"""

    thread_id: str
    goal_id: int
    objective: str
    status: str
    turns_used: int
    max_turns: int
    completed_at: str | None = None
    audit_evidence: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "thread_id": self.thread_id,
            "goal_id": self.goal_id,
            "objective": self.objective,
            "status": self.status,
            "turns_used": self.turns_used,
            "max_turns": self.max_turns,
        }
        if self.completed_at is not None:
            d["completed_at"] = self.completed_at
        if self.audit_evidence is not None:
            d["audit_evidence"] = self.audit_evidence
        return d

    @classmethod
    def from_dict(cls, d: dict, thread_id: str | None = None) -> "Goal":
        return cls(
            thread_id=thread_id or str(d.get("thread_id", "")),
            goal_id=_as_int(d.get("goal_id", 0), 0),
            objective=str(d.get("objective", "")),
            status=str(d.get("status", GOAL_ACTIVE)),
            turns_used=_as_int(d.get("turns_used", 0), 0),
            max_turns=_as_int(d.get("max_turns", DEFAULT_GOAL_MAX_TURNS), DEFAULT_GOAL_MAX_TURNS),
            completed_at=d.get("completed_at"),
            audit_evidence=d.get("audit_evidence"),
        )


def goals_path() -> Path:
    """全局 goal 存储路径（~/.jarvis/goals.json，JARVIS_HOME 可覆盖）。"""
    return user_home() / GOALS_FILENAME


def load_goals(path: Path | None = None) -> dict[str, dict]:
    """读 goals.json；缺文件 / 损坏 / 非 dict / 值非 dict → warning + {}（不崩）。"""
    p = Path(path) if path else goals_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logging.warning("goals.json 损坏/不可读，忽略: %s (%s)", p, exc)
        return {}
    if not isinstance(raw, dict):
        logging.warning("goals.json 顶层非 dict，忽略: %s", p)
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _resolve_path(path: Path | None) -> Path:
    return Path(path) if path else goals_path()


def _atomic_write(path: Path, goals: dict[str, dict]) -> None:
    """原子写：同目录 tmp（name.tmp）→ json(ensure_ascii=False, indent=2) → replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(goals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_raw_goals(path: Path | None) -> dict:
    """读 goals.json 原始顶层 dict（保留 int 墓碑等非 dict 值）；缺文件 / 损坏 / 非 dict → {}（不崩）。"""
    p = Path(path) if path else goals_path()
    if not p.is_file():
        return {}
    try:
        raw_map = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logging.warning("goals.json 损坏/不可读，忽略: %s (%s)", p, exc)
        return {}
    if not isinstance(raw_map, dict):
        logging.warning("goals.json 顶层非 dict，忽略: %s", p)
        return {}
    return raw_map


def _require_record(path: Path | None, thread_id: str) -> tuple[dict, dict, Path]:
    goals = _load_raw_goals(path)
    rec = goals.get(thread_id)
    if not isinstance(rec, dict):
        raise NoGoalError("该线程无 goal 记录，请先 /goal <objective> 创建")
    return goals, rec, _resolve_path(path)


def _check_version(rec: dict, expected_goal_id: int | None) -> None:
    """乐观版本校验：expected = 调用方所知"现存记录"的 goal_id（无记录视为 0）。"""
    if expected_goal_id is None:
        return
    cur = _as_int(rec.get("goal_id", 0), 0)
    if cur != int(expected_goal_id):
        raise StaleGoalVersion(
            "goal 乐观版本不符：引用 goal_id=" + str(expected_goal_id)
            + "，磁盘为 " + str(cur) + "；请刷新引用后重试"
        )


def goal_set(
    path: Path | None = None,
    thread_id: str = "",
    objective: str = "",
    max_turns: int | None = None,
    expected_goal_id: int | None = None,
) -> Goal:
    """为该线程创建/新建目标（在途目标不可覆盖，一会话一目标）。

    - 已有记录 status ∈ (active, paused) → GoalExistsError
    - 已有记录 status ∈ 终态 → TerminalGoalError（须 /goal clear 后重建）
    - goal_id = 旧记录 goal_id + 1（无记录 = 1；clear 后 int 墓碑保持序列，下一次 = 最后 goal_id + 1）；
      expected_goal_id 为"调用方所知现存记录 goal_id"（认为无记录传 0），
      不匹配 → StaleGoalVersion
    - max_turns 缺省 DEFAULT_GOAL_MAX_TURNS；非数字 warning 回落；钳 [1, 9999]
    """
    obj = (objective or "").strip()
    if not obj:
        raise GoalError("goal 目标文本不能为空")
    goals = _load_raw_goals(path)
    target = _resolve_path(path)
    entry = goals.get(thread_id)
    prev = entry if isinstance(entry, dict) else None
    counter = entry if isinstance(entry, int) and not isinstance(entry, bool) else None
    goal_id = 1
    if prev is None:
        if counter is not None:
            goal_id = counter + 1
        if expected_goal_id is not None and int(expected_goal_id) != 0:
            raise StaleGoalVersion(
                "goal 乐观版本不符：该线程无 goal 记录（无记录=0），"
                + "但你引用了 goal_id=" + str(expected_goal_id) + "；请刷新引用后重试"
            )
    else:
        status = str(prev.get("status", GOAL_ACTIVE))
        _check_version(prev, expected_goal_id)
        if status in (GOAL_ACTIVE, GOAL_PAUSED):
            raise GoalExistsError(
                "该会话已有在途目标（status=" + status + "），一会话一目标；先 /goal pause 或 /goal clear，再 /goal <objective>"
            )
        if status in TERMINAL_STATUSES:
            raise TerminalGoalError(
                "该会话目标已终态（" + status + "）；先 /goal clear 再新建"
            )
        goal_id = _as_int(prev.get("goal_id", 0), 0) + 1
    n = DEFAULT_GOAL_MAX_TURNS
    if max_turns is not None:
        try:
            n = int(max_turns)
        except (TypeError, ValueError):
            logging.warning("goal_set max_turns 非数字，回落默认 %d: %r", DEFAULT_GOAL_MAX_TURNS, max_turns)
    n = max(1, min(n, 9999))
    goal = Goal(thread_id, goal_id, obj, GOAL_ACTIVE, 0, n)
    goals[thread_id] = goal.to_dict()
    _atomic_write(target, goals)
    return goal


def goal_pause(path: Path | None = None, thread_id: str = "", expected_goal_id: int | None = None) -> Goal:
    """active → paused；已 paused 显式报错；终态 → TerminalGoalError；无记录 → NoGoalError。"""
    goals, rec, target = _require_record(path, thread_id)
    status = str(rec.get("status", GOAL_ACTIVE))
    _check_version(rec, expected_goal_id)
    if status in TERMINAL_STATUSES:
        raise TerminalGoalError("goal 已终态（" + status + "），不可暂停；/goal clear 后重建")
    if status != GOAL_ACTIVE:
        raise GoalError("goal 已暂停，无需再 pause；继续请 /goal resume")
    rec["status"] = GOAL_PAUSED
    goals[thread_id] = rec
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


def goal_resume(path: Path | None = None, thread_id: str = "", expected_goal_id: int | None = None) -> Goal:
    """paused → active；已 active 显式报错；终态 → TerminalGoalError；无记录 → NoGoalError。"""
    goals, rec, target = _require_record(path, thread_id)
    status = str(rec.get("status", GOAL_ACTIVE))
    _check_version(rec, expected_goal_id)
    if status in TERMINAL_STATUSES:
        raise TerminalGoalError("goal 已终态（" + status + "），不可恢复；/goal clear 后重建")
    if status != GOAL_PAUSED:
        raise GoalError("goal 已 active，无需 resume")
    rec["status"] = GOAL_ACTIVE
    goals[thread_id] = rec
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


def goal_clear(path: Path | None = None, thread_id: str = "", expected_goal_id: int | None = None) -> Goal:
    """任意状态删除该线程 goal 记录（留 int 墓碑保持 goal_id +1 序列），返回被删 Goal；无记录 → NoGoalError。"""
    goals, rec, target = _require_record(path, thread_id)
    _check_version(rec, expected_goal_id)
    goals[thread_id] = _as_int(rec.get("goal_id", 0), 0)
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


def goal_status(path: Path | None = None, thread_id: str = "") -> Goal | None:
    """只读查询该线程 goal（无记录 → None，不报错）。"""
    rec = load_goals(path).get(thread_id)
    if rec is None:
        return None
    return Goal.from_dict(rec, thread_id)


def goal_complete(
    path: Path | None = None,
    thread_id: str = "",
    audit_evidence: str = "",
    expected_goal_id: int | None = None,
) -> Goal:
    """唯一 complete 写路径：active/paused → complete，记 audit_evidence + completed_at（UTC ISO）。

    evidence strip 后为空 → EvidenceRequiredError；终态 → TerminalGoalError；无记录 → NoGoalError。
    """
    evidence = (audit_evidence or "").strip()
    if not evidence:
        raise EvidenceRequiredError("complete 必须附审计证据（命令输出/测试结果/文件变更清单）；无证据不得标记完成")
    goals, rec, target = _require_record(path, thread_id)
    status = str(rec.get("status", GOAL_ACTIVE))
    _check_version(rec, expected_goal_id)
    if status in TERMINAL_STATUSES:
        raise TerminalGoalError("goal 已终态（" + status + "）；/goal clear 后重建")
    rec["status"] = GOAL_COMPLETE
    rec["completed_at"] = datetime.now(timezone.utc).isoformat()
    rec["audit_evidence"] = evidence
    goals[thread_id] = rec
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


def goal_mark_budget_exhausted(
    path: Path | None = None, thread_id: str = "", expected_goal_id: int | None = None
) -> Goal:
    """active/paused → budget_limited（预算轮结束后由前端调用；终态）。"""
    goals, rec, target = _require_record(path, thread_id)
    status = str(rec.get("status", GOAL_ACTIVE))
    _check_version(rec, expected_goal_id)
    if status in TERMINAL_STATUSES:
        raise TerminalGoalError("goal 已终态（" + status + "），不可再标 budget_limited")
    rec["status"] = GOAL_BUDGET_LIMITED
    goals[thread_id] = rec
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


def goal_note_turn(path: Path | None = None, thread_id: str = "") -> Goal:
    """turns_used = min(+1, max_turns)（续跑入队后调用）；无记录 → NoGoalError。"""
    goals, rec, target = _require_record(path, thread_id)
    m = _as_int(rec.get("max_turns", DEFAULT_GOAL_MAX_TURNS), DEFAULT_GOAL_MAX_TURNS)
    rec["turns_used"] = min(_as_int(rec.get("turns_used", 0), 0) + 1, m)
    goals[thread_id] = rec
    _atomic_write(target, goals)
    return Goal.from_dict(rec, thread_id)


# ---------------------------------------------------------------- 触发判定（纯函数）


@dataclass(frozen=True)
class ContinuationDecision:
    """自动续跑决策：kind ∈ {continuation, budget, none}。

    - continuation：常规续跑轮，prompt 为续跑轮输入
    - budget：末轮（收尾交接轮），prompt 为交接轮输入
    - none：不续跑，reason 为一句话说明
    """

    kind: str
    prompt: str | None = None
    reason: str | None = None
    new_turns_used: int | None = None


def should_continue(goal: Goal | None, turn, ctx: dict | None = None) -> bool:
    """该回合结束后是否自动续跑（全满足才续）：

    goal 非 None 且 status==active 且 turns_used<max_turns 且
    outcome ∉ (cancel, abandon) 且 tool_calls_count>0 且
    非 Plan 模式 且 无悬挂 HITL interrupt 且 非 sched-* 线程。
    turn 鸭子类型（.outcome/.tool_calls_count）；ctx 约定见模块 docstring。
    """
    if goal is None:
        return False
    if goal.status != GOAL_ACTIVE:
        return False
    if goal.turns_used >= goal.max_turns:
        return False
    if getattr(turn, "outcome", None) in ("cancel", "abandon"):
        return False
    if (getattr(turn, "tool_calls_count", 0) or 0) <= 0:
        return False
    ctx = ctx or {}
    if ctx.get("plan_mode"):
        return False
    if ctx.get("pending_interrupt"):
        return False
    if str(ctx.get("thread_id", "")).startswith("sched-"):
        return False
    return True


def continuation_decision(goal: Goal | None, turn, ctx: dict | None = None) -> ContinuationDecision:
    """should_continue 的富版本：给出 kind + prompt + new_turns_used。"""
    ctx = ctx or {}
    if goal is None:
        return ContinuationDecision("none", reason="无 goal")
    if goal.status != GOAL_ACTIVE:
        return ContinuationDecision("none", reason="goal 非 active（status=" + goal.status + "）")
    if goal.turns_used >= goal.max_turns:
        return ContinuationDecision("none", reason="预算已耗尽")
    if getattr(turn, "outcome", None) in ("cancel", "abandon"):
        return ContinuationDecision("none", reason="该轮 outcome=" + str(getattr(turn, "outcome", None)))
    if (getattr(turn, "tool_calls_count", 0) or 0) <= 0:
        return ContinuationDecision("none", reason="该轮零工具调用")
    if ctx.get("plan_mode"):
        return ContinuationDecision("none", reason="Plan 模式不续跑")
    if ctx.get("pending_interrupt"):
        return ContinuationDecision("none", reason="存在悬挂 HITL interrupt")
    if str(ctx.get("thread_id", "")).startswith("sched-"):
        return ContinuationDecision("none", reason="定时任务线程不续跑")
    next_used = min(goal.turns_used + 1, goal.max_turns)
    if goal.turns_used + 1 >= goal.max_turns:
        return ContinuationDecision("budget", prompt=budget_prompt(goal, next_used), new_turns_used=next_used)
    return ContinuationDecision("continuation", prompt=continuation_prompt(goal, next_used), new_turns_used=next_used)


def continuation_prompt(goal: Goal, next_turns_used: int | None = None) -> str:
    """自动续跑轮输入（codex continuation.md 纪律移植）。"""
    n = goal.turns_used + 1 if next_turns_used is None else int(next_turns_used)
    return (
        "[目标续跑 {0}/{1}] 自动续跑目标「{2}」。纪律：\n"
        "1) 逐条审计目标：哪些条目已完成（附证据）、哪些未完成；\n"
        "2) 对未完成部分继续执行——微调参数≠换方案，harness 拦截的命令不许重发；不做目标外工作；\n"
        "3) 全部条目达成后必须调用 complete_goal 并附审计证据（命令输出/测试结果/文件变更清单），无证据不得标记完成；\n"
        "4) 若确实没有可执行动作则本轮不发起工具调用（自动续跑链自然终止）。".format(
            n, goal.max_turns, goal.objective
        )
    )


def budget_prompt(goal: Goal, next_turns_used: int | None = None) -> str:
    """预算耗尽末轮（收尾交接轮）输入（codex budget_limit.md 纪律移植）。"""
    n = goal.turns_used + 1 if next_turns_used is None else int(next_turns_used)
    return (
        "[目标预算耗尽 {0}/{1}] 最后一续跑轮（收尾交接轮）。纪律：\n"
        "1) 禁止开新工作：不开新任务、不写新文件、不执行新命令；\n"
        "2) 产出结构化交接：\n"
        "## 已完成\n（逐条 + 证据：命令输出/测试结果/文件变更清单）\n"
        "## 未完成\n（逐条 + 原因 + 下一步）\n"
        "## 下一步\n（具体命令/文件清单，人可直接执行）\n"
        "3) 若目标实际已全部达成，仍可调用 complete_goal 并附审计证据。".format(
            n, goal.max_turns
        )
    )

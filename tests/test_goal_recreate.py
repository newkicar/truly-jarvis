"""#33: 终态 /goal <objective> 自动关旧建新 + 在途拒绝指路 /goal edit（红绿切片）。

工单: 终态下 /goal <新目标> = 自动关闭旧 goal（int 墓碑保留 goal_id 序列）并新建、kick 新目标；
非终态（active/paused）维持拒绝 + 指路 /goal edit 基线（弹窗属 #34，本单不实现）。
验收（spec .scratch/javis-goal/spec.md #33 行）：AC1 无记录不变 / AC2 complete / AC3 budget_limited /
AC4 在途拒绝指路 / AC5 create 与 edit 分支互不串。
目录纪律: os.makedirs 自建目录（tmp_path 禁用，WinError5 中毒先例）。
"""
from src import commands
from src import goals as g
from tests._goal_harness import goal_tmp as _goal_tmp


# AC1（回归）：无记录 → 新建 + kick，行为不变
def test_goal_set_no_record_creates_and_kicks():
    with _goal_tmp("recreate-none") as d:
        p = d / "goals.json"
        out = commands.goal_command_text("t1", "/goal status report", p)
        assert out.startswith("目标已创建：'status report'")
        kick = commands.goal_kick_prompt("t1", "/goal status report", p)
        assert kick is not None
        assert kick.startswith("[目标续跑 1/5]")
        assert "自动续跑目标「status report」" in kick


# AC2：complete 终态 → 自动关旧建新 + kick 新目标（无需手动 /goal clear）
def test_goal_set_terminal_complete_auto_recreates():
    with _goal_tmp("recreate-complete") as d:
        p = d / "goals.json"
        commands.goal_command_text("t1", "/goal A", p)
        g.goal_complete(path=p, thread_id="t1", audit_evidence="done")
        out = commands.goal_command_text("t1", "/goal C", p)
        assert "已关闭旧目标" in out
        assert "已完成" in out
        assert "'A'" in out
        assert "并新建" in out
        assert "'C'" in out
        cur = g.goal_status(path=p, thread_id="t1")
        assert cur is not None
        assert cur.status == g.GOAL_ACTIVE
        assert cur.goal_id == 2  # int 墓碑保留序列（旧 1 → 新 2）
        assert cur.turns_used == 0
        assert cur.objective == "C"
        kick = commands.goal_kick_prompt("t1", "/goal C", p)
        assert kick is not None
        assert kick.startswith("[目标续跑 1/5]")
        assert "自动续跑目标「C」" in kick


# AC3：budget_limited 终态 → 自动关旧建新 + kick 新目标
def test_goal_set_terminal_budget_limited_auto_recreates():
    with _goal_tmp("recreate-budget") as d:
        p = d / "goals.json"
        commands.goal_command_text("t1", "/goal A", p)
        g.goal_mark_budget_exhausted(path=p, thread_id="t1")
        out = commands.goal_command_text("t1", "/goal D", p)
        assert "已关闭旧目标" in out
        assert "回合预算耗尽" in out
        assert "并新建" in out
        assert "'D'" in out
        cur = g.goal_status(path=p, thread_id="t1")
        assert cur is not None
        assert cur.status == g.GOAL_ACTIVE
        assert cur.objective == "D"
        kick = commands.goal_kick_prompt("t1", "/goal D", p)
        assert kick is not None
        assert "自动续跑目标「D」" in kick


# AC4：在途（active/paused）→ 维持拒绝基线 + 指路 /goal edit（弹窗属 #34，不实现）
def test_goal_set_inflight_rejected_edit_hint():
    with _goal_tmp("recreate-inflight") as d:
        p = d / "goals.json"
        commands.goal_command_text("t1", "/goal A", p)
        out = commands.goal_command_text("t1", "/goal B", p)
        assert "目标已存在（进行中：'A'）" in out
        assert "/goal edit 变更目标" in out
        assert "/goal clear 替换" in out
        cur = g.goal_status(path=p, thread_id="t1")
        assert cur is not None and cur.objective == "A"  # 旧目标未动
        g.goal_pause(path=p, thread_id="t1")
        out2 = commands.goal_command_text("t1", "/goal B", p)
        assert "目标已存在（已暂停" in out2
        assert "/goal edit 变更目标" in out2


# AC5（回归）：create 与 edit 分支互不串——clear 留 int 墓碑后 /goal edit 走 edit 分支（无目标文案）
def test_goal_create_objective_branch_regression():
    with _goal_tmp("recreate-regression") as d:
        p = d / "goals.json"
        commands.goal_command_text("t1", "/goal A", p)
        out = commands.goal_command_text("t1", "/goal clear", p)
        assert "目标已清除" in out
        out2 = commands.goal_command_text("t1", "/goal edit the docs", p)
        assert "本会话无目标，无需变更" in out2
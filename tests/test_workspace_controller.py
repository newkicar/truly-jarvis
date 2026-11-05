"""工单 05 — WorkspaceController（注册表 + 切项目 + 打开/新建，用假 runtime factory，不碰真模型）。"""
from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace

from tests.gui_fakes import TEST_ROOT
from src.gui.events import UiBridge
from src.gui.project_registry import ProjectRegistry
from src.gui.workspace_controller import WorkspaceController


def _home() -> "tuple":
    d = TEST_ROOT / f"wctrl-{uuid.uuid4().hex[:10]}"
    d.mkdir(parents=True)
    return d, lambda: shutil.rmtree(d, ignore_errors=True)


class FakeSchedGate:
    """假调度器门：记录 shutdown 调用（真值 = SchedulerGate.shutdown 停调度器）。"""

    def __init__(self):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class FakeRT:
    def __init__(self, root):
        self.config = SimpleNamespace(project_root=root)
        self.closed = False
        self.gate = FakeSchedGate()

    def close(self):
        self.closed = True


def _ctrl(d, root):
    reg = ProjectRegistry(d / "projects.json")
    rt = FakeRT(root)
    made: list = []

    def factory(r):
        f = FakeRT(r)
        made.append(f)
        return f

    reg.add(root, now=1.0)
    ctrl = WorkspaceController(reg, factory, UiBridge())
    return reg, ctrl, made, rt


def test_switch_builds_repoints_and_closes_old():
    d, clean = _home()
    try:
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        reg, ctrl, made, _ = _ctrl(d, a)
        p1 = ctrl.switch_project(a)
        assert ctrl.presenter is p1 and ctrl.active_root() == a.resolve()
        assert reg.active() == str(a.resolve())
        p2 = ctrl.switch_project(b)
        assert ctrl.presenter is p2 and ctrl.active_root() == b.resolve()
        assert len(made) == 2 and made[0].closed is True  # 旧的被关
        assert made[1].closed is False
    finally:
        clean()


def test_open_dir_resolves_inits_registers():
    d, clean = _home()
    try:
        bare = d / "bare"
        bare.mkdir()
        reg, ctrl, _made, _ = _ctrl(d, d / "a")
        (d / "a").mkdir()
        root = ctrl.open_dir(bare)
        assert (bare / "jarvis.json").is_file()  # 缺配置 → 骨架
        assert reg.get(root) is not None
        assert reg.active() == str(root)
    finally:
        clean()


def test_new_dir_creates_scaffolds_registers():
    d, clean = _home()
    try:
        reg, ctrl, _m, _ = _ctrl(d, d / "a")
        (d / "a").mkdir()
        root = ctrl.new_dir("工程X", d)
        assert root == (d / "工程X").resolve()
        assert (root / "jarvis.json").is_file()
        assert reg.get(root)["name"] == "工程X"
    finally:
        clean()


def test_sessions_for_inactive_reads_readonly():
    d, clean = _home()
    try:
        a = d / "a"; a.mkdir()
        reg, ctrl, _m, _ = _ctrl(d, a)
        b = d / "b"; b.mkdir()
        reg.add(b, now=2.0)
        got = ctrl.sessions_for(b)  # b 非活动 → 只读（无 checkpoint 库 → 空）
        assert got == []
    finally:
        clean()


def test_project_node_ops_delegate_to_registry():
    d, clean = _home()
    try:
        a = d / "a"; a.mkdir()
        reg, ctrl, _m, _ = _ctrl(d, a)
        assert ctrl.project_name(a) == "a"
        ctrl.rename_project(a, "甲")
        assert ctrl.project_name(a) == "甲"
        assert ctrl.project_pinned(a) is False
        ctrl.set_project_pinned(a, True)
        assert ctrl.project_pinned(a) is True
        ctrl.remove_project(a)
        assert reg.entries() == []
        assert a.exists()  # 只删登记，不删项目
    finally:
        clean()


def test_remove_project_releases_runtime_and_reuses_open_one():
    """移除活动项目 = 解除占用：取消进行中回合 + 清队列 + 关 runtime（停调度器/释放连接）+
    删注册表项；项目文件不碰。活动重指向 = 优先复用未关 runtime（零重建）。"""
    d, clean = _home()
    try:
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        (a / "jarvis.json").write_text("{}", encoding="utf-8")
        (b / "jarvis.json").write_text("{}", encoding="utf-8")
        reg, ctrl, made, _ = _ctrl(d, a)
        reg.add(b, now=2.0)

        pa = ctrl.switch_project(a)
        assert pa.gate.try_start("ta", "x") == "started"      # a 后台在跑（ADR-0010 busy 保留）
        pb = ctrl.switch_project(b)                            # b 活动；a busy 不被 close_idle 关
        assert len(made) == 2 and made[0].closed is False
        assert pb.gate.try_start("tb", "y") == "started"      # b 在跑
        assert pb.gate.try_start("tb", "q1") == "queued"      # 排队消息 ×2
        assert pb.gate.try_start("tb", "q2") == "queued"

        got = ctrl.remove_project(b)

        # ① 注册表：b 删、a 留
        assert reg.get(b) is None and reg.get(a) is not None
        # ② 项目文件一律不碰
        assert (b / "jarvis.json").is_file()
        # ③ b 的回合被取消（drain）+ 排队消息全清
        assert pb.gate.is_cancelled("tb") is True
        assert pb.gate.queued_count("tb") == 0
        assert pb.gate.queued_texts("tb") == []
        # ④ b 的 runtime 已关（调度器 shutdown + 连接释放），presenter 摘除
        eb = ctrl._manager.runtimes.get(b)
        assert eb.runtime.closed is True and eb.presenter is None
        assert eb.runtime.gate.shutdown_calls == 1
        # ⑤ 活动重指向 = a（未关 runtime 复用，工厂不再被调）
        assert got == a.resolve()
        assert ctrl.presenter is None and ctrl.active_root() is None  # UI 切换前
        pa2 = ctrl.switch_project(got)      # UI 的 _do_switch_project 走完整切换
        assert len(made) == 2               # 零重建
        assert ctrl.presenter is pa and ctrl.active_root() == a.resolve()
        # a 的后台回合不受 b 的移除影响
        assert pa2.gate.is_running("ta") is True and pa2.gate.is_cancelled("ta") is False
    finally:
        clean()


def test_remove_active_project_without_next_returns_none():
    """移除活动项目且无其他项目 → None（UI 落空态）；runtime 资源全量释放。"""
    d, clean = _home()
    try:
        a = d / "a"; a.mkdir()
        (a / "jarvis.json").write_text("{}", encoding="utf-8")
        reg, ctrl, _m, _ = _ctrl(d, a)
        pa = ctrl.switch_project(a)
        assert pa.gate.try_start("ta", "x") == "started"

        assert ctrl.remove_project(a) is None
        # 空态：presenter / 活动根 / runtime 活动指针 全清
        assert ctrl.presenter is None
        assert ctrl.active_root() is None
        assert ctrl._manager.runtimes.active_key() is None
        # 资源释放：runtime 关、调度器停、回合取消
        ea = ctrl._manager.runtimes.get(a)
        assert ea.runtime.closed is True and ea.presenter is None
        assert ea.runtime.gate.shutdown_calls == 1
        assert pa.gate.is_cancelled("ta") is True
        # 项目文件不碰
        assert (a / "jarvis.json").is_file()
    finally:
        clean()


def test_remove_inactive_project_keeps_active_and_returns_it():
    """移除非活动项目：活动项目不受影响，返回当前活动根（UI 切换早退无操作）。"""
    d, clean = _home()
    try:
        a, b = d / "a", d / "b"
        a.mkdir(); b.mkdir()
        (b / "jarvis.json").write_text("{}", encoding="utf-8")
        reg, ctrl, _m, _ = _ctrl(d, a)      # a 只登记（无 runtime、无 jarvis.json = 陈旧项）
        reg.add(b, now=2.0)
        ctrl.switch_project(b)              # b 活动

        got = ctrl.remove_project(a)
        assert got == ctrl.active_root()    # 活动不变
        assert reg.get(a) is None and reg.get(b) is not None
        eb = ctrl._manager.runtimes.get(b)
        assert eb.runtime.closed is False    # 活动 runtime 未受影响
    finally:
        clean()


def test_static_workspace_remove_project_noop_returns_root():
    """StaticWorkspace（单项目无注册表）：移除 = no-op，返回当前根（契约与多项目版一致）。"""
    from types import SimpleNamespace

    from src.gui.workspace_controller import StaticWorkspace

    d, clean = _home()
    try:
        r = d / "solo"; r.mkdir()
        pres = SimpleNamespace(
            runtime=SimpleNamespace(config=SimpleNamespace(project_root=str(r))),
            gate=SimpleNamespace(running_threads=lambda: []),
        )
        ws = StaticWorkspace(pres, UiBridge())
        assert ws.remove_project(r) == r
    finally:
        clean()

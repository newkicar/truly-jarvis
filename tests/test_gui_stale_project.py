"""陈旧项目启动落空态回归（gui_main 的 jarvis.json 被删/目录已移场景）。

契约：
- 启动路径：pick_launch 跳过「目录还在但 jarvis.json 已删」的条目（不删条目、不自动重建文件）；
- 手动切项目（controller.switch_project）：用户发起 → init_project 重建骨架后再切；
- MainWindow(presenter=None) 空态：构造/刷新/提交/新会话按钮均不崩，输入区禁用。

纪律：offscreen；不用 tmp_path（pytest-of-uida0712 基目录 WinError 5 中毒），
目录自建在 .scratch/gui-test-tmp/<uuid>/ 并 finally rmtree。
陈旧判例须 >=5 层深链：仓库根有 jarvis.json，浅测试目录向上 4 级会误判有效。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.project_registry import ProjectRegistry
from src.gui.runtime import GuiPresenter
from src.gui.workspace import jarvis_project_root_of
from src.gui.workspace_controller import WorkspaceController
from tests.gui_fakes import TEST_ROOT


def _stale_dir(base: Path, name: str) -> Path:
    """>=5 层深链目录（base/a/b/c/d/name）：自身与上 4 级内均无 jarvis.json。"""
    d = base / "a" / "b" / "c" / "d" / name
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def base():
    b = TEST_ROOT / f"stale-{uuid.uuid4().hex[:8]}"
    b.mkdir(parents=True)
    try:
        yield b
    finally:
        shutil.rmtree(b, ignore_errors=True)


# ---- 1. jarvis_project_root_of：有效性判定（目录 or 上 4 级内有 jarvis.json）


def test_root_of_missing_dir_is_none():
    assert jarvis_project_root_of(TEST_ROOT / "no-such-dir-xyz") is None


def test_root_of_dir_with_jarvis_json(base: Path):
    p = base / "proj"
    p.mkdir()
    (p / "jarvis.json").write_text("{}", encoding="utf-8")
    assert jarvis_project_root_of(p) == p


def test_root_of_finds_ancestor_jarvis_json(base: Path):
    # jarvis.json 在 3 级祖先 → 判为该祖先（子目录误登记时回落到项目根）
    (base / "jarvis.json").write_text("{}", encoding="utf-8")
    z = base / "x" / "y" / "z"
    z.mkdir(parents=True)
    assert jarvis_project_root_of(z) == base


def test_root_of_stale_deep_chain_is_none(base: Path):
    stale = _stale_dir(base, "stale")
    assert jarvis_project_root_of(stale) is None


# ---- 2. pick_launch：陈旧条目跳过（不删条目、不重建文件），全无效 → None


def test_pick_launch_skips_stale_returns_healthy(base: Path):
    stale = _stale_dir(base, "stale")
    healthy = base / "healthy"
    healthy.mkdir()
    (healthy / "jarvis.json").write_text("{}", encoding="utf-8")
    reg = ProjectRegistry(base / "projects.json")
    reg.add(healthy, now=1.0)
    reg.add(stale, now=5.0)  # 更「最近」→ ordered() 排前，须被跳过
    entry = reg.pick_launch()
    assert entry is not None
    assert Path(str(entry["path"])).resolve() == healthy.resolve()
    # 不自动重建文件
    assert not (stale / "jarvis.json").exists()
    # 不删除陈旧条目
    paths = [Path(str(e["path"])) for e in reg.entries()]
    assert stale.resolve() in paths


def test_pick_launch_all_invalid_returns_none(base: Path):
    stale = _stale_dir(base, "s1")
    missing = base / "gone"  # 目录已移（不存在）
    reg = ProjectRegistry(base / "projects.json")
    reg.add(missing, now=9.0)
    reg.add(stale, now=1.0)
    assert reg.pick_launch() is None
    # 两条目都保留（跳过语义，非清理语义）
    paths = [Path(str(e["path"])) for e in reg.entries()]
    assert stale.resolve() in paths and missing.resolve() in paths


# ---- 3. MainWindow(None, ...) 空态：不崩 + 输入区禁用 + 操作有提示


class _EmptyFakeWS:
    """空工作区 fake（presenter=None 场景）：接口面与 _FakeMultiWS 对齐。"""

    def __init__(self, bridge):
        self.presenter = None
        self.bridge = bridge

    def projects(self):
        return []

    def sessions_for(self, root):
        return []

    def active_root(self):
        return None

    def recent(self):
        return []

    def switch_project(self, root, proceed_if_running=None):
        return None

    def pick_start(self, root):
        return None

    def set_last_active(self, root, tid):
        pass

    def has_running(self):
        return False

    def new_dir(self, name, parent):
        return Path(parent) / name

    def open_dir(self, chosen, up_to=None):
        return Path(str(chosen))

    def project_name(self, root):
        return Path(str(root)).name

    def rename_project(self, root, name):
        pass

    def project_pinned(self, root):
        return False

    def set_project_pinned(self, root, on):
        pass

    def remove_project(self, root):
        pass


def test_mainwindow_empty_state_no_crash(qapp):
    bridge = UiBridge()
    ws = _EmptyFakeWS(bridge)
    win = MainWindow(None, bridge, workspace=ws)
    win.show()
    qapp.processEvents()
    assert win.presenter is None
    assert win.input_bar.edit.isEnabled() is False
    assert win.input_bar.btn_send.isEnabled() is False
    # 空态操作不崩
    win.refresh_tree()
    win._submit()
    assert "还没有关联项目" in win.status_label.text()
    win._on_new_session_clicked()
    assert "还没有关联项目" in win.status_label.text()
    win.close()


# ---- 4. 真 controller：手动切陈旧根 → 重建骨架后再切（菜单语义）


def test_switch_project_stale_root_rebuilds_and_switches(qapp):
    d = TEST_ROOT / f"stalectrl-{uuid.uuid4().hex[:8]}"
    stale = d / "a" / "b" / "c" / "dd" / "ee"
    stale.mkdir(parents=True)
    try:

        class FR:
            def __init__(self, root):
                self.config = SimpleNamespace(
                    project_root=root, mcps={}, model_label="fake", vault_path=None
                )
                self.agent = None
                self.permission_state = {}
                self.mcp_tool_count = 0
                self.closed = False

            def close(self):
                self.closed = True

        reg = ProjectRegistry(d / "projects.json")
        bridge = UiBridge()
        ctrl = WorkspaceController(reg, lambda r: FR(r), bridge)
        pres = ctrl.switch_project(stale)
        assert isinstance(pres, GuiPresenter)
        # 骨架已重建（jarvis.json + schedules/）
        assert (stale / "jarvis.json").is_file()
        assert (stale / "schedules").is_dir()
        assert ctrl._manager.active_root == stale.resolve()
        ctrl.shutdown()
    finally:
        shutil.rmtree(d, ignore_errors=True)
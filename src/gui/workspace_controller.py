"""工作区控制器（GUI 侧「切项目 + 项目/会话数据」的接口）。

MainWindow 只依赖这套接口（不关心单项目还是多项目）：
- 单项目（旧路径 / 无注册表）= `StaticWorkspace`（包一个固定 presenter，不切项目）。
- 多项目（工单 05）= `WorkspaceController`（注册表 + WorkspaceManager + runtime 工厂，切项目=关旧建新）。

MainWindow 通过 `.presenter`（活动项目的 presenter）读数据、通过 `.switch_project`/`.pick_start`
切项目；会话切换仍走既有的 `_switch_to`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.gui.workspace import (
    WorkspaceManager,
    list_sessions_readonly,
    new_project,
    open_project,
    pick_start_session,
    resolve_open_root,
)
from src.gui.project_registry import ProjectRegistry


class StaticWorkspace:
    """单项目工作区：包一个固定 presenter（config.project_root），不做项目切换。"""

    def __init__(self, presenter, bridge) -> None:
        self._presenter = presenter
        self._bridge = bridge
        self._root = Path(presenter.runtime.config.project_root)

    @property
    def presenter(self):
        return self._presenter

    @property
    def bridge(self):
        return self._bridge

    def projects(self) -> list[tuple[Path, str, bool]]:
        return [(self._root, self._root.name, False)]

    def sessions_for(self, root: Any) -> list[tuple[str, str]]:
        if Path(str(root)) == self._root:
            p = self._presenter
            return [(t, p.session_label(t)) for t in p.session_ids()]
        return []

    def active_root(self) -> Path | None:
        return self._root

    def recent(self) -> list[tuple[Path, str]]:
        return [(r, n) for (r, n, _p) in self.projects()]

    def switch_project(self, root: Any, *, proceed_if_running=None) -> Any:
        """单项目：返回同一 presenter（MainWindow 见 `presenter is current` 即 no-op）。"""
        return self._presenter

    def pick_start(self, root: Any) -> str | None:
        return None

    def set_last_active(self, root: Any, tid: str) -> None:
        pass

    def has_running(self) -> bool:
        return bool(self._presenter.gate.running_threads())

    # ---- 项目节点操作（单项目：多为 no-op；多项目版经注册表落地）
    def project_name(self, root: Any) -> str:
        return Path(str(root)).name

    def rename_project(self, root: Any, name: str) -> None:
        pass

    def project_pinned(self, root: Any) -> bool:
        return False

    def set_project_pinned(self, root: Any, on: bool) -> None:
        pass

    def remove_project(self, root: Any) -> None:
        pass

    # ---- 打开/新建（单项目无注册表：只做解析+骨架，登记/切换为 no-op，避免菜单崩）
    def resolve_root(self, chosen_dir: Any, *, up_to: Any = None):
        from src.gui.workspace import resolve_open_root

        return resolve_open_root(chosen_dir, up_to=up_to)

    def open_dir(self, chosen_dir: Any, *, up_to: Any = None, now: float | None = None) -> Path:
        from src.gui.workspace import init_project, resolve_open_root

        d = resolve_open_root(chosen_dir, up_to=up_to)
        if d.needs_init:
            init_project(d.root)
        return d.root

    def new_dir(self, name: str, parent_dir: Any, *, now: float | None = None) -> Path:
        from src.gui.workspace import init_project

        root = (Path(str(parent_dir)).expanduser().resolve() / str(name)).resolve()
        root.mkdir(parents=True, exist_ok=True)
        init_project(root)
        return root


class WorkspaceController:
    """多项目工作区（工单 05）：注册表 + WorkspaceManager + runtime 工厂。

    切项目 = 关旧 runtime、为新项目根建新 runtime + presenter、置活动。
    runtime_factory(root) -> runtime（须有 .close()；真值 = gui_main 用 build_runtime 造）。
    实现 StaticWorkspace 同款接口，MainWindow 对单/多项目一视同仁。
    """

    def __init__(self, registry: ProjectRegistry, runtime_factory, bridge, *, card_factory=None) -> None:
        self.registry = registry
        self._runtime_factory = runtime_factory
        self.bridge = bridge
        self._card_factory = card_factory
        self._presenter = None
        self._manager = WorkspaceManager(registry, self._build_runtime, is_running=self._has_running)
        self._current_root: Path | None = None

    def _build_runtime(self, root):
        runtime = self._runtime_factory(root)
        from src.gui.presenter_wiring import wire_presenter

        self._presenter = wire_presenter(
            runtime, self.bridge, card_factory=self._card_factory if self._card_factory is not None else None
        )
        self._current_root = Path(str(root))
        return runtime

    def _has_running(self) -> bool:
        return self._presenter is not None and bool(self._presenter.gate.running_threads())

    @property
    def presenter(self):
        return self._presenter

    def active_root(self):
        return self._current_root

    # ---- 数据（MainWindow 读）
    def projects(self) -> list[tuple[Path, str, bool]]:
        out: list[tuple[Path, str, bool]] = []
        for e in self.registry.ordered():
            r = Path(str(e["path"]))
            out.append((r, str(e.get("name") or r.name), bool(e.get("pinned", False))))
        return out

    def recent(self) -> list[tuple[Path, str]]:
        return [(r, n) for (r, n, _p) in self.projects()]

    def sessions_for(self, root: Any) -> list[tuple[str, str]]:
        r = Path(str(root))
        if self._current_root is not None and r == self._current_root:
            p = self._presenter
            return [(t, p.session_label(t)) for t in p.session_ids()]
        return list_sessions_readonly(r)

    def pick_start(self, root: Any) -> str | None:
        available = [t for (t, _n) in self.sessions_for(root)]
        return pick_start_session(self.registry, root, available)

    # ---- 切换
    def switch_project(self, root: Any, *, proceed_if_running=None) -> Any:
        res = self._manager.switch_to(root, proceed_if_running=proceed_if_running)
        if res is None:
            return None
        return self._presenter

    def set_last_active(self, root: Any, tid: str) -> None:
        if root is None:
            return
        self.registry.set_last_active_thread(Path(str(root)), tid)

    def has_running(self) -> bool:
        return self._has_running()

    # ---- 项目增删（菜单用）
    def open_dir(self, chosen_dir: Any, *, up_to: Any = None, now: float | None = None) -> Path:
        """打开目录：判定根 +（需时）骨架 + 登记。返回项目根（UI 再 switch_project）。"""
        return open_project(self.registry, chosen_dir, now=now, up_to=up_to)

    def new_dir(self, name: str, parent_dir: Any, *, now: float | None = None) -> Path:
        """新建项目：建 <父>/<名> + 骨架 + 登记。返回项目根（UI 再 switch_project）。"""
        return new_project(self.registry, name, parent_dir, now=now)

    def resolve_root(self, chosen_dir: Any, *, up_to: Any = None):
        return resolve_open_root(chosen_dir, up_to=up_to)

    # ---- 项目节点操作（委托注册表）
    def project_name(self, root: Any) -> str:
        e = self.registry.get(root)
        return str((e or {}).get("name") or Path(str(root)).name)

    def rename_project(self, root: Any, name: str) -> None:
        self.registry.rename(Path(str(root)), name)

    def project_pinned(self, root: Any) -> bool:
        return bool((self.registry.get(root) or {}).get("pinned", False))

    def set_project_pinned(self, root: Any, on: bool) -> None:
        self.registry.set_pinned(Path(str(root)), on)

    def remove_project(self, root: Any) -> None:
        self.registry.remove(Path(str(root)))

    def shutdown(self) -> None:
        """app 收尾：关当前 runtime（释放 checkpointer 连接 + 停调度器）。"""
        rt = self._manager.current
        if rt is None:
            return
        gate = getattr(rt, "gate", None)
        if gate is not None:
            gate.shutdown()
        rt.close()

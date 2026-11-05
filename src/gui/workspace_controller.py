"""工作区控制器（GUI 侧「切项目 + 项目/会话数据」的接口）。

MainWindow 只依赖这套接口（不关心单项目还是多项目）：
- 单项目（旧路径 / 无注册表）= `StaticWorkspace`（包一个固定 presenter，不切项目）。
- 多项目（工单 05）= `WorkspaceController`（注册表 + WorkspaceManager + runtime 工厂，切项目=复用/新建 entry 置活动，busy 后台续跑）。

MainWindow 通过 `.presenter`（活动项目的 presenter）读数据、通过 `.switch_project`/`.pick_start`
切项目；会话切换仍走既有的 `_switch_to`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.gui.workspace import (
    WorkspaceManager,
    init_project,
    jarvis_project_root_of,
    list_sessions_readonly,
    new_project,
    open_project,
    pick_start_session,
    resolve_open_root,
)
from src.gui.project_registry import ProjectRegistry
from src.gui.runtime_registry import normalize_root_key

from src.gui.presenter_wiring import wire_presenter


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

    def running_sessions(self, root: Any) -> list[str]:
        """List of thread ids currently running under this project root (#6: session tree background-running marker)."""
        if Path(str(root)) == self._root:
            return list(self._presenter.gate.running_threads())
        return []

    # ---- 项目节点操作（单项目：多为 no-op；多项目版经注册表落地）
    def project_name(self, root: Any) -> str:
        return Path(str(root)).name

    def rename_project(self, root: Any, name: str) -> None:
        pass

    def project_pinned(self, root: Any) -> bool:
        return False

    def set_project_pinned(self, root: Any, on: bool) -> None:
        pass

    def remove_project(self, root: Any) -> Path | None:
        """单项目无注册表：移除是 no-op（契约与多项目版一致：返回当前活动根，UI 切换=早退无操作）。"""
        return self._root

    # ---- 打开/新建（单项目无注册表：只做解析+骨架，登记/切换为 no-op，避免菜单崩）
    def resolve_root(self, chosen_dir: Any):
        from src.gui.workspace import resolve_open_root

        return resolve_open_root(chosen_dir)

    def open_dir(self, chosen_dir: Any, *, now: float | None = None) -> Path:
        from src.gui.workspace import init_project, resolve_open_root

        d = resolve_open_root(chosen_dir)
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

    切项目 = 复用/新建该项目 entry + 置活动（ADR-0010：busy runtime 后台续跑，只关 idle）。
    runtime_factory(root) -> runtime（须有 .close()；真值 = gui_main 用 build_runtime 造）。
    实现 StaticWorkspace 同款接口，MainWindow 对单/多项目一视同仁。
    """

    def __init__(self, registry: ProjectRegistry, runtime_factory, bridge, *, card_factory=None) -> None:
        self.registry = registry
        self._runtime_factory = runtime_factory
        self.bridge = bridge
        self._card_factory = card_factory
        self._presenter = None
        self._manager = WorkspaceManager(registry, self._runtime_factory)  # ADR-0010：每项目 entry 后台续跑
        self._current_root: Path | None = None


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
        e = self._manager.runtimes.get(r)
        if e is not None and e.presenter is not None and not getattr(e.runtime, "closed", False):
            try:
                return [(t, e.presenter.session_label(t)) for t in e.presenter.session_ids()]
            except Exception:
                return list_sessions_readonly(r)
        return list_sessions_readonly(r)

    def pick_start(self, root: Any) -> str | None:
        available = [t for (t, _n) in self.sessions_for(root)]
        return pick_start_session(self.registry, root, available)

    # ---- 切换
    def switch_project(self, root: Any, *, proceed_if_running=None) -> Any:
        # 陈旧根（用户点树/打开项目时 jarvis.json 已被删）= 用户发起 → 重建骨架后再切
        # （与「打开项目/新建项目」菜单语义一致，区别于启动路径的「落空态、绝不自动重建」）。
        # OSError（网络盘不可达、权限等）→ 不切，返回 None。
        if jarvis_project_root_of(root) is None:
            try:
                init_project(Path(str(root)))
            except OSError:
                return None
        # ADR-0010：切走不再取消后台（busy runtime 保留），switch_to 恒返回目标 runtime；
        # proceed_if_running kwarg 遗留（新实现忽略）。
        self._manager.switch_to(root, proceed_if_running=proceed_if_running)
        e = self._manager.runtimes.get(Path(str(root)))
        if e is not None and e.presenter is None:
            try:
                e.presenter = wire_presenter(
                    e.runtime, self.bridge,
                    card_factory=self._card_factory if self._card_factory is not None else None,
                )
            except Exception:
                e.presenter = None
        self._presenter = e.presenter if e is not None else None
        self._current_root = Path(e.root) if e is not None else None
        return self._presenter

    def set_last_active(self, root: Any, tid: str) -> None:
        if root is None:
            return
        self.registry.set_last_active_thread(Path(str(root)), tid)

    def has_running(self) -> bool:
        return self._has_running()

    def running_sessions(self, root: Any) -> list[str]:
        """List of thread ids currently running under this project root (#6: session tree background-running marker)."""
        r = Path(str(root))
        e = self._manager.runtimes.get(r)
        if e is not None and e.presenter is not None and not getattr(e.runtime, "closed", False):
            try:
                return list(e.presenter.gate.running_threads())
            except Exception:
                return []
        return []

    # ---- 项目增删（菜单用）
    def open_dir(self, chosen_dir: Any, *, now: float | None = None) -> Path:
        """打开目录：判定根 +（需时）骨架 + 登记。返回项目根（UI 再 switch_project）。"""
        return open_project(self.registry, chosen_dir, now=now)

    def new_dir(self, name: str, parent_dir: Any, *, now: float | None = None) -> Path:
        """新建项目：建 <父>/<名> + 骨架 + 登记。返回项目根（UI 再 switch_project）。"""
        return new_project(self.registry, name, parent_dir, now=now)

    def resolve_root(self, chosen_dir: Any):
        return resolve_open_root(chosen_dir)

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

    def remove_project(self, root: Any) -> Path | None:
        """从列表移除 + 解除项目占用（项目文件**一律不碰**，用户随后可自由删文件夹）。

        步骤：① 删注册表项 → ② 取消该项目全部进行中回合（drain 语义：当前步骤跑完即停、
        后续步骤跳过；停车中的审批卡片被唤醒放弃）→ ③ 清空该项目全部消息队列
        （排队消息随项目一起放弃）→ ④ 关 runtime（停调度器 + 释放 checkpointer 持久
        sqlite 连接——Windows「文件夹被占用删不掉」的锁源）→ ⑤ 若被移除的是活动项目：
        选下一个活动项目并返回其根（UI 侧走完整切换），没有则返回 None（UI 落空态）；
        移除的是非活动项目：返回当前活动根（UI 切换=无操作早退）。

        与 ADR-0010「切走保留 busy runtime 后台续跑」的区别：移除 = 用户显式放弃该项目，
        资源全量释放（进行中的回合被取消，不再后台续跑）。
        """
        r = Path(str(root))
        self.registry.remove(r)
        entry = self._manager.runtimes.get(r)
        if entry is not None:
            pres = entry.presenter
            if pres is not None:
                for tid in pres.gate.running_threads():
                    pres.cancel(tid)
                pres.gate.clear_all_queues()
            entry.close()
            entry.presenter = None
        k = normalize_root_key(r)
        was_active = self._current_root is not None and normalize_root_key(self._current_root) == k
        if was_active:
            self._manager.runtimes.deactivate()
            self._presenter = None
            self._current_root = None
            return self._pick_next_active(k)
        return self._current_root

    def _pick_next_active(self, excluded_key: str) -> Path | None:
        """活动项目被移除后选下一个：先取后台未关 runtime 的项目（ADR-0010 在跑项目，零重建复用）；
        再取注册表里第一个仍有效的项目（jarvis.json 还在）；全无 = None（空态）。"""
        for e in self._manager.runtimes.entries().values():
            if e.root == excluded_key or getattr(e.runtime, "closed", False):
                continue
            return Path(e.root)
        for item in self.registry.ordered():
            p = Path(str(item.get("path")))
            if jarvis_project_root_of(p) is not None:
                return p
        return None

    def shutdown(self) -> None:
        """app 收尾：关全部项目 runtime（释放 checkpointer 连接 + 停所有调度器）。"""
        self._manager.runtimes.close_all()
        self._presenter = None
        self._current_root = None

"""多项目工作区内核（打开/新建 项目 + 切项目 + 只读取非活动项目会话名）。

纯逻辑层（S1/S2 接缝，离 Qt）：
- resolve_open_root：给定目录判定「开哪个项目根 + 要不要初始化」（三分支）。
- init_project：幂等骨架（缺 jarvis.json 才补，绝不覆盖；建 schedules/）。
- open_project / new_project：登记进全局注册表 + 设为活动。
- list_sessions_readonly：不加载 runtime、只读列出某非活动项目的会话（id+短名）。
- pick_start_session：切项目后打开哪条会话（上次活动，缺失则新会话）。
- WorkspaceManager：切项目 = 关旧 runtime、建新、置活动（runtime_factory 可注入以便测试）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.project_paths import JARVIS_JSON

# ---------------------------------------------------------------- 打开/新建 内核（工单 02）


@dataclass(frozen=True)
class OpenDecision:
    root: Path
    needs_init: bool


def resolve_open_root(chosen_dir: Any, *, up_to: Any | None = None) -> OpenDecision:
    """三分支：① 目录本身有 jarvis.json → 开它；② 上级有 → 开那个上级项目根；③ 都没有 → 需初始化。

    up_to（可选搜索上界）：向上查找止于该目录（含它本身、不含其父）；缺省 None = 查到文件系统顶。
    """
    c = Path(str(chosen_dir)).expanduser().resolve()
    cap = Path(str(up_to)).expanduser().resolve() if up_to is not None else None

    def within(p: Path) -> bool:
        if cap is None:
            return True
        return p == cap or cap in p.parents

    if (c / JARVIS_JSON).is_file():
        return OpenDecision(root=c, needs_init=False)
    for d in c.parents:
        if not within(d):
            break
        if (d / JARVIS_JSON).is_file():
            return OpenDecision(root=d, needs_init=False)
    return OpenDecision(root=c, needs_init=True)


def init_project(root: Any) -> None:
    """幂等骨架：缺 jarvis.json 才写默认（不覆盖已有）；建 schedules/ 目录。"""
    from src.project_init import JARVIS_JSON_TEMPLATE

    r = Path(str(root)).expanduser().resolve()
    jarvis = r / JARVIS_JSON
    if not jarvis.is_file():
        data = dict(JARVIS_JSON_TEMPLATE)
        data["project_name"] = r.name
        # 新建项目默认不配知识库（spec：默认无 /vault/）；剥掉模板里的 KB 键
        data.pop("knowledge_base", None)
        data.pop("obsidian_vault", None)
        r.mkdir(parents=True, exist_ok=True)
        jarvis.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (r / "schedules").mkdir(exist_ok=True)


def open_project(registry, chosen_dir: Any, *, now: float | None = None, up_to: Any | None = None) -> Path:
    """打开项目：判定根 + （需时）初始化 + 登记并设为活动。返回项目根。"""
    d = resolve_open_root(chosen_dir, up_to=up_to)
    if d.needs_init:
        init_project(d.root)
    registry.add(d.root, now=now)
    return d.root


def new_project(registry, name: str, parent_dir: Any, *, now: float | None = None) -> Path:
    """新建项目：在 parent 下建 <name>/ + 骨架 + 登记并设为活动。返回项目根。"""
    root = (Path(str(parent_dir)).expanduser().resolve() / str(name)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    init_project(root)
    registry.add(root, name=name, now=now)
    return root


# ---------------------------------------------------------------- 只读取会话 / 切项目（工单 03）


def list_sessions_readonly(project_root: Any) -> list[tuple[str, str]]:
    """只读列出某（非活动）项目的会话 (thread_id, 短名)，不加载其 runtime。

    thread 清单取自该项目 checkpoint 库（只读连接），短名来自其 sessions.json；
    DB 缺失/打不开 → 空。非活动项目无其它 runtime 争锁，只读安全。
    """
    root = Path(str(project_root)).expanduser().resolve()
    from src.project_paths import CHECKPOINTS_DIR

    db = root / CHECKPOINTS_DIR / "checkpoints.sqlite"
    tids: list[str] = []
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT thread_id FROM checkpoints "
                    "WHERE thread_id NOT LIKE 'sched-%' GROUP BY thread_id"
                ).fetchall()
                tids = [str(r[0]) for r in rows]
            finally:
                con.close()
        except sqlite3.Error:
            tids = []
    from src.gui.session_registry import SessionRegistry

    reg = SessionRegistry(root / "sessions.json")
    out: list[tuple[str, str]] = []
    for tid in tids:
        e = reg.get(tid) or {}
        title = str(e.get("title", "")).strip()
        out.append((tid, title or tid))
    return out


def pick_start_session(registry, project_root: Any, available_tids: list[str]) -> str | None:
    """切到某项目后打开哪条会话：注册表记的上次活动会话（若仍在 available 里）；否则 None=新会话。"""
    last = registry.last_active_thread(project_root)
    if last and last in available_tids:
        return last
    return None


class WorkspaceManager:
    """持有全局注册表 + 当前活动 runtime；切项目 = 关旧、建新、置活动。

    runtime_factory(root) -> runtime（须有 .close()）；可注入以便测试（真值 = build_runtime）。
    is_running() = 当前项目是否有进行中回合（UI 接当前 presenter 的 gate）；
    proceed_if_running() 由 UI 注入（弹「切换将取消进行中回合」确认，True=继续）。
    """

    def __init__(self, registry, runtime_factory: Callable, *, is_running: Callable[[], bool] | None = None) -> None:
        self.registry = registry
        self._factory = runtime_factory
        self._is_running = is_running or (lambda: False)
        self.current: Any = None
        self.active_root: Path | None = None

    def switch_to(self, root: Any, *, proceed_if_running: Callable[[], bool] | None = None) -> Any:
        """切到 root。当前有进行中回合且（缺省或）确认不继续 → 返回 None（不切）。"""
        root = Path(str(root)).expanduser().resolve()
        if self.current is not None and self._is_running():
            gate = proceed_if_running if proceed_if_running is not None else (lambda: True)
            if not gate():
                return None
        if self.current is not None:
            self.current.close()
        self.current = self._factory(root)
        self.active_root = root
        self.registry.set_active(root)
        return self.current

    def active(self) -> Path | None:
        return self.active_root

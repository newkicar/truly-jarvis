"""多项目工作区内核（打开/新建 项目 + 切项目 + 只读取非活动项目会话名）。

纯逻辑层（S1/S2 接缝，离 Qt）：
- resolve_open_root：给定目录判定「开哪个项目根 + 要不要初始化」（开哪个文件夹就是哪个项目根，不再向上回落）。
- init_project：幂等骨架（缺 jarvis.json 才补，绝不覆盖；建 schedules/）。
- open_project / new_project：登记进全局注册表 + 设为活动。
- list_sessions_readonly：不加载 runtime、只读列出某非活动项目的会话（id+短名）。
- pick_start_session：切项目后打开哪条会话（上次活动，缺失则新会话）。
- WorkspaceManager：切项目 = 复用/新建该项目 entry + 置活动（ADR-0010：busy runtime 后台续跑，只关 idle；runtime_factory 可注入以便测试）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.project_paths import JARVIS_JSON
from src.gui.runtime_registry import RuntimeRegistry

# ---------------------------------------------------------------- 打开/新建 内核（工单 02）


@dataclass(frozen=True)
class OpenDecision:
    root: Path
    needs_init: bool


def resolve_open_root(chosen_dir: Any) -> OpenDecision:
    """开哪个文件夹 = 哪个文件夹就是项目根（单目录判定）：

    ① 目录本身有 jarvis.json → 开它；② 没有 → 该文件夹是裸文件夹，需初始化。
    不再向上查找祖先项目根（打开「另一个 jarvis 项目的子文件夹」= 独立裸文件夹，
    允许项目套项目/临时文件夹，与 codex 的 cwd=项目 语义一致）。
    """
    c = Path(str(chosen_dir)).expanduser().resolve()
    return OpenDecision(root=c, needs_init=not (c / JARVIS_JSON).is_file())


def jarvis_project_root_of(chosen_dir: Any) -> Path | None:
    """目录本身有 jarvis.json → 返回该目录；否则 None（= 不再是 jarvis 项目）。

    启动/切项目的**有效性判定**专用（与 resolve_open_root 的「判定+要初始化」不同）：
    - 目录不存在 → None；
    - 目录本身存在 jarvis.json → 该目录（**不再**向上查找祖先项目根）；
    - 没有 → None（用户已删除 jarvis 依赖文件 = 不再需要该项目；**不**自动重建）。
    UNC/网络盘路径不做 .resolve()（避免网络盘探测挂起）；任何 I/O 异常一律 None，
    永不把「探测失败」误判为有效项目。
    """
    try:
        d = Path(str(chosen_dir)).expanduser()
        if not d.is_dir():
            return None
        return d if (d / JARVIS_JSON).is_file() else None
    except OSError:
        return None


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


def open_project(registry, chosen_dir: Any, *, now: float | None = None) -> Path:
    """打开项目：判定根 + （需时）初始化 + 登记并设为活动。返回项目根。"""
    d = resolve_open_root(chosen_dir)
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
    """持有全局注册表 + 多项目 runtime（RuntimeRegistry，ADR-0010：busy 后台续跑）。

    切项目 = 复用/新建该项目 entry + 置活动；busy runtime 后台继续工作、只关 idle（codex 进程模型先例）。
    runtime_factory(归一 str key) -> runtime（须有 .close()）；可注入以便测试（真值 = build_runtime）。
    遗留接口（is_running / proceed_if_running）保留为 no-op，兼容旧调用点。
    """

    def __init__(self, registry, runtime_factory: Callable, *, is_running: Callable[[], bool] | None = None) -> None:
        self.registry = registry
        self._factory = runtime_factory
        self._is_running = is_running or (lambda: False)  # 遗留 no-op：新语义不再取消后台工作
        self.runtimes = RuntimeRegistry(self._factory, registry=registry)

    @property
    def current(self) -> Any:
        """活动项目 entry 的 runtime（无活动 = None）。"""
        e = self.runtimes.active_entry()
        return e.runtime if e is not None else None

    @property
    def active_root(self) -> Path | None:
        k = self.runtimes.active_key()
        return Path(k) if k is not None else None

    def switch_to(self, root: Any, *, proceed_if_running: Callable[[], bool] | None = None) -> Any:
        """切到 root：复用/新建该项目 entry 并置活动；busy runtime 后台保留，idle 关掉。

        恒返回目标项目的 runtime（非 None）。`proceed_if_running` 为遗留 kwarg（新实现忽略）。
        """
        e = self.runtimes.activate(root)
        self.runtimes.close_idle()
        return e.runtime

    def active(self) -> Path | None:
        return self.active_root
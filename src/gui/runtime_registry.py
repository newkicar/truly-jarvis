"""RuntimeRegistry——GUI 多项目 runtime 后台续跑内核（离 Qt，纯 stdlib）。

设计（ADR-0010）：切项目/切会话**不再关闭**旧项目的 runtime；busy（有进行中回合
或有开着的调度器）的 runtime 一律保留、后台继续工作（对标 codex 独立进程模型）；
只有 idle 的 runtime 才由 close_idle() 统一关掉释放资源。切回已存在的项目时
复用 entry（零重建、checkpoint 连接与调度器状态原样保留）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def normalize_root_key(root: Any) -> str:
    """项目根归一 key（与 ProjectRegistry._norm 一致：expanduser + resolve + str）。"""
    return str(Path(str(root)).expanduser().resolve())


def default_busy(entry: "RegistryEntry") -> bool:
    """缺省 busy 判据（双判，任一命中 = 后台有活）：

    ① presenter.gate.running_threads() 非空（有进行中回合）；
    ② runtime.gate（SchedulerGate）.enabled = True（调度器开着，job 可能随时触发）。
    全部 getattr/调用包 try/except，任何异常 → False（保守：宁可关也不误保）。
    """
    try:
        pr = getattr(entry, "presenter", None)
        g = getattr(pr, "gate", None)
        rt_threads = getattr(g, "running_threads", None)
        if callable(rt_threads) and rt_threads():
            return True
    except Exception:
        pass
    try:
        rt_gate = getattr(entry.runtime, "gate", None)
        if rt_gate is not None and getattr(rt_gate, "enabled", False):
            return True
    except Exception:
        pass
    return False


@dataclass
class RegistryEntry:
    """一个项目的 runtime + 其 presenter（presenter 可后接线，wire_presenter 注入）。"""

    root: str
    runtime: Any
    presenter: Any = None

    def close(self) -> None:
        """关调度器 + 关 runtime（均 getattr 防御，缺字段直接跳过，FakeRT 友好）。"""
        gate = getattr(self.runtime, "gate", None)
        shutdown = getattr(gate, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:
                pass
        close = getattr(self.runtime, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        self.runtime.closed = True


class RuntimeRegistry:
    """多项目 runtime 持有器：activate=复用/重建/新建；close_idle 只关非活动且 idle 的。"""

    def __init__(
        self,
        factory: Callable[[str], Any],
        *,
        registry: Any = None,
        busy: Callable[["RegistryEntry"], bool] | None = None,
    ) -> None:
        self._factory = factory
        self._registry = registry
        self._busy = busy or default_busy
        self._entries: dict[str, RegistryEntry] = {}
        self._active_key: str | None = None

    def activate(self, root: Any) -> RegistryEntry:
        """切到 root：已有 entry 且未关 → 复用（零重建）；已关 → 原地重建；新 → factory。

        factory 只收**归一化字符串** key。
        """
        k = normalize_root_key(root)
        e = self._entries.get(k)
        if e is not None:
            if getattr(e.runtime, "closed", False):
                e = RegistryEntry(root=k, runtime=self._factory(k))
                self._entries[k] = e
        else:
            e = RegistryEntry(root=k, runtime=self._factory(k))
            self._entries[k] = e
        self._active_key = k
        if self._registry is not None:
            self._registry.set_active(k)
        return e

    def get(self, root: Any) -> RegistryEntry | None:
        return self._entries.get(normalize_root_key(root))

    def entries(self) -> dict[str, RegistryEntry]:
        return dict(self._entries)

    def active_key(self) -> str | None:
        return self._active_key

    def active_entry(self) -> RegistryEntry | None:
        k = self._active_key
        return self._entries.get(k) if k is not None else None

    def deactivate(self) -> None:
        """清活动指针（活动项目被「从列表移除」后调用）：只清不关、不重建。

        ProjectRegistry 侧的登记项与 active 字段已由 registry.remove() 清理；
        这里防 close_idle/close_all/active_entry 命中陈旧 key。
        """
        self._active_key = None

    def close_idle(self) -> int:
        """关一切「非活动 + idle + 未关」的 runtime；busy/活动/已关一律跳过。返回关闭数。"""
        n = 0
        for e in list(self._entries.values()):
            if e.root == self._active_key:
                continue
            if getattr(e.runtime, "closed", False):
                continue
            if self._busy(e):
                continue
            e.close()
            n += 1
        return n

    def close_all(self) -> None:
        """app 收尾：全关（含活动与 busy——调度器/回合都停）。"""
        for e in list(self._entries.values()):
            if not getattr(e.runtime, "closed", False):
                e.close()
        self._active_key = None

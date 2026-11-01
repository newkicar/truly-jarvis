"""RuntimeRegistry 单测（ADR-0010：busy runtime 切走不关、切回复用零重建）。

纯内存（TEST_ROOT 自建目录纪律，不用 tmp_path）。
"""
import os
import shutil
from types import SimpleNamespace
from pathlib import Path

from src.gui.runtime_registry import (
    RegistryEntry,
    RuntimeRegistry,
    default_busy,
    normalize_root_key,
)


def _mkroot(name):
    """自建临时项目根目录（用完由调用方 clean）。"""
    base = Path(os.environ.get("TEST_ROOT") or (Path.cwd() / "scratch_test_root"))
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _clean(root):
    shutil.rmtree(str(root.parent), ignore_errors=True)


class _FakeRT:
    """最小 Fake runtime：close() 置 closed，可挂 gate。"""

    def __init__(self, label):
        self.label = label
        self.closed = False
        self.gate = None

    def close(self):
        self.closed = True


def _reg_factory(calls):
    def factory(key):
        calls.append(key)
        rt = _FakeRT(key)
        return rt
    return factory


def test_activate_reuses_entry_zero_rebuild():
    root = _mkroot("p1")
    try:
        calls: list = []
        reg = RuntimeRegistry(_reg_factory(calls))
        e1 = reg.activate(root)
        e2 = reg.activate(root)
        assert e1 is e2
        assert calls == [normalize_root_key(root)]  # factory 只调一次
        assert reg.get(root) is e1
        assert reg.active_key() == normalize_root_key(root)
    finally:
        _clean(root)


def test_activate_key_normalization_str_path_tilde():
    root = _mkroot("p2")
    try:
        rn = normalize_root_key(root)
        assert rn == normalize_root_key(str(root)) == normalize_root_key(Path(str(root)))
        calls: list = []
        reg = RuntimeRegistry(_reg_factory(calls))
        e = reg.activate(root)
        assert e.root == rn  # entry.root = 归一 key
        assert reg.get(str(root)) is e
        assert reg.get(root) is e
        assert calls == [rn]
    finally:
        _clean(root)


def test_activate_closed_entry_rebuilds_in_place():
    root = _mkroot("p3")
    try:
        calls: list = []
        reg = RuntimeRegistry(_reg_factory(calls))
        e1 = reg.activate(root)
        e1.close()
        assert e1.runtime.closed is True
        e2 = reg.activate(root)
        assert e2 is not e1
        assert e2.runtime.closed is False
        assert len(calls) == 2
    finally:
        _clean(root)


def test_get_miss_returns_none():
    calls: list = []
    reg = RuntimeRegistry(_reg_factory(calls))
    assert reg.get("ghost-project-key") is None  # 不存在的 key → miss
    assert calls == []  # get 不触发 factory
    assert reg.active_entry() is None
    assert reg.active_key() is None


def test_close_idle_keeps_active_and_busy_closes_rest():
    a = _mkroot("a")
    b = _mkroot("b")
    try:
        calls: list = []
        reg = RuntimeRegistry(_reg_factory(calls))
        ea = reg.activate(a)
        eb = reg.activate(b)          # b 变活动
        # a idle → 应被关；b 是 active → 保留
        n = reg.close_idle()
        assert n == 1
        assert ea.runtime.closed is True
        assert eb.runtime.closed is False
        # b 加 busy 标记（scheduler gate enabled）再手动造 idle a'
        eb.runtime.gate = SimpleNamespace(enabled=True)
        ea2 = reg.activate(a)         # a 重建（closed → rebuild），a 变活动
        n2 = reg.close_idle()
        assert n2 == 0                # b busy + active 保留
        assert eb.runtime.closed is False
    finally:
        _clean(a)


def test_close_idle_skips_active_even_if_busy():
    a = _mkroot("a")
    b = _mkroot("b")
    try:
        reg = RuntimeRegistry(_reg_factory([]))
        ea = reg.activate(a)
        eb = reg.activate(b)
        # b 标 busy；close_idle 只跳过活动+busy，idle 的 a 照关
        eb.runtime.gate = SimpleNamespace(enabled=True)
        assert reg.close_idle() == 1
        assert ea.runtime.closed is True
        assert eb.runtime.closed is False
        # 活动 a 变 idle，b busy → 切 a 时 b 保留
        reg.activate(a)
        assert reg.close_idle() == 0
        assert eb.runtime.closed is False
    finally:
        _clean(a)


def test_close_all_closes_everything():
    a = _mkroot("a")
    b = _mkroot("b")
    try:
        reg = RuntimeRegistry(_reg_factory([]))
        reg.activate(a)
        reg.activate(b)
        reg.close_all()
        for e in reg.entries().values():
            assert e.runtime.closed is True
        assert reg.active_key() is None
    finally:
        _clean(a)


def test_default_busy_two_wires():
    # ① presenter.gate.running_threads 非空
    pr = SimpleNamespace(gate=SimpleNamespace(running_threads=lambda: ["t1"]))
    rt = _FakeRT("x")
    assert default_busy(SimpleNamespace(presenter=pr, runtime=rt)) is True
    # ② runtime.gate.enabled
    pr2 = SimpleNamespace(gate=SimpleNamespace(running_threads=lambda: []))
    rt2 = _FakeRT("x")
    rt2.gate = SimpleNamespace(enabled=True)
    assert default_busy(SimpleNamespace(presenter=pr2, runtime=rt2)) is True
    # 双 idle → False
    rt3 = _FakeRT("x")
    rt3.gate = SimpleNamespace(enabled=False)
    assert default_busy(SimpleNamespace(presenter=pr2, runtime=rt3)) is False
    # presenter 为 None（切走未接线）→ 只看 runtime.gate
    assert default_busy(SimpleNamespace(presenter=None, runtime=rt3)) is False
    # 异常保守 → False（running_threads 抛异常时不炸，按 idle 处理）
    boom = SimpleNamespace(gate=SimpleNamespace(running_threads=lambda: (_ for _ in ()).throw(ValueError())))
    assert default_busy(SimpleNamespace(presenter=boom, runtime=_FakeRT("x"))) is False
    # 无 gate 的 FakeRT（旧测试直传兼容）→ False
    assert default_busy(SimpleNamespace(presenter=None, runtime=_FakeRT("y"))) is False


def test_custom_busy_overrides_default():
    a = _mkroot("a")
    b = _mkroot("b")
    try:
        reg = RuntimeRegistry(_reg_factory([]), busy=lambda e: False)  # 全 idle
        ea = reg.activate(a)
        reg.activate(b)
        ea.runtime.gate = SimpleNamespace(enabled=True)  # 自定义 busy 无视
        assert reg.close_idle() == 1
        assert ea.runtime.closed is True
    finally:
        _clean(a)


def test_registry_set_active_propagates():
    seen: list = []

    class FakeProjReg:
        def set_active(self, key):
            seen.append(key)

    a = _mkroot("a")
    try:
        reg = RuntimeRegistry(_reg_factory([]), registry=FakeProjReg())
        reg.activate(a)
        assert seen == [normalize_root_key(a)]
    finally:
        _clean(a)

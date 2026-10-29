"""工单 02 — 打开/新建 项目内核（缺 jarvis.json 三分支 + 幂等骨架 + 建目录）。

纯逻辑（无 Qt，用假注册表 + 临时目录）：给定目录判定「开哪个根、要不要初始化」、
新建=建目录+骨架+登记。目录纪律：.scratch/gui-test-tmp（禁 tmp_path）。
"""
from __future__ import annotations

import json
import shutil
import uuid

from tests.gui_fakes import TEST_ROOT


def _tree() -> "tuple":
    base = TEST_ROOT / f"ws-{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True)
    # 一个真实项目根（有 jarvis.json）+ 其下子文件夹 + 一个裸文件夹
    proj = base / "realproj"
    proj.mkdir()
    (proj / "jarvis.json").write_text(json.dumps({"project_name": "realproj"}), encoding="utf-8")
    (proj / "sub").mkdir()  # 子文件夹：本身无 jarvis.json，上级 realproj 有
    bare = base / "bare"
    bare.mkdir()  # 无任何 jarvis.json

    def clean():
        shutil.rmtree(base, ignore_errors=True)

    return base, proj, proj / "sub", bare, clean


from src.gui.project_registry import ProjectRegistry  # noqa: E402
from src.gui.workspace import OpenDecision, init_project, new_project, open_project, resolve_open_root  # noqa: E402


def test_resolve_self_has_jarvis():
    base, proj, _sub, _bare, clean = _tree()
    try:
        d = resolve_open_root(proj, up_to=base)
        assert isinstance(d, OpenDecision)
        assert d.root == proj.resolve() and d.needs_init is False
    finally:
        clean()


def test_resolve_ancestor_has_jarvis():
    base, _proj, sub, _bare, clean = _tree()
    try:
        d = resolve_open_root(sub, up_to=base)
        assert d.root == _proj.resolve()  # 认定属于上级项目根
        assert d.needs_init is False
    finally:
        clean()


def test_resolve_neither_needs_init():
    base, _proj, _sub, bare, clean = _tree()
    try:
        d = resolve_open_root(bare, up_to=base)
        assert d.root == bare.resolve() and d.needs_init is True
    finally:
        clean()


def test_init_project_writes_only_if_missing_and_idempotent():
    _b, _proj, _sub, bare, clean = _tree()
    try:
        sentinel = (bare / "jarvis.json")  # 尚不存在
        init_project(bare)
        assert (bare / "jarvis.json").is_file()
        assert (bare / "schedules").is_dir()
        (bare / "jarvis.json").write_text(json.dumps({"keep": 1}), encoding="utf-8")
        init_project(bare)  # 幂等：不覆盖已有
        assert json.loads((bare / "jarvis.json").read_text(encoding="utf-8")) == {"keep": 1}
        _ = sentinel
    finally:
        clean()


def test_open_project_registers_active_root():
    base, proj, _sub, _bare, clean = _tree()
    try:
        reg = ProjectRegistry(base / "projects.json")
        root = open_project(reg, proj, now=1.0, up_to=base)
        assert root == proj.resolve()
        assert reg.active() == str(proj.resolve())
        assert len(reg.entries()) == 1
    finally:
        clean()


def test_open_bare_inits_then_registers():
    base, _proj, _sub, bare, clean = _tree()
    try:
        reg = ProjectRegistry(base / "projects.json")
        root = open_project(reg, bare, now=1.0, up_to=base)
        assert (bare / "jarvis.json").is_file()  # 缺配置 → 骨架已补
        assert root == bare.resolve()
        assert reg.get(root) is not None
    finally:
        clean()


def test_open_dedupe_no_duplicate_entry():
    base, proj, _sub, _bare, clean = _tree()
    try:
        reg = ProjectRegistry(base / "projects.json")
        open_project(reg, proj, now=1.0, up_to=base)
        open_project(reg, proj, now=2.0, up_to=base)
        assert len(reg.entries()) == 1
        assert reg.get(proj)["last_opened"] == 2.0
    finally:
        clean()


def test_new_project_creates_dir_scaffolds_and_registers():
    _b, _proj, _sub, _bare, clean = _tree()
    try:
        reg = ProjectRegistry(_b / "projects.json")
        root = new_project(reg, "新工程", _b, now=1.0)
        assert root == (_b / "新工程").resolve()
        assert (root / "jarvis.json").is_file()
        e = reg.get(root)
        assert e is not None and e["name"] == "新工程"
        assert reg.active() == str(root)
    finally:
        clean()

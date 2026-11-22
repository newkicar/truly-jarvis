"""Public discovery face tests (src/profiles/discovery.list_profiles / ProfileInfo).

Discipline: no tmp_path / tempfile.mkdtemp; self-made directory
(C:/Users/uida0712/jarvis_pytest_v015_disco), rmtree at fixture start.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.profiles.discovery import list_profiles

BASE = Path("C:/Users/uida0712/jarvis_pytest_v015_disco")
REPO_ROOT = Path(__file__).resolve().parent.parent

ALPHA_YAML = """schema_version: 1
id: alpha
name: Alpha
description: user-layer test
identity:
  role: secretary
runtime:
  engine: deepagents
"""

PROJX_YAML = """schema_version: 1
id: projx
name: Projx
description: project-layer test
runtime:
  engine: deepagents
"""

DEV_OVERRIDE_YAML = """schema_version: 1
id: developer
name: Developer
description: user override
"""

LAZY_SCRIPT = """import sys

uh = sys.argv[1]
mod = sys.argv[2]
import jarvis
assert mod not in sys.modules, "import jarvis must not pull " + mod
from jarvis import list_profiles, ProfileInfo
infos = list_profiles(user_home=uh)
assert infos, "builtin profiles expected"
assert isinstance(infos[0], ProfileInfo)
print("ok", len(infos))
"""


class Env:
    """Isolated user_home / workspace directory pair under BASE."""

    def __init__(self, uh: Path, ws: Path) -> None:
        self.uh = uh
        self.ws = ws


@pytest.fixture()
def env():
    shutil.rmtree(BASE, ignore_errors=True)
    uh = BASE / "uh"
    ws = BASE / "ws"
    (uh / "agents" / "alpha").mkdir(parents=True)
    (uh / "agents" / "alpha" / "agent.yaml").write_text(ALPHA_YAML, encoding="utf-8")
    (ws / ".jarvis" / "agents" / "projx").mkdir(parents=True)
    (ws / ".jarvis" / "agents" / "projx" / "agent.yaml").write_text(PROJX_YAML, encoding="utf-8")
    yield Env(uh, ws)


def _by_id(infos: list) -> dict:
    return {i.profile_id: i for i in infos}


def test_builtin_always_present(env):
    by_id = _by_id(list_profiles(user_home=env.uh))
    for pid in ("developer", "researcher", "secretary"):
        assert pid in by_id, pid
        assert by_id[pid].layer == "builtin"
        assert by_id[pid].is_legacy is False
        assert by_id[pid].version == 1
    dev = by_id["developer"]
    assert dev.role == "developer"
    assert dev.engine == "deepagents"


def test_user_layer_discovered(env):
    by_id = _by_id(list_profiles(user_home=env.uh))
    alpha = by_id["alpha"]
    assert alpha.layer == "user"
    assert alpha.version == 1
    assert alpha.is_legacy is False
    assert alpha.role == "secretary"
    assert alpha.engine == "deepagents"
    assert alpha.description == "user-layer test"


def test_user_layer_overrides_builtin(env):
    p = env.uh / "agents" / "developer"
    p.mkdir(parents=True)
    (p / "agent.yaml").write_text(DEV_OVERRIDE_YAML, encoding="utf-8")
    by_id = _by_id(list_profiles(user_home=env.uh))
    assert by_id["developer"].layer == "user"
    assert by_id["developer"].description == "user override"


def test_project_layer_requires_workspace(env):
    by_id = _by_id(list_profiles(user_home=env.uh))
    assert "projx" not in by_id
    by_id2 = _by_id(list_profiles(user_home=env.uh, workspace=env.ws))
    assert by_id2["projx"].layer == "project"
    assert by_id2["projx"].description == "project-layer test"


def _snapshot(root: Path) -> dict:
    """All regular files under root: relative path -> size bytes."""
    out = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(root))] = path.stat().st_size
    return out


def test_list_profiles_is_read_only(env):
    before_uh = _snapshot(env.uh)
    before_ws = _snapshot(env.ws)
    list_profiles(user_home=env.uh, workspace=env.ws)
    list_profiles(user_home=env.uh)
    assert _snapshot(env.uh) == before_uh
    assert _snapshot(env.ws) == before_ws


def test_lazy_export_does_not_pull_src_agent(env):
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", LAZY_SCRIPT, str(env.uh), "src.agent"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout

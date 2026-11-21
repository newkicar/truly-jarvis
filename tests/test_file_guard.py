"""Agent Profile ticket 05: workspace file boundary guard + approvals merge + audit.

Spec: .scratch/agent-profile/issues/05-file-guard-approvals.md

Covers:
- resolve_within: real-path containment (.., symlink, drive, UNC, sibling-prefix trap)
- WorkspaceFileGuardMiddleware: write/edit/delete always boundary-checked; read tools
  only when block_read (workspace_only); unregistered tools pass; missing path value
  is fail-closed.
- permissions extension: extra_rule_tools fail-closed ask, deny gate covers extra
  tools, audit JSONL lines never contain raw args.
- merge_permissions_deny_wins: profile rules can only tighten, never relax.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import types
import uuid
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from src.file_guard import (
    PathBoundaryError,
    WorkspaceFileGuardMiddleware,
    resolve_within,
)
from src.permissions import (
    GATED_TOOLS,
    PermissionDenyMiddleware,
    build_permission_interrupts,
    build_permission_interrupts_from_state,
    build_permission_interrupts_extended,
    merge_permissions_deny_wins,
)
from src.tool_call import ToolCallView


def _view(name: str, **args) -> ToolCallView:
    return ToolCallView(name=name, id="tc-1", args=dict(args))


@pytest.fixture()
def scratch_home():
    base = Path(tempfile.gettempdir()) / f"jarvis-t05-home-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    old = os.environ.get("JARVIS_HOME")
    os.environ["JARVIS_HOME"] = str(base)
    yield base
    if old is None:
        os.environ.pop("JARVIS_HOME", None)
    else:
        os.environ["JARVIS_HOME"] = old
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def workspace():
    base = Path(tempfile.gettempdir()) / f"jarvis-t05-ws-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def outside():
    base = Path(tempfile.gettempdir()) / f"jarvis-t05-out-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


class TestResolveWithin:
    def test_relative_inside_allowed(self, workspace):
        got = resolve_within(workspace, "sub/file.txt")
        assert got == workspace.resolve() / "sub" / "file.txt"

    def test_base_dot_allowed(self, workspace):
        got = resolve_within(workspace, ".")
        assert got == workspace.resolve()

    def test_dotdot_traversal_blocked(self, workspace):
        with pytest.raises(PathBoundaryError):
            resolve_within(workspace, "../nope.txt")

    def test_absolute_outside_blocked(self, workspace, outside):
        with pytest.raises(PathBoundaryError):
            resolve_within(workspace, str(outside / "f.txt"))

    def test_string_prefix_sibling_blocked(self, workspace):
        # A naive str.startswith containment check would let this sibling through;
        # real resolve + parents containment must reject it.
        sibling = workspace.parent / (workspace.name + "-suffix")
        assert str(sibling).startswith(str(workspace))
        with pytest.raises(PathBoundaryError):
            resolve_within(workspace, str(sibling / "f.txt"))

    def test_symlink_escape_blocked(self, workspace, outside):
        target = outside / "real.txt"
        target.write_text("secret")
        link = workspace / "link.txt"
        try:
            os.symlink(target, link)
        except OSError:
            pytest.skip("symlink creation not permitted on this host")
        with pytest.raises(PathBoundaryError):
            resolve_within(workspace, "link.txt")

    @pytest.mark.skipif(os.name != "nt", reason="drive letters are Windows-only")
    def test_cross_drive_blocked(self):
        try:
            with pytest.raises(PathBoundaryError):
                resolve_within(Path("C:/"), "D:/x/f.txt")
        except OSError:
            pytest.skip("drive not available on this host")

    @pytest.mark.skipif(os.name != "nt", reason="UNC paths are Windows-only")
    def test_unc_cross_share_blocked(self):
        try:
            ok = resolve_within(Path(r"\\srv\\share1"), r"\\srv\\share1\\sub\\f.txt")
        except (OSError, ValueError):
            pytest.skip("UNC resolve unsupported on this host")
        assert str(ok).startswith(str(Path(r"\\srv\\share1")))
        with pytest.raises(PathBoundaryError):
            resolve_within(Path(r"\\srv\\share1"), r"\\srv\\share2\\f.txt")


class TestWorkspaceFileGuard:
    def test_write_inside_allowed(self, workspace):
        gw = WorkspaceFileGuardMiddleware(workspace)
        assert gw.block(_view("write_file", file_path=str(workspace / "f.txt"), content="x")) is None

    def test_write_relative_inside_allowed(self, workspace):
        gw = WorkspaceFileGuardMiddleware(workspace)
        assert gw.block(_view("write_file", file_path="sub/f.txt", content="x")) is None

    def test_write_outside_blocked(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace)
        msg = gw.block(_view("write_file", file_path=str(outside / "f.txt"), content="x"))
        assert msg is not None and "WORKSPACE-GUARD" in msg

    def test_edit_delete_outside_blocked(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace)
        assert gw.block(_view("edit_file", file_path=str(outside / "f.txt"))) is not None
        assert gw.block(_view("delete", file_path=str(outside / "f.txt"))) is not None

    def test_non_file_tools_pass(self, workspace):
        gw = WorkspaceFileGuardMiddleware(workspace, block_read=True)
        assert gw.block(_view("execute", command="dir")) is None
        assert gw.block(_view("custom_tool", file_path="../x")) is None

    def test_reads_pass_when_block_read_false(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace)
        assert gw.block(_view("read_file", file_path=str(outside / "f.txt"))) is None
        assert gw.block(_view("ls", path=str(outside))) is None

    def test_reads_blocked_when_block_read_true(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace, block_read=True)
        assert gw.block(_view("read_file", file_path=str(outside / "f.txt"))) is not None
        assert gw.block(_view("ls", path=str(outside))) is not None
        assert gw.block(_view("read_file", file_path=str(workspace / "f.txt"))) is None

    def test_missing_path_value_fail_closed(self, workspace):
        gw = WorkspaceFileGuardMiddleware(workspace)
        assert gw.block(_view("delete")) is not None
        assert gw.block(_view("write_file", content="x")) is not None
        assert gw.block(_view("glob")) is not None

    def test_glob_grep_pattern_outside_blocked(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace, block_read=True)
        pattern = str(outside) + os.sep + "*.txt"
        assert gw.block(_view("glob", pattern=pattern)) is not None
        assert gw.block(_view("grep", pattern="foo", path=str(outside))) is not None
        # a plain relative pattern is scoped to the backend root (the workspace)
        assert gw.block(_view("grep", pattern="foo")) is None

    def test_wrap_tool_call_returns_error_toolmessage(self, workspace, outside):
        gw = WorkspaceFileGuardMiddleware(workspace)
        req = types.SimpleNamespace(
            tool_call={"name": "delete", "id": "tc-9", "args": {"file_path": str(outside / "f.txt")}}
        )
        out = gw.wrap_tool_call(req, handler=None)
        assert isinstance(out, ToolMessage)
        assert out.status == "error"
        assert out.tool_call_id == "tc-9"


class TestPermissionsExtension:
    def test_legacy_state_has_extra_rule_tools_key(self):
        _, state = build_permission_interrupts(None)
        assert state["extra_rule_tools"] == ()

    def test_from_state_setdefault_missing_key(self):
        state = {"default": "ask", "tools": {t: "ask" for t in GATED_TOOLS}}
        build_permission_interrupts_from_state(state)
        assert state["extra_rule_tools"] == ()

    def test_extra_tools_fail_closed_ask(self):
        interrupt_on, state = build_permission_interrupts_extended(
            {"*": "allow"}, extra_tools=("quick_search", "search")
        )
        assert state["tools"]["quick_search"] == "ask"
        assert state["tools"]["search"] == "ask"
        assert state["extra_rule_tools"] == ("quick_search", "search")
        assert interrupt_on.get("quick_search") is not False
        assert interrupt_on["execute"] is False

    def test_extra_tools_dedup(self):
        _, state = build_permission_interrupts_extended({}, extra_tools=("search", "search"))
        assert state["extra_rule_tools"] == ("search",)

    def test_extra_tool_explicit_rule_kept(self):
        _, state = build_permission_interrupts_extended(
            {"quick_search": "deny"}, extra_tools=("quick_search",)
        )
        assert state["tools"]["quick_search"] == "deny"

    def test_deny_gate_covers_extra_tools(self):
        _, state = build_permission_interrupts_extended(
            {"quick_search": "deny"}, extra_tools=("quick_search",)
        )
        state["thread_id"] = "t-x"
        dm = PermissionDenyMiddleware(state)
        assert dm.block(_view("quick_search")) is not None
        # unregistered tools pass the gate untouched
        assert dm.block(_view("some_new_tool")) is None

    def test_deny_audit_line_never_contains_raw_args(self, scratch_home):
        _, state = build_permission_interrupts({"execute": "deny"})
        state["thread_id"] = "t-audit"
        dm = PermissionDenyMiddleware(state)
        secret = "echo super-secret-token-abc123"
        msg = dm.block(_view("execute", command=secret))
        assert msg is not None
        audit = scratch_home / "audit" / "permissions.jsonl"
        assert audit.is_file()
        lines = [json.loads(l) for l in audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert lines, "expected at least one audit line"
        rec = lines[-1]
        assert rec["tool"] == "execute"
        assert rec["action"] == "deny"
        assert rec["thread_id"] == "t-audit"
        assert rec["value_len"] == len(secret)
        assert len(rec["value_hash"]) == 12
        raw = audit.read_text(encoding="utf-8")
        assert "super-secret-token-abc123" not in raw


class TestMergeDenyWins:
    def test_project_deny_survives_profile_ask(self):
        merged = merge_permissions_deny_wins(
            {"write_file": "deny"}, {"write_file": "ask"}
        )
        assert merged["write_file"] == "deny"

    def test_profile_tightens_project_allow(self):
        merged = merge_permissions_deny_wins(
            {"write_file": "allow"}, {"write_file": "ask"}
        )
        assert merged["write_file"] == "ask"

    def test_tool_deny_overrides_project_allow(self):
        merged = merge_permissions_deny_wins(
            {"write_file": "allow"}, {}, ("write_file",)
        )
        assert merged["write_file"] == "deny"

    def test_input_dicts_not_mutated(self):
        base = {"write_file": "allow"}
        extra = {"write_file": "ask"}
        merge_permissions_deny_wins(base, extra)
        assert base["write_file"] == "allow"
        assert extra["write_file"] == "ask"

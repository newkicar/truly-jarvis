"""Agent Profile ticket 05: workspace file boundary guard.

write_file/edit_file/delete are always boundary-checked against the profile
workspace; read tools (read_file/ls/glob/grep) only when block_read=True
(filesystem.workspace_only). No string-prefix containment: paths are resolved
(non-strict, follows symlinks) and compared by real-path parent containment.
Missing required values fail closed.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView


class PathBoundaryError(Exception):
    """Requested path escapes its containing base directory."""


_WRITE_TOOLS = ("write_file", "edit_file", "delete")
_READ_TOOLS = ("read_file", "ls", "glob", "grep")
_GLOB_METACHARS = ("*", "?", "[")


def resolve_within(base, requested):
    if not requested:
        raise PathBoundaryError("empty path")
    base_path = Path(base)
    target = Path(requested)
    if not target.is_absolute():
        target = base_path / target
    resolved_base = base_path.resolve()
    resolved_target = target.resolve()
    if resolved_target == resolved_base or resolved_base in resolved_target.parents:
        return resolved_target
    raise PathBoundaryError("path escapes base: " + repr(requested))


class WorkspaceFileGuardMiddleware(GuardMiddleware):
    def __init__(self, workspace, *, block_read: bool = False):
        super().__init__()
        self._base = Path(workspace)
        self._block_read = block_read

    @property
    def name(self) -> str:
        return "workspace-file-guard"

    def block(self, view: ToolCallView) -> str | None:
        tool = view.name
        if tool in _WRITE_TOOLS:
            return self._check_file(view, tool)
        if tool not in _READ_TOOLS:
            return None
        if not self._block_read:
            if tool in ("glob", "grep") and not view.arg_value("pattern"):
                return self._fail(tool, "missing pattern value")
            return None
        if tool in ("glob", "grep"):
            return self._check_search(view, tool)
        return self._check_file(view, tool)

    def _check_file(self, view, tool):
        path_value = view.arg_value("file_path", "path")
        if not path_value:
            return self._fail(tool, "missing path value")
        return self._contain(path_value, tool)

    def _check_search(self, view, tool):
        pattern = view.arg_value("pattern")
        if not pattern:
            return self._fail(tool, "missing pattern value")
        candidates = []
        path_value = view.arg_value("path")
        if path_value:
            candidates.append(path_value)
        if tool == "glob":
            static = pattern
            for ch in _GLOB_METACHARS:
                idx = static.find(ch)
                if idx != -1:
                    static = static[:idx]
            if static:
                candidates.append(static)
        for candidate in candidates:
            if not Path(candidate).is_absolute() and ".." not in candidate.replace("/", os.sep).split(os.sep):
                continue  # relative, no traversal: scoped to backend root
            out = self._contain(candidate, tool)
            if out is not None:
                return out
        return None

    def _contain(self, value, tool):
        try:
            resolve_within(self._base, value)
        except PathBoundaryError:
            return self._fail(tool, value)
        except OSError:
            return self._fail(tool, value)
        return None

    def _fail(self, tool, detail):
        return (
            "Error: WORKSPACE-GUARD " + tool
            + " rejected: " + str(detail)
            + " escapes the profile workspace. File tools are confined to the workspace."
        )


__all__ = ["PathBoundaryError", "WorkspaceFileGuardMiddleware", "resolve_within"]

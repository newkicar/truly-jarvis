"""JarvisRuntime: multi-identity Agent Profile runtime (ticket 06).

Wraps ``create_jarvis(profile_id=...)`` in worker-isolated runtime handles
with §12.2 run semantics and ``agent_runs`` audit records:

- ``create(...)`` builds one agent per handle; the checkpointer / store are
  caller-owned, so concurrent workers never share checkpoint state;
- ``handle.invoke(message)`` returns the §12.2 dict
  (runtime_id / profile_id / profile_version / task_id / session_id /
  status / result / artifacts / memory_candidates / usage);
- ``handle.stream(message)`` yields ``stream_events`` v3 events with an
  ADR-0008 style ``RunControl``; early break cancels the run;
- ``handle.resume()`` works only when an explicit checkpointer was given;
- ``handle.close()`` is idempotent and cancels the audit row when the run
  is not terminal yet;
- audit rows: inserted on create, updated on running / completed / failed /
  cancelled; audit failures never break the run (warn + continue).

Legacy behavior (``create_jarvis(profile_id=None)``) is untouched.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from src import commands
from src.agent import create_jarvis
from src.profiles.db import insert_agent_run, update_agent_run_status

log = logging.getLogger(__name__)

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class RuntimeHandle:
    """One worker-level runtime: profile + workspace + task/session."""

    def __init__(
        self,
        *,
        runtime_id: str,
        agent,
        profile_id: str,
        profile_version: int,
        profile_hash: str,
        task_id: str | None,
        session_id: str | None,
        project_id: str | None,
        workspace: Path,
        user_home: Path,
        engine: str = "deepagents",
        checkpointer_explicit: bool = False,
    ) -> None:
        self.runtime_id = runtime_id
        self.agent = agent
        self.profile_id = profile_id
        self.profile_version = str(profile_version)
        self.profile_hash = profile_hash
        self.task_id = task_id
        self.session_id = session_id
        self.project_id = project_id
        self.workspace = workspace
        self.user_home = user_home
        self.engine = engine
        self.thread_id = session_id or task_id
        self._checkpointer_explicit = checkpointer_explicit
        self._closed = False
        self._audit_state = "created"
        try:
            insert_agent_run(
                user_home,
                runtime_id=runtime_id,
                profile_id=profile_id,
                profile_version=int(profile_version),
                profile_hash=profile_hash,
                task_id=task_id,
                session_id=session_id,
                project_id=project_id,
                workspace=str(workspace),
                engine=engine,
            )
        except Exception:
            log.warning("agent_runs audit insert failed for %s", runtime_id)
        self._emit("runtime_created")

    # ------------------------------------------------------------------
    # metadata
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> dict:
        """ProfileSnapshot.to_dict() + runtime_id (fallback for legacy)."""
        snap = getattr(self.agent, "_jarvis_profile_snapshot", None)
        if snap is not None:
            base = snap.to_dict()
        else:
            base = {
                "profile_id": self.profile_id,
                "profile_version": self.profile_version,
                "profile_hash": self.profile_hash,
                "runtime_version": "",
                "engine": self.engine,
                "task_id": self.task_id or "",
                "session_id": self.session_id or "",
                "workspace": str(self.workspace),
            }
        base["runtime_id"] = self.runtime_id
        return base

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"runtime {self.runtime_id} is closed")

    def _audit(self, status: str, *, finished: bool = False) -> None:
        if finished:
            self._audit_state = status
        try:
            update_agent_run_status(
                self.user_home, self.runtime_id, status, finished=finished
            )
        except Exception:
            log.warning("agent_runs audit update failed for %s", self.runtime_id)

    def _emit(self, kind: str, **extra) -> None:
        """Best-effort ops event (ticket 07); never raises."""
        try:
            from src.profiles.observability import ops_event

            ops_event(
                kind,
                runtime_id=self.runtime_id,
                profile_id=self.profile_id,
                profile_version=self.profile_version,
                profile_hash=self.profile_hash,
                task_id=self.task_id or "",
                session_id=self.session_id or "",
                **extra,
            )
        except Exception:
            pass

    def _config(self) -> dict:
        return commands.thread_config(self.thread_id)

    @staticmethod
    def _normalize(message: str | dict) -> dict:
        if isinstance(message, dict):
            return message
        return {"messages": [HumanMessage(content=message)]}

    @staticmethod
    def _last_ai(state: dict) -> tuple[str, dict]:
        """(result text, usage_metadata) of the last AIMessage in state."""
        msgs = (state or {}).get("messages") or []
        for msg in reversed(msgs):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            parts.append(str(part.get("text", "")))
                        else:
                            parts.append(str(part))
                    text = "".join(parts)
                else:
                    text = str(content)
                return text, dict(msg.usage_metadata or {})
        return "", {}

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------

    def invoke(self, message: str | dict) -> dict:
        """Run one turn and return the §12.2 result dict. Raises on failure."""
        self._ensure_open()
        self._audit("running")
        self._emit("worker_started")
        try:
            state = self.agent.invoke(self._normalize(message), self._config())
        except Exception:
            self._audit("failed", finished=True)
            self._emit("worker_failed")
            raise
        self._audit("completed", finished=True)
        self._emit("worker_completed")
        result, usage = self._last_ai(state)
        return {
            "runtime_id": self.runtime_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "status": "completed",
            "result": result,
            "artifacts": [],
            "memory_candidates": [],
            "usage": usage,
        }

    def stream(self, message: str | dict):
        """Stream one turn as v3 events (ADR-0008 RunControl style).

        Early break of the generator cancels the run.
        """
        self._ensure_open()
        self._audit("running")
        self._emit("worker_started")
        try:
            from langgraph.runtime import RunControl
        except ImportError:
            RunControl = None
        try:
            events = self.agent.stream_events(
                self._normalize(message),
                version="v3",
                config=self._config(),
                control=RunControl() if RunControl is not None else None,
            )
        except Exception:
            self._audit("failed", finished=True)
            self._emit("worker_failed")
            raise
        try:
            for event in events:
                yield event
        except GeneratorExit:
            self._audit("cancelled", finished=True)
            self._emit("worker_cancelled")
            raise
        except Exception:
            self._audit("failed", finished=True)
            self._emit("worker_failed")
            raise
        else:
            self._audit("completed", finished=True)
            self._emit("worker_completed")

    def resume(self) -> dict | None:
        """Resume the thread from its checkpoint.

        Requires an explicit checkpointer; None when the thread has no
        checkpoint yet.
        """
        self._ensure_open()
        if not self._checkpointer_explicit:
            # build_agent falls back to a transient InMemorySaver when no
            # checkpointer is injected, so agent.checkpointer is never None.
            # Resume only makes sense with a caller-owned checkpointer.
            raise RuntimeError(
                "resume() requires a runtime created with an explicit checkpointer"
            )
        snapshot = self.agent.get_state(self._config())
        # langgraph returns an empty Snapshot (checkpoint_id=None) for a thread
        # with no checkpoint yet, not None.
        checkpoint_id = (snapshot.config or {}).get("configurable", {}).get(
            "checkpoint_id"
        ) if snapshot is not None else None
        if checkpoint_id is None:
            return None
        self._emit("checkpoint_resumed", checkpoint_id=checkpoint_id)
        return {
            "thread_id": self.thread_id,
            "checkpoint_id": checkpoint_id,
            "next": tuple(snapshot.next or ()),
        }

    def close(self) -> None:
        """Idempotent teardown; cancels the audit row when not terminal yet."""
        if self._closed:
            return
        self._closed = True
        if self._audit_state not in TERMINAL_STATUSES:
            self._audit("cancelled", finished=True)
        self._emit("worker_cancelled")


def create(
    profile_id: str,
    workspace: str | Path,
    *,
    task_id: str | None = None,
    session_id: str | None = None,
    project_id: str | None = None,
    checkpointer=None,
    store=None,
    profile_version: int | None = None,
    user_home: str | Path | None = None,
    model=None,
    env_overrides: dict | None = None,
    permission_state: dict | None = None,
    mcp_tools: list | None = None,
) -> RuntimeHandle:
    """Build a :class:`RuntimeHandle` for ``profile_id`` rooted at ``workspace``.

    - workspace must exist (FileNotFoundError);
    - a pinned ``profile_version`` must match the loaded profile, else
      ValueError (no agent_runs row is written);
    - checkpointer / store are caller-owned: no cross-worker or
      cross-profile checkpoint sharing.
    """
    root = Path(workspace)
    if not root.is_dir():
        raise FileNotFoundError(
            f"workspace does not exist or is not a directory: {workspace}"
        )

    agent = create_jarvis(
        root,
        checkpointer,
        model=model,
        store=store,
        env_overrides=env_overrides,
        permission_state=permission_state,
        mcp_tools=mcp_tools,
        profile_id=profile_id,
        task_id=task_id,
        project_id=project_id,
        session_id=session_id,
    )

    snap = getattr(agent, "_jarvis_profile_snapshot", None)
    if snap is not None:
        version = int(snap.profile_version)
        profile_hash = snap.profile_hash
        engine = snap.engine or "deepagents"
    else:  # legacy virtual profile: fixed version 1, no hash
        version, profile_hash, engine = 1, "", "deepagents"

    if profile_version is not None and profile_version != version:
        raise ValueError(
            f"pinned profile_version {profile_version} does not match loaded "
            f"profile '{profile_id}' version {version}"
        )

    if user_home is None:
        from src.project_paths import user_home as _default_user_home
        home = _default_user_home()
    else:
        home = Path(user_home)

    return RuntimeHandle(
        runtime_id=uuid.uuid4().hex,
        agent=agent,
        profile_id=profile_id,
        profile_version=version,
        profile_hash=profile_hash,
        task_id=task_id,
        session_id=session_id,
        project_id=project_id,
        workspace=root,
        user_home=home,
        engine=engine,
        checkpointer_explicit=checkpointer is not None,
    )

"""Agent Profile Registry: three-layer discovery, merge, legacy mapping."""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.profiles.schema import (
    AgentProfile,
    ProfileError,
    check_security_narrowing,
    deep_merge,
    parse_profile,
    profile_hash,
    validate_unique_ids,
)

log = logging.getLogger(__name__)


def _default_user_home() -> Path:
    """Resolve user home directory (respects JARVIS_HOME env)."""
    from src.project_paths import user_home
    return user_home()


@dataclass(frozen=True)
class LoadedProfile:
    """A fully resolved profile with hash and AGENTS.md text."""
    profile: AgentProfile
    profile_hash: str
    agents_md_text: str
    source_path: str


class ProfileRegistry:
    """Discover, merge, and load Agent Profiles from three layers.

    Layers (low to high):
      1. builtin:  src/profiles/builtin/<id>/
      2. user:     ~/.jarvis/agents/<id>/
      3. project:  <workspace>/.jarvis/agents/<id>/

    Security narrowing: high layers may only tighten (never loosen).
    """

    AGENT_YAML = "agent.yaml"
    INSTRUCTIONS = "AGENTS.md"

    def __init__(
        self,
        *,
        user_home: Path | None = None,
        workspace: Path | None = None,
        jarvis_json_agents: dict | None = None,
    ) -> None:
        self._user_home = user_home or _default_user_home()
        self._workspace = workspace
        self._legacy_agents: dict = jarvis_json_agents or {}
        self._builtin_root = Path(__file__).resolve().parent / "builtin"

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _layers_for(self, pid: str) -> list[tuple[Path, str]]:
        """Return (dir, label) pairs for each layer that may contain pid."""
        layers: list[tuple[Path, str]] = [
            (self._builtin_root / pid, "builtin"),
        ]
        user_layer = self._user_home / "agents" / pid
        layers.append((user_layer, "user"))
        if self._workspace is not None:
            proj_layer = self._workspace / ".jarvis" / "agents" / pid
            layers.append((proj_layer, "project"))
        return layers

    def _read_layer(self, layer_dir: Path) -> tuple[dict | None, str]:
        """Read agent.yaml from a layer dir. Returns (raw_dict_or_None, source_path)."""
        yaml_path = layer_dir / self.AGENT_YAML
        if not yaml_path.is_file():
            return None, ""
        text = yaml_path.read_text(encoding="utf-8-sig")
        raw = yaml.safe_load(text)
        if raw is None:
            return None, str(yaml_path)
        if not isinstance(raw, dict):
            raise ProfileError(
                f"{yaml_path}: agent.yaml must be a mapping, got {type(raw).__name__}"
            )
        return raw, str(yaml_path)

    def _has_yaml(self, pid: str) -> bool:
        """Check if any layer has an agent.yaml for this pid."""
        for layer_dir, _ in self._layers_for(pid):
            if (layer_dir / self.AGENT_YAML).is_file():
                return True
        return False

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def _raw_profile(self, pid: str) -> tuple[dict, str] | None:
        """Merge all layers for pid. Returns (merged_dict, highest_source_path) or None."""
        merged: dict = {}
        source_path = ""
        for layer_dir, label in self._layers_for(pid):
            raw, sp = self._read_layer(layer_dir)
            if raw is None:
                continue
            if merged:
                check_security_narrowing(merged, raw)
            merged = deep_merge(merged, raw)
            if sp:
                source_path = sp
        if not merged:
            return None
        return merged, source_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(self) -> list[str]:
        """List all known profile ids (builtin + user + project + legacy), sorted."""
        ids: set[str] = set()
        # builtin
        if self._builtin_root.is_dir():
            for d in sorted(self._builtin_root.iterdir()):
                if d.is_dir() and (d / self.AGENT_YAML).is_file():
                    ids.add(d.name)
        # user
        user_agents = self._user_home / "agents"
        if user_agents.is_dir():
            for d in sorted(user_agents.iterdir()):
                if d.is_dir() and (d / self.AGENT_YAML).is_file():
                    ids.add(d.name)
        # project
        if self._workspace is not None:
            proj_agents = self._workspace / ".jarvis" / "agents"
            if proj_agents.is_dir():
                for d in sorted(proj_agents.iterdir()):
                    if d.is_dir() and (d / self.AGENT_YAML).is_file():
                        ids.add(d.name)
        # legacy
        ids.update(self._legacy_agents.keys())
        return sorted(ids)

    def get(self, pid: str) -> AgentProfile:
        """Get parsed profile for pid. Raises ProfileError if unknown."""
        raw = self._raw_profile(pid)
        if raw is not None:
            merged, sp = raw
            return parse_profile(merged, source_path=sp)
        # legacy virtual profile
        if pid in self._legacy_agents:
            return self._legacy_profile(pid)
        raise ProfileError(f"unknown profile: '{pid}'")

    def _legacy_profile(self, pid: str) -> AgentProfile:
        """Create a read-only virtual profile from jarvis.json agents section."""
        entry = self._legacy_agents[pid]
        if isinstance(entry, str):
            description = entry
        elif isinstance(entry, dict):
            description = entry.get("description", "")
        else:
            description = ""
        return AgentProfile(
            id=pid,
            name=pid,
            description=description,
            is_legacy=True,
        )

    def load(self, pid: str) -> LoadedProfile:
        """Load and persist profile. Returns LoadedProfile with hash and AGENTS.md."""
        profile = self.get(pid)
        if profile.is_legacy:
            # Legacy: no AGENTS.md, no db write
            return LoadedProfile(profile, "", "", "")

        # Read AGENTS.md from highest existing layer
        md_text = ""
        for layer_dir, _ in reversed(self._layers_for(pid)):
            md_path = layer_dir / self.INSTRUCTIONS
            if md_path.is_file():
                md_text = md_path.read_text(encoding="utf-8-sig")
                break

        ph = profile_hash(profile, md_text)

        # Upsert to db
        from src.profiles.db import upsert_profile
        upsert_profile(self._user_home, profile, ph, profile.source_path)

        return LoadedProfile(profile, ph, md_text, profile.source_path)

    def load_all(self) -> list[LoadedProfile]:
        """Load all known profiles."""
        return [self.load(pid) for pid in self.list()]
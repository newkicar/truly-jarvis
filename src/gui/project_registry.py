"""项目注册表（多项目工作区）：全局 ~/.jarvis/projects.json，只做导航/记账。

- 一个条目 = 一个已知项目（已解析绝对路径 + 显示名 + 置顶 + 最近打开 + 上次活动会话）。
- 顺序 = 置顶优先，其次按最近打开降序（对齐 ChatGPT「pin 只改顺序、不加上下文」）。
- 移除条目 = 只删注册表项，**永不**触碰项目文件夹里的数据。
- 启动选取：取排序里第一个「路径仍存在」的条目；全都不在 → 无（上层落空状态）。

纯逻辑（无 Qt）；文件缺失/损坏一律回落空注册表，不崩。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _norm(path: Any) -> str:
    return str(Path(str(path)).expanduser().resolve())


def default_registry_path() -> Path:
    """全局注册表位置：~/.jarvis/projects.json（JARVIS_HOME 可改）。"""
    from src.project_paths import user_home

    return user_home() / "projects.json"


class ProjectRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # ---- 读写（缺失/损坏 = 空）
    def _load(self) -> dict:
        if not self.path.exists():
            return {"active": None, "projects": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"active": None, "projects": []}
        if not isinstance(data, dict):
            return {"active": None, "projects": []}
        projects = data.get("projects")
        if not isinstance(projects, list):
            projects = []
        projects = [e for e in projects if isinstance(e, dict)]  # 损坏条目丢弃，不崩
        active = data.get("active")
        return {"active": active if isinstance(active, str) else None, "projects": projects}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---- 查询
    def entries(self) -> list[dict]:
        return self._load()["projects"]

    def active(self) -> str | None:
        return self._load()["active"]

    def get(self, path: Any) -> dict | None:
        want = _norm(path)
        for e in self.entries():
            if str(e.get("path")) == want:
                return e
        return None

    def last_active_thread(self, path: Any) -> str | None:
        e = self.get(path)
        if not e:
            return None
        v = e.get("last_active_thread")
        return v if isinstance(v, str) and v else None

    # ---- 变更
    def _entry(self, data: dict, path: Any) -> dict | None:
        want = _norm(path)
        return next((e for e in data["projects"] if str(e.get("path")) == want), None)

    def add(self, path: Any, *, name: str | None = None, now: float | None = None) -> None:
        data = self._load()
        want = _norm(path)
        ts = now if now is not None else time.time()
        existing = self._entry(data, want)
        if existing is not None:
            existing["last_opened"] = ts  # 重开只刷最近，保留显示名/置顶/上次会话
        else:
            data["projects"].append(
                {
                    "path": want,
                    "name": (name or Path(want).name or want),
                    "pinned": False,
                    "last_opened": ts,
                    "last_active_thread": None,
                }
            )
        data["active"] = want
        self._save(data)

    def remove(self, path: Any) -> None:
        data = self._load()
        want = _norm(path)
        data["projects"] = [e for e in data["projects"] if str(e.get("path")) != want]
        if data.get("active") == want:
            data["active"] = None
        self._save(data)

    def set_pinned(self, path: Any, on: bool) -> None:
        data = self._load()
        e = self._entry(data, path)
        if e:
            e["pinned"] = bool(on)
            self._save(data)

    def rename(self, path: Any, name: str) -> None:
        data = self._load()
        e = self._entry(data, path)
        if e:
            e["name"] = name
            self._save(data)

    def set_active(self, path: Any) -> None:
        data = self._load()
        data["active"] = _norm(path)
        self._save(data)

    def set_last_active_thread(self, path: Any, tid: str | None) -> None:
        data = self._load()
        e = self._entry(data, path)
        if e:
            e["last_active_thread"] = tid
            self._save(data)

    # ---- 排序 / 启动
    def ordered(self) -> list[dict]:
        """置顶优先（组内按最近打开降序），其次非置顶（按最近打开降序）。"""
        def key(e: dict) -> tuple[int, float]:
            return (0 if e.get("pinned") else 1, -(float(e.get("last_opened") or 0)))

        return sorted(self.entries(), key=key)

    def pick_launch(self) -> dict | None:
        """取 ordered() 里第一个「路径仍存在 且 仍是 jarvis 项目」的条目；无则 None（上层落空状态）。

        陈旧条目 = 目录还在但 jarvis.json 等依赖文件已被删除（用户不再使用 jarvis）→
        **跳过**（不删除条目、不自动重建文件），继续找下一个有效条目；全无效 → None。
        """
        from src.gui.workspace import jarvis_project_root_of  # 函数内 import：保持 registry 模块独立可 import

        for e in self.ordered():
            p = Path(str(e.get("path")))
            if p.exists() and jarvis_project_root_of(p) is not None:
                return e
        return None

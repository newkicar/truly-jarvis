"""JARVIS — 通用个人 AI 助手。包体实现在 src/，此包仅作 python -m jarvis 入口。

headless 公开入口（ADR-0012）：`from jarvis import create_jarvis`——
懒加载 src.agent，避免在导入包本身时拉起重型依赖；TUI 路径（python -m jarvis）不受影响。
"""

__all__ = ["create_jarvis"]


def __getattr__(name):
    """PEP 562 懒导出：仅暴露 create_jarvis，其余属性访问按模块语义抛 AttributeError。"""
    if name == "create_jarvis":
        from src.agent import create_jarvis

        return create_jarvis
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

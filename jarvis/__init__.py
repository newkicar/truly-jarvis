"""JARVIS — 通用个人 AI 助手。包体实现在 src/，此包仅作 python -m jarvis 入口。

headless 公开入口（ADR-0012）：
- `from jarvis import create_jarvis` —— 懒加载 src.agent，避免导入包时拉起重型依赖；
  TUI 路径（python -m jarvis）不受影响。
- `from jarvis import list_profiles, ProfileInfo` —— Agent Profile 只读发现面
  （三层 builtin->user->project，结构化返回），供外部 adapter 使用，不暴露 src 内部。
"""

__all__ = ["create_jarvis", "list_profiles", "ProfileInfo"]


def __getattr__(name):
    """PEP 562 懒导出：仅暴露上述符号，其余属性访问按模块语义抛 AttributeError。"""
    if name == "create_jarvis":
        from src.agent import create_jarvis

        return create_jarvis
    if name == "list_profiles":
        from src.profiles.discovery import list_profiles

        return list_profiles
    if name == "ProfileInfo":
        from src.profiles.discovery import ProfileInfo

        return ProfileInfo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""主代理 skills 中间件（#08）：manual-only skill（disable-model-invocation）不进模型上下文。

deepagents SkillsMiddleware 把发现的 skill 元数据（name/description/path）注入主代理 system prompt，
模型按需自动调用（progressive disclosure）。SKILL.md frontmatter 含
`disable-model-invocation: true` 的 skill 是「手动专用 skill」：只能由用户 /use 命令手动触发，
且不应出现在代理上下文中（模型不该知道它的存在，更不该自动调用）。

实现：子类化 SkillsMiddleware 只覆写 modify_request —— state 中存在被标记 skill 时复刻 base 的
模板填充逻辑但先从 skills_metadata 中过滤掉被标记项；无标记项则直接委托 base（行为不变）。
before_agent 加载逻辑（backend ls / download_files，后层覆盖同名）不变。

接线（agent.py）：不再向 create_deep_agent 传 skills=，改为把本中间件挂到主代理（与模型 backend
共享同一 CompositeBackend 实例）。副作用（ADR-0007）：deepagents 内置 GP 子代理失去 skills 注入。
"""
from __future__ import annotations

from deepagents.middleware._utils import append_to_system_message
from deepagents.middleware.skills import SkillsMiddleware

__all__ = ["JarvisSkillsMiddleware"]


class JarvisSkillsMiddleware(SkillsMiddleware):
    """SkillsMiddleware + manual-only skill 过滤（见模块 docstring）。"""

    def __init__(self, backend, sources, flagged: set[str] | None = None) -> None:
        super().__init__(backend=backend, sources=sources)
        self._flagged: set[str] = {str(n).casefold() for n in (flagged or set())}

    def modify_request(self, request):
        # 无 manual-only skill（或关闭模板）→ 完全委托 base（等价原生 SkillsMiddleware）
        if not self._flagged or self.system_prompt_template is None:
            return super().modify_request(request)

        # 复刻 base 模板填充，但先把手动专用 skill 从元数据中过滤掉
        skills_metadata = [
            s
            for s in request.state.get("skills_metadata", [])
            if str(s.get("name", "")).casefold() not in self._flagged
        ]
        skills_load_errors = request.state.get("skills_load_errors", [])
        skills_section = self.system_prompt_template.format(
            skills_locations=self._format_skills_locations(),
            skills_load_warnings=self._format_skills_load_warnings(skills_load_errors),
            skills_list=self._format_skills_list(skills_metadata),
        )
        new_system_message = append_to_system_message(request.system_message, skills_section)
        return request.override(system_message=new_system_message)

# 01 — 内置 skill 首次运行 seed 到 ~/.jarvis/skills，对齐 opencode 两层模型

**What to build:**
部署后 jarvis 只读两级 skill 层（对齐 opencode）：
- 全局级：`~/.jarvis/skills`（`USER_SKILLS_VPATH = "/skills/"`）
- 项目级：`{project}/skills`（`PROJECT_SKILLS_VPATH = "/workspace/skills/"`）

随包 14 个内置 skill（xlsx/docx/pptx/pdf/jarvis-self-help/local-facts/…）在首次运行时 seed 进 `~/.jarvis/skills`（`copytree(dirs_exist_ok=True)`，已存在则跳过不覆盖），seed 后 `~/.jarvis/skills` 即为全局可编辑 skill。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 无

## 背景

- opencode 模型：`~/.config/opencode/skills`（全局）+ `{project}/skills`（项目），清晰两级。
- 当前 jarvis 是三层：BUILTIN（`install_root()/skills` → `/builtin-skills/`）+ USER（`~/.jarvis/skills` → `/skills/`）+ PROJECT（`{project}/skills` → `/workspace/skills/`）。
- 用户部署 jarvis 后 `~/.jarvis/skills` 为空，认为内置 skill 没拷贝进来——实质是内置 skill 挂在 BUILTIN 层（`/builtin-skills/`），不在 `~/.jarvis/skills`。
- BUILTIN 层对开发者冗余：开发时 `install_root()` = project_root，`repo/skills/` 已被 PROJECT 层发现。

## 目标

### 1. ensure_user_home() — seed 内置 skill

`src/project_paths.py:ensure_user_home()` 在 `mkdir ~/.jarvis/skills/` 后：

```python
from src.project_paths import install_root
import shutil

builtin_skills = install_root() / "skills"
if builtin_skills.is_dir():
    for child in builtin_skills.iterdir():
        if child.is_dir() and not child.name.startswith(".") and not child.name.startswith("__"):
            target = home / "skills" / child.name
            if not target.exists():
                shutil.copytree(child, target)
```

仅在目标目录不存在时拷贝（不覆盖用户已有修改）。跳过隐含目录和 `__pycache__`。

### 2. skill_paths.py — 删除 BUILTIN 层

删除 `discover_skill_layers()` 中 `install_root()/skills` 分支（`src/skill_paths.py:24-26`）。

`BUILTIN_SKILLS_VPATH = "/builtin-skills/"` 常量保留（注释标注已废弃）或直接删除。

### 3. agent.py — 清理系统提示

`src/agent.py:119` 删除 `/builtin-skills/（随安装包 skill）` 前缀引用（下版本该前缀失效）。

### 4. tests/test_skill_paths.py — 更新测试

`test_discover_skill_layers_order` (line 41-59) 断言 `BUILTIN_SKILLS_VPATH in vpaths`，需改为只验证 USER + PROJECT 两层顺序。

### 5. AGENTS.md — 同步文档

更新 AGENTS.md 中 `/builtin-skills/` 相关表述，说明内置 skill 部署后 seed 进 `~/.jarvis/skills`。

## 验证

- `pytest tests/test_skill_paths.py -q` 通过
- `pytest tests/ -q` 全量通过
- 新开 `jarvis`，确认 `~/.jarvis/skills` 下出现 14 个内置 skill 目录
- 在 `~/.jarvis/skills` 手动编辑某个 skill，重启 jarvis，确认编辑未被覆盖

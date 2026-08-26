# 01 — 创建 pyproject.toml + console_scripts 入口

**What to build:** 为项目创建 `pyproject.toml`，定义包元数据、依赖、`jarvis` 命令入口（console_scripts）。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** 01-rename-constants（常量统一后再建 pyproject.toml，避免引用旧名）

## 目标

```bash
pip install -e .        # 开发模式安装
jarvis                  # 在任意目录启动（cwd 成为项目根）
python -m jarvis        # 等价启动方式
```

## pyproject.toml 结构

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "jarvis"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "deepagents==0.7.6",
    "langchain>=1.3.14,<2",
    "langchain-core>=1.5,<2",
    "langchain-openai>=1.5",
    "langgraph-checkpoint-sqlite==3.1.1",
    "textual>=0.40.0",
    "openpyxl>=3.1",
    "tavily-python",
]

[project.scripts]
jarvis = "src.main:main"

[tool.setuptools.packages.find]
include = ["src*"]

[tool.setuptools.package-data]
src = ["*.md"]
skills = ["**/*"]
```

## 需要的配套改动

- `src/__main__.py`：`from src.main import main; sys.exit(main())`
- `requirements.txt` → 保留（兼容），但 pyproject.toml 的 dependencies 是权威来源
- `.gitignore` 添加 `dist/`、`*.egg-info/`

## 验收
- [ ] `pip install -e .` 成功
- [ ] `jarvis` 命令可用（PATH 里有）
- [ ] `python -m jarvis` 可用
- [ ] `jarvis --init` 可用
- [ ] 全量测试通过

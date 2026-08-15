# 03-项目骨架搭建

`Type: task`  `Status: claimed`  `Blocked by: 01, 02`

## Question

搭建项目骨架（不写 agent 逻辑）：
1. `git init`（一期即纳入 git）+ 创建 `.gitignore`（忽略 `.env`、`checkpoints.sqlite`、快照映射库、`__pycache__/`、`.scratch/` 除外待定）
2. `requirements.txt`：依据 01/02 验证出的版本写入 `deepagents==0.7.x`、`langchain-openai`、`langgraph-checkpoint-sqlite`、`tavily-python`、`httpx`、`markdownify`、`python-dotenv`、`apscheduler`
3. `src/` 目录布局：`main.py` / `config.py` / `agent.py` / `subagents.py` / `tools.py` / `time_travel.py` / `scheduler.py`（按设计文档 §11）
4. `javis.json` 初始文件（按设计文档 §4）
5. `memory/`、`skills/` 空目录

预期产出：可安装依赖、可 `python src/main.py` 冒烟的空骨架。被 01/02 阻塞（版本需先验证）。

# 03-项目骨架搭建

`Type: task`  `Status: resolved`  `Blocked by: 01, 02`

## Question

搭建项目骨架（不写 agent 逻辑）：
1. `git init`（一期即纳入 git）+ 创建 `.gitignore`（忽略 `.env`、`checkpoints.sqlite`、快照映射库、`__pycache__/`、`.scratch/` 除外待定）
2. `requirements.txt`：依据 01/02 验证出的版本写入 `deepagents==0.7.x`、`langchain-openai`、`langgraph-checkpoint-sqlite`、`tavily-python`、`httpx`、`markdownify`、`python-dotenv`、`apscheduler`
3. `src/` 目录布局：`main.py` / `config.py` / `agent.py` / `subagents.py` / `tools.py` / `time_travel.py` / `scheduler.py`（按设计文档 §11）
4. `javis.json` 初始文件（按设计文档 §4）
5. `memory/`、`skills/` 空目录

预期产出：可安装依赖、可 `python src/main.py` 冒烟的空骨架。被 01/02 阻塞（版本需先验证）。

## Resolution

已全部完成并通过冒烟验证：

1. **git init**（main 分支）+ `.gitignore`（忽略 `.env`/`checkpoints.sqlite`/`__pycache__`/`*.sqlite*` 等；`.scratch/` 纳入跟踪以版本化 issue tracker）。已提交基线 commit。
2. **requirements.txt**：按 02 版本矩阵锁定 `deepagents==0.7.6`、`langchain>=1.3.14`、`langchain-core>=1.5.0`、`langchain-openai>=1.5.0`、`langgraph-checkpoint-sqlite==3.1.1`、`langchain-quickjs>=0.3.3` + tavily/httpx/markdownify/python-dotenv/apscheduler。已安装成功。
3. **src/** 布局：`__init__/main/config/agent/subagents/tools/time_travel/scheduler`（stub 模块，无 agent 逻辑）。
4. **javis.json**：按 §4（含 vault 路径 `E:\Thomas\Obsidian_warehouse`）。
5. **memory/ skills/** 空目录 + README 占位。

### 冒烟结果
- 依赖导入 ✅（deepagents 0.7.6 / langchain 1.3.15 / core 1.5.5 / openai 1.5.1 / quickjs 0.3.5）
- `CompositeBackend` + `SqliteSaver` + `create_deep_agent` 组装 ✅
- `python src/main.py` 退出码 0 ✅

### ⚠️ 实现要点（后续 session 必看）
- **`SqliteSaver.from_conn_string(path)` 返回的是 context manager**，必须 `with SqliteSaver.from_conn_string(path) as cp:` 使用（agent 生命周期需在 with 内）。方式 A `SqliteSaver(sqlite3.connect(path))` 也行。
- conda env `thomas` 中残留 **embedchain / langchain-cohere / langchain-community / instructor / stagehand** 等旧包与 langchain 1.3.x 冲突（pip 警告）。JARVIS 不受影响，但注意不要误用这些包。
- `.env` 仍为 `:` 分隔小写格式，`config.py` 需自定义解析（`python-dotenv` 读不了）。

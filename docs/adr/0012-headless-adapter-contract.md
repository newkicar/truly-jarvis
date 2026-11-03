# ADR-0012: headless 适配契约——create_jarvis 公开入口与 checkpointer 注入

**状态:** 已接受（2026-11-03）

## 背景

姊妹仓 local_dots（Local Dots V1.0）需要无头（headless）驱动 Jarvis 执行远程任务：
`pip install -e .` 之后，调用方通过公开入口
`create_jarvis(workspace, checkpointer)` + `.ainvoke(...)` 复用 Jarvis 的模型、
Skills 与工具，且 Jarvis 原 TUI 路径不受影响（任务清单：local_dots 仓
`.scratch/phase-a-jarvis-adapter/spec.md` 五项）。

两个硬约束来自调用方纪律：
1. **多任务并发**：同一 Python 进程内可能同时存在多个 Jarvis 会话（不同 workspace、
   不同 task），任何「当前工作目录」全局状态都会串台；
2. **重启恢复核对**：调用方（Local Dots Task Manager）需要把 checkpointer 指向自己
   管理的独立 SQLite 库（task_id 作 thread_id），服务重启后核对引擎 Thread 实际状态，
   不接受引擎自带模块级单例 checkpointer。

## 决策

1. **薄工厂 `create_jarvis(workspace, checkpointer=None, *, model=None, store=None,
   env_overrides=None, permission_state=None, mcp_tools=None)`**（src/agent.py 尾部），
   行为 = `load_config(project_root=workspace, env_overrides=...)` +
   `build_agent(config, ...)`，不引入新的装配逻辑：
   - `workspace` 必须是已存在的目录，作为 `project_root` 显式传入；
     文件后端（CompositeBackend 的 /workspace/ 路由）与 shell 工具根锚定于该目录。
   - 引擎代码路径**永不 `os.chdir`、永不 cwd 探测**（`grep -r "os.chdir" src/` 为空，
     测试 `tests/test_phase_a_adapter.py` 守门）。
   - 必填配置键（BASE_URL / API_KEY / MODEL_ID / TAVILY_KEY）由 `env_overrides` 提供，
     缺失时回落 workspace 的 .env / 全局 ~/.jarvis 配置，再缺则 KeyError。
2. **`jarvis` 包公开入口**：`from jarvis import create_jarvis` 经 PEP 562
   `__getattr__` 懒加载导出（jarvis/__init__.py），包本体导入不拉起 src.agent 的
   重型依赖；`python -m jarvis` TUI 路径（jarvis/__main__.py → src.main:main）零改动。
3. **checkpointer 由调用方注入**：`build_agent` 缺省 InMemorySaver 的行为不变；
   嵌入方（Local Dots）传 `SqliteSaver("data/checkpoints.db")`，thread_id = task_id，
   嵌入方拥有生命周期（with 块内建、随进程退出关闭），Jarvis 内无模块级单例。
4. **headless 冒烟**：`import src.agent` 后断言 `"textual" not in sys.modules`
   （TUI 相关文本终端依赖仅在 TUI 入口链上，不进核心装配链）。

## 后果

- 调用方适配器纪律（local_dots AGENTS.md）：adapters/jarvis.py 只允许
  `from jarvis import create_jarvis` + `.ainvoke(...)`，禁止 import `src.*` 内部模块。
- `create_jarvis` 不读 TUI 配置、不触网、不执行目标代码；workspace 目录本身由
  调用方授权（Local Dots 的 workspace/<task_id>/ 授权模型）。
- 已知边界：虚拟前缀 /memories/ 仍解析到全局 ~/.jarvis/memory（跨项目复用先例）；
  多会话共享同一 workspace 时文件后端无互斥，串行化由调用方（dispatcher）负责。

## 考虑过但拒绝的选项

- **新增独立 core 包（如 jarvis-core）**：需要拆仓 + 双包发布，V1.0 单人规模无收益；
  薄工厂 + 公开入口已满足「adapter 是唯一接口」纪律，TUI 与 core 共享 src/ 不构成
  import 循环（TUI 是 src.agent 的下游，不是上游依赖）。
- **checkpointer 内建默认 SQLite**：破坏 `build_agent` 的 InMemorySaver 缺省语义与
  测试惯例；注入契约写在调用方 ADR 与本 ADR 文档即可。

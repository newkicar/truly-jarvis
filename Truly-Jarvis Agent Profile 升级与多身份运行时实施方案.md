# Truly-Jarvis Agent Profile 升级与多身份运行时实施方案

-   **目标仓库：** https://github.com/newkicar/truly-jarvis
-   **交付对象：** Codex / Jarvis 开发 Agent
-   **目标：** 将 Truly-Jarvis 升级为支持多个持久逻辑身份（Agent
    Profile）的通用 Agent Runtime。
-   **核心原则：** 保留现有内核与功能，在现有实现上增加
    Profile、Runtime、Skill Resolver、Memory Router 和权限解析能力。
-   **重要声明：** 本文是目标设计，不代表其中提及的文件、函数或第三方
    API 在当前仓库中一定存在。开发 Agent
    必须先检查实际代码、依赖锁定版本和官方 API，再实施。

------------------------------------------------------------------------

# 0. 给开发 Agent 的执行指令

本任务不是从零搭建多 Agent 框架，也不是重写
Jarvis。开始开发前，必须先审计仓库。

## 0.1 第一轮必须完成的工作

1.  阅读仓库目录、README、`pyproject.toml`、lock 文件、CI 和测试。
2.  检查 Agent
    创建入口、配置加载、SubAgent、Middleware、Skill、Memory、Backend、Checkpointer、TUI、CLI
    和 Headless API。
3.  特别核实（若存在）：
    -   `src/agent.py`
    -   `src/config_agents.py`
    -   `src/skill_paths.py`
    -   `src/skill_discovery.py`
    -   `src/project_paths.py`
    -   `src/memory/`
4.  确认当前 DeepAgents、LangGraph、LangChain 及相关依赖的实际锁定版本。
5.  对照当前版本的官方文档和源码，核实
    `create_deep_agent()`、SubAgent、SkillsMiddleware、Checkpointer、Store、Backend、工具审批等
    API 的真实参数与行为。
6.  运行现有测试，记录基线结果和已存在的失败。
7.  输出当前架构图、实际调用链、能力盘点、依赖兼容性报告和文件级改造建议。

## 0.2 开发纪律

-   不得根据本文示例猜测第三方 API。
-   不得复制多份 Jarvis 内核来实现不同身份。
-   不得破坏现有 TUI、CLI、Headless API 和默认行为。
-   不得删除或改变现有 `researcher`、`knowledge_keeper`
    等子代理的默认行为。
-   不得把 Checkpoint 当作长期语义记忆。
-   不得把 Prompt 中的权限声明当作安全控制。
-   不得把所有任务输出自动写入永久记忆。
-   不要在第一阶段引入不必要的向量数据库、消息队列或微服务。
-   依赖升级与架构改造分开提交、分开测试。
-   每个阶段都要有测试、回滚边界和交付报告。

第一轮只做审计和设计，不改代码。完成评审后，再按本文阶段实施。

------------------------------------------------------------------------

# 1. 项目目标与核心概念

## 1.1 要解决的问题

当前 Jarvis
已有模型调用、工具、Middleware、子代理、Skill、Memory、Backend、TUI 和
Headless 调用等基础能力，但"配置式子代理"不等于"持久代理身份"。

需要补齐：

-   稳定的逻辑代理身份。
-   身份级职责、指令、模型策略、工具、Skill 和 Memory 配置。
-   同一个身份可以跨多个任务重复使用。
-   每次任务仍可创建全新的 Worker / Session。
-   同一 Profile 的不同 Worker 可以共享长期 Agent Memory，但不能共享临时
    Task Memory。
-   Local Dots 可以通过 `profile_id` 选择 Jarvis 身份。
-   Profile 与底层模型、DeepAgents 内核和执行引擎解耦。

## 1.2 必须区分的概念

  ----------------------------------------------------------------------------------
  概念                    定义                               生命周期
  ----------------------- ---------------------------------- -----------------------
  Engine                  推理与执行引擎，如                 引擎运行周期
                          DeepAgents、Codex                  

  Agent Profile           逻辑代理的身份与能力定义           长期

  Agent Runtime           根据 Profile                       一次运行或 Session
                          组装出的可执行代理环境             

  Worker / Agent Instance 为具体任务创建的执行实例           单任务或会话

  Session / Thread        一次连续交互及其执行状态           会话周期

  Task                    需要完成的工作单元                 任务周期

  Workspace               当前任务可访问的工作目录           任务或项目周期

  Memory                  跨任务保留的语义知识、经验和偏好   按命名空间长期保存

  Checkpoint              恢复某个执行图的状态               Session / Thread 周期

  Skill                   可复用的操作方法、流程或工具说明   版本化管理
  ----------------------------------------------------------------------------------

**关键定义：Agent Profile 是长期身份，不是长期运行的 Python 进程。**

例如，`developer` 是长期存在的逻辑身份。今天创建 Worker A
做代码审查，明天创建 Worker B 开发功能。A、B
是不同执行实例，但可以加载相同 Profile 和 Agent Memory，各自拥有独立
Task Memory、Workspace 和 Checkpoint。

## 1.3 目标公式

``` text
Agent Profile
= Identity + Instructions + Model Policy + Tools
+ Skills + Memory Policy + Permissions + Runtime Policy

Agent Runtime
= Profile + Resolved Instructions + Resolved Skills
+ Resolved Tools + Memory Context + Backend
+ Checkpointer + Middleware + Model

Worker
= Agent Runtime + Task + Workspace + Session/Thread + Task Memory
```

------------------------------------------------------------------------

# 2. 非目标与架构边界

本次不是：

-   为每个 Agent 复制一套 Jarvis。
-   让每个 Profile 都必须有独立模型或常驻进程。
-   把每个临时 Task 都变成永久 Agent。
-   立即实现无限自主创建子代理。
-   替代 Local Dots 的任务数据库、异步调度和任务编排。
-   直接复制 Codex 的全部实现。

本次只聚焦：身份可配置、运行环境可组装、记忆可隔离、技能可分配、权限可执行。

Local Dots 是外部编排层；Jarvis 是可被调用的 Agent
Runtime。双方不要重复实现任务队列和调度器。

------------------------------------------------------------------------

# 3. 目标架构与模块

``` text
User / Local Dots / CLI / TUI
              |
        Jarvis Entry API
              |
       Agent Profile Loader
              |
         Agent Registry
              |
        Profile Resolver
        /      |       \\
 Instructions Skills  Memory Policy
        \\      |       /
         Runtime Builder
              |
       Permission Resolver
              |
      Tool / Model / Backend Resolver
              |
        DeepAgents Runtime
              |
        Invoke / Stream / Resume
              |
      Result + Artifacts + Memory Candidates
              |
        Memory Curator / Persistence
```

建议新增或扩展以下模块，具体文件名必须服从仓库现有架构：

  模块                      职责
  ------------------------- ----------------------------------------
  `agent_profiles`          Profile Schema、Loader、Validator
  `agent_registry`          注册、发现、查询 Profile
  `profile_resolver`        配置合并、路径解析、版本锁定
  `agent_runtime`           根据 Profile 组装 Runtime
  `skill_resolver`          Skill 层级、过滤、冲突处理
  `memory`                  命名空间、读写、检索、候选审核
  `permission_resolver`     有效工具和权限计算
  现有 `agent.py`           保留兼容入口，内部委托 Runtime Builder
  现有 `config_agents.py`   保留旧配置，增加兼容转换

不要为了追求这些文件名拆出大量只有几行代码的模块。

------------------------------------------------------------------------

# 4. Agent Profile 配置规范

## 4.1 建议目录

``` text
~/.jarvis/
├── config/
│   └── jarvis.yaml
├── agents/
│   ├── secretary/
│   │   ├── agent.yaml
│   │   ├── AGENTS.md
│   │   ├── skills/
│   │   └── memory/
│   ├── researcher/
│   │   ├── agent.yaml
│   │   ├── AGENTS.md
│   │   ├── skills/
│   │   └── memory/
│   └── developer/
│       ├── agent.yaml
│       ├── AGENTS.md
│       ├── skills/
│       └── memory/
├── skills/
│   └── common/
├── memory/
│   ├── user/
│   └── secretary/
├── projects/
└── data/
```

## 4.2 Profile 示例

``` yaml
schema_version: 1

id: developer
name: Developer
description: Python software development and engineering maintenance

identity:
  role: Senior Python Engineer
  mission: >
    Develop, debug, test, review, and maintain software projects.
  principles:
    - Inspect existing code before changing it.
    - Prefer small, testable changes.
    - Run relevant tests before reporting completion.

runtime:
  engine: deepagents
  model: default

instructions:
  file: AGENTS.md

skills:
  include:
    - python-development
    - code-review
    - testing
  exclude:
    - industry-research

memory:
  enabled: true
  namespace: agents/developer
  recall:
    enabled: true
    max_items: 10
  write:
    mode: propose
    auto_promote: false

tools:
  allow:
    - read_file
    - write_file
    - edit_file
    - glob
    - grep
    - execute
  deny: []

permissions:
  filesystem:
    workspace_only: true
  approvals:
    execute: required
    external_network: required
    destructive_operations: required
  can_delegate: false

session:
  checkpoint_enabled: true
  checkpoint_policy: per_session

lifecycle:
  persistent_profile: true
  worker_default: ephemeral
```

以上是目标 Schema，不是 DeepAgents 原生配置格式。应使用项目已有的
Pydantic / dataclass / 配置校验体系；不要无必要增加依赖。

## 4.3 字段要求

-   `schema_version`：配置结构版本。
-   `id`：稳定唯一标识。
-   `identity`：职责、使命、原则。
-   `runtime`：Engine、模型和运行参数。
-   `instructions`：Profile 指令文件。
-   `skills`：Skill 白名单、黑名单和发现策略。
-   `memory`：命名空间与读写策略。
-   `tools`：工具可用范围。
-   `permissions`：真正执行的安全策略。
-   `session`：Checkpoint 和会话策略。
-   `lifecycle`：Profile 与 Worker 生命周期。

Profile 校验必须检查 ID、路径、Skill、Tool、Memory
Namespace、版本和权限配置。未知安全字段不得静默忽略；配置错误不得悄悄回退到权限更宽松的默认值。

------------------------------------------------------------------------

# 5. Profile 发现、覆盖和版本

## 5.1 发现范围

建议支持：

1.  内置 Profile。
2.  用户级 `~/.jarvis/agents/<id>/agent.yaml`。
3.  项目级 `<workspace>/.jarvis/agents/<id>/agent.yaml`。

不要扫描任意磁盘路径。配置来源必须处于明确的信任边界。

## 5.2 普通配置优先级

``` text
Built-in Defaults
  < User Global Defaults
  < User Agent Profile
  < Project Agent Override
  < Invocation Overrides
```

但安全配置不能按普通配置覆盖规则处理。项目级和调用级配置不能扩大上层安全边界。

有效工具集合建议按交集计算：

``` text
Effective Tools
= Registered Tools
∩ Global Policy
∩ Caller Capabilities
∩ Agent Profile Allowlist
∩ Project Policy
```

明确 deny 优先；无法确定时默认拒绝（fail closed）。

## 5.3 Profile 快照

每次创建 Worker 时记录：

``` json
{
  "profile_id": "developer",
  "profile_version": "1",
  "profile_hash": "...",
  "runtime_version": "...",
  "engine": "deepagents",
  "task_id": "...",
  "session_id": "...",
  "workspace": "..."
}
```

运行中的 Worker 使用创建时的 Profile 快照。Profile
更新不能悄悄改变正在运行的任务。历史任务应能追溯当时的 Profile、Skill
和工具配置。

------------------------------------------------------------------------

# 6. Instructions 与 AGENTS.md

每个 Profile 可以有：

``` text
~/.jarvis/agents/developer/AGENTS.md
```

内容描述工作方法、质量标准、输出规范、完成标准、失败处理和记忆候选提交规则。

建议指令层级：

1.  平台安全规则。
2.  Jarvis 全局规则。
3.  Agent Profile 身份和职责。
4.  Profile `AGENTS.md`。
5.  Project `AGENTS.md`。
6.  当前 Task Instructions。

必须定义冲突处理规则。低优先级项目文件和 Skill 不能覆盖安全规则。

`AGENTS.md` 是指令内容，不是权限执行机制。

------------------------------------------------------------------------

# 7. Skill 系统升级

## 7.1 Skill 与 Memory 的区别

  Skill                  Memory
  ---------------------- ------------------------
  如何做                 知道什么、学到了什么
  操作流程、脚本、规则   事实、经验、偏好、教训
  版本化、审核、发布     持续积累、整理、审核

不要把每次任务总结都变成 Skill。

## 7.2 三层目录

``` text
~/.jarvis/
├── skills/
│   └── common/
│       └── report-writing/SKILL.md
├── agents/
│   └── developer/
│       └── skills/
│           ├── python-development/SKILL.md
│           └── code-review/SKILL.md
└── projects/
    └── project-a/
        └── skills/
            └── domain-workflow/SKILL.md
```

如当前项目使用其他格式，先做兼容映射，不要破坏旧路径。

## 7.3 解析规则

``` text
Common Skills
  + Agent Skills
  + Project Skills
  + Optional Task Skills
  = Resolved Skills
```

必须支持：

-   Profile include / exclude。
-   公共、Agent、Project 三层。
-   同名 Skill 冲突检测。
-   Skill 版本或内容 Hash。
-   按需加载，避免一次性注入所有 Skill。
-   Skill 来源审计。
-   未授权 Skill 不得因 Prompt 提及而执行。

安全规则永远不能被 Skill 覆盖。Profile 排除规则必须有效。项目 Skill
可以补充领域知识，但不能扩大权限。

建议接口意图：

``` python
resolved = skill_resolver.resolve(
    profile=profile,
    workspace=workspace,
    task_context=task_context,
)
```

Codex 有自己的 Agent / Skill 文件约定。Jarvis
可以做兼容读取层，但不能假定 Jarvis Skill、Codex Skill 和通用 Agent
Skill 的语义完全相同。

------------------------------------------------------------------------

# 8. Memory 分层与隔离

这是本次改造的重点。

## 8.1 六类记忆

  ------------------------------------------------------------------------------------
  Memory            归属              生命周期          用途
  ----------------- ----------------- ----------------- ------------------------------
  User Memory       用户              长期              用户偏好、目标、长期背景

  Secretary Memory  秘书              长期              秘书学到的协作方式和工作经验

  Agent Memory      单个 Profile      长期              专业知识、经验、方法、教训

  Project Memory    项目              项目生命周期      项目背景、决策、进度

  Task Memory       Task / Worker     短期              中间结果、临时发现

  Conversation /    Session / Thread  会话周期          对话状态和执行状态恢复
  Checkpoint                                            
  ------------------------------------------------------------------------------------

不允许混淆：

-   Checkpoint 不是语义记忆。
-   对话历史不等于 Agent Memory。
-   项目知识不应全部写入 Agent Memory。
-   普通 Worker 不应无审核修改 User Memory。
-   临时任务结果不应默认进入永久记忆。

## 8.2 建议目录

``` text
~/.jarvis/
├── memory/
│   ├── user/
│   │   ├── profile.md
│   │   └── preferences.md
│   └── secretary/
│       ├── MEMORY.md
│       └── operating-lessons.md
├── agents/
│   ├── researcher/memory/
│   │   ├── MEMORY.md
│   │   └── lessons.md
│   └── developer/memory/
│       ├── MEMORY.md
│       └── engineering-lessons.md
├── projects/
│   └── project-a/memory/
│       ├── background.md
│       ├── decisions.md
│       └── progress.md
└── tasks/
    └── <task_id>/
        ├── working-memory.md
        └── memory-candidates/
```

## 8.3 读取策略

创建 Worker 时由 Memory Router 根据权限和任务选择性读取：

``` text
Worker Context
  + Authorized User Memory
  + Current Agent Memory
  + Authorized Project Memory
  + Current Task Memory
  + Current Conversation / Checkpoint
```

不要把所有 Memory 文件注入上下文。先加载小型 `MEMORY.md`
索引，再按任务需要读取详细内容。控制条目数和 Token 预算，记录来源。

第一版可用 Markdown + SQLite 元数据 + FTS5（确认当前 SQLite
支持情况）实现。不必立即引入向量数据库。

## 8.4 写入策略：Memory Candidate

``` text
Worker completes task
        |
Extract candidate memories
        |
Classify target namespace
        |
Validate source / confidence / sensitivity
        |
Curator review or policy approval
        |
Promote to persistent Memory
```

普通 Worker 默认可以：

-   读取授权记忆。
-   写当前 Task Memory。
-   提交自己的 Agent Memory Candidate。
-   提交 Project Memory Candidate。

默认不能直接修改 User Memory、其他 Agent Memory 或全局策略。

候选记录示例：

``` json
{
  "candidate_id": "uuid",
  "source_task_id": "task-id",
  "source_agent_id": "developer",
  "target_namespace": "agents/developer",
  "memory_type": "lesson",
  "content": "A concise reusable lesson.",
  "source_reference": "artifact-or-message-reference",
  "confidence": null,
  "created_at": "ISO-8601",
  "status": "pending_review"
}
```

`confidence` 如果没有可靠校准方法，可以留空，不要伪造精确概率。

## 8.5 并发与冲突

同一 Profile 可能同时运行多个 Worker：

-   不允许多个 Worker 无锁覆盖同一个 Memory 文件。
-   优先使用候选记录追加写入。
-   由 Curator 串行合并，或用数据库事务处理。
-   记录来源、时间、版本和修改历史。
-   冲突时保留来源并显式合并，不允许静默覆盖。

## 8.6 API 意图

``` python
memory = memory_router.for_worker(
    profile_id="developer",
    task_id="task-123",
    project_id="project-a",
    access_policy=resolved_policy,
)

context = await memory.recall(
    query="相关代码审查经验",
    scopes=["agent", "project"],
)

candidate = await memory.propose(
    namespace="agents/developer",
    content="可复用的工程经验",
    source_task_id="task-123",
)
```

以上是接口意图，必须适配当前项目风格。

------------------------------------------------------------------------

# 9. Tools 与 Permission 安全模型

## 9.1 原则

Prompt 不是安全边界。Profile
写着"不能访问工作区外文件"并不能阻止工具访问。必须在工具注册、工具调用、Backend
文件访问和外部副作用执行时强制检查。

## 9.2 权限交集

``` text
Effective Tools
= Registered Tools
∩ Global Policy
∩ Caller Capabilities
∩ Profile Allowlist
∩ Project Policy
```

明确 deny 优先；无法判断时拒绝。

## 9.3 权限分类

至少区分：

-   文件读取、写入、删除。
-   Shell / 命令执行。
-   网络访问。
-   外部 API。
-   凭证访问。
-   数据库访问。
-   Agent Delegation。
-   安全敏感操作。

高风险操作可要求审批。审批必须由 Runtime / Tool Layer 强制执行。

## 9.4 文件系统边界

-   路径规范化与真实路径检查。
-   防止 `..` 路径穿越。
-   检查符号链接是否越过 Workspace。
-   专门测试 Windows 盘符和 UNC 路径。
-   文件写入和删除时检查最终目标路径。
-   不得把字符串前缀匹配当作安全检查。

------------------------------------------------------------------------

# 10. Agent Runtime Builder

## 10.1 职责

``` text
profile_id
  -> Registry
  -> Load & Validate Profile
  -> Resolve Instructions
  -> Resolve Skills
  -> Resolve Memory Policy
  -> Resolve Tools / Permissions
  -> Resolve Model / Backend
  -> Build Middleware
  -> Bind Checkpointer / Store
  -> Create DeepAgent
  -> Compiled Runtime
```

## 10.2 API 目标

``` python
runtime = await jarvis_runtime.create(
    profile_id="developer",
    workspace=workspace,
    task_id=task_id,
    session_id=session_id,
    project_id=project_id,
)
```

Runtime Handle 应包含：

-   `profile_id`
-   `profile_version`
-   `runtime_id`
-   `invoke()`
-   `stream()`
-   `resume()`（仅当当前 Checkpointer 支持）
-   资源释放接口
-   metadata

## 10.3 保留旧入口

如果当前已有 `create_jarvis()`，保留旧签名或兼容包装：

``` python
create_jarvis(
    workspace=workspace,
    profile_id="default",
    checkpointer=checkpointer,
)
```

旧调用不传 `profile_id` 时，必须保持旧默认行为。

## 10.4 Runtime Cache

如果缓存 Compiled Runtime：

-   Cache Key 至少包含 Profile Hash、模型配置、Skill Manifest Hash、Tool
    Policy Hash 和关键 Runtime 配置。
-   Profile 更新后不能误用旧缓存。
-   Checkpointer / Session 不得跨 Profile 错误复用。
-   明确 Runtime 资源释放策略。
-   并发创建时避免重复初始化和状态污染。

------------------------------------------------------------------------

# 11. 两种 SubAgent 模式

## 11.1 Declarative SubAgent

用于简单搜索、文本整理、临时审查和一次性并行任务。

特点：

-   配置轻量。
-   可以使用部分公共能力。
-   任务结束即退出。
-   Task Memory 独立。
-   不要求独立长期 Profile。

保留现有 `researcher`、`knowledge_keeper` 等能力。

## 11.2 Profile-backed Agent

用于需要长期专业身份、独立 Memory、Skill 和权限的代理。

特点：

-   稳定 `profile_id`。
-   每次任务创建新的 Worker / Runtime。
-   跨任务共享所属 Agent Memory。
-   Task Checkpoint 独立。
-   记录 Profile Version。

如果当前 DeepAgents 版本支持 `CompiledSubAgent`
或等价机制，可研究将独立构建的 Agent 图注册为父 Agent
的子代理。但必须先确认当前锁定版本的真实 API。

## 11.3 委派原则

不要为了角色数量而增加代理。只有任务可安全并行、需要独立上下文、不同工具/权限、专业
Skill、不同模型或独立验收时才委派。

------------------------------------------------------------------------

# 12. 与 Local Dots 集成

## 12.1 Local Dots 请求示例

``` json
{
  "profile_id": "developer",
  "task_id": "task-123",
  "session_id": "session-456",
  "project_id": "project-a",
  "workspace": "D:/work/project-a",
  "message": "Review this Python project.",
  "profile_version": null
}
```

要求：

-   `profile_version` 为空时使用当前有效版本。
-   调用方可指定版本时必须验证该版本可用。
-   Workspace 必须由 Jarvis 自己校验。
-   调用方不能通过参数绕过 Profile 权限。

## 12.2 Jarvis 返回示例

``` json
{
  "runtime_id": "runtime-id",
  "profile_id": "developer",
  "profile_version": "1",
  "task_id": "task-123",
  "session_id": "session-456",
  "status": "completed",
  "result": "...",
  "artifacts": [],
  "memory_candidates": [],
  "usage": {}
}
```

## 12.3 Profile 权威来源

第一阶段建议 Jarvis 自己管理 Jarvis Profile，Local Dots 只传
`profile_id` 和任务上下文，不复制 Profile 文件。

未来如果要让 Codex 与 Jarvis 共享同一逻辑身份，再在 Local Dots 增加统一
Identity Registry 和 Engine-specific Profile Resolver。

不要第一阶段就实现跨引擎统一记忆写入。

------------------------------------------------------------------------

# 13. 向后兼容与迁移

## 13.1 旧 SubAgent 配置

如果现有 `config_agents.py` 支持
`description`、`system_prompt`、`permissions`：

-   旧配置继续可加载。
-   旧字段映射到新 Definition。
-   未配置字段保持旧默认行为。
-   提供显式迁移工具或只读兼容转换。
-   不静默重写用户配置。

## 13.2 旧 Memory

不要把旧全局 Memory 猜测性地迁移为 User Memory 或 Secretary Memory。

流程：

1.  备份。
2.  检查来源和内容。
3.  分类为用户偏好、秘书经验、项目知识或其他。
4.  生成迁移报告。
5.  由用户或明确规则确认。
6.  保留原始副本和迁移日志。

无法可靠分类时放入 `legacy` 命名空间。

## 13.3 旧 Skills 与 API

-   保留旧 Skill 搜索路径。
-   新 Resolver 兼容读取旧路径。
-   保留 `create_jarvis()`。
-   保留 TUI、CLI、Headless API。
-   保留旧 Checkpointer 使用方式。
-   保留默认模型和工具行为。
-   旧测试继续通过。

------------------------------------------------------------------------

# 14. 数据与元数据

第一阶段复用当前配置文件和 SQLite。若需要数据库实体，可参考：

``` text
agent_profiles
--------------
profile_id
schema_version
profile_version
profile_hash
source_path
enabled
created_at
updated_at
```

``` text
agent_runs
----------
runtime_id
profile_id
profile_version
profile_hash
task_id
session_id
project_id
workspace
engine
status
started_at
finished_at
```

``` text
memory_entries
--------------
memory_id
namespace
memory_type
content
source_task_id
source_agent_id
project_id
status
version
created_at
updated_at
```

``` text
memory_candidates
-----------------
candidate_id
target_namespace
source_task_id
source_agent_id
content
source_reference
status
created_at
reviewed_at
reviewed_by
```

Profile 完整配置可以继续存文件，数据库保存索引和版本元数据。Schema
必须适配现有迁移工具。

------------------------------------------------------------------------

# 15. 分阶段实施计划

## Phase 0：仓库审计与依赖验证

工作：

-   阅读仓库并运行基线测试。
-   核实依赖版本和关键 API。
-   画出 Agent、SubAgent、Skill、Memory、Checkpoint 的实际调用链。
-   输出文件级改造建议。

验收：

-   有现状报告。
-   有依赖兼容性报告。
-   有基线测试记录。
-   没有改动现有功能。

## Phase 1：Agent Profile / Registry

工作：

-   定义 Profile Schema。
-   实现 Loader、Registry、Validator。
-   支持内置和用户级 Profile。
-   支持 Version / Hash。
-   创建 `secretary`、`researcher`、`developer` 示例。
-   将旧 SubAgent 配置接入兼容层。

验收：

-   可列出和加载 Profile。
-   错误配置明确失败。
-   Profile 之间不污染。
-   旧子代理仍然可用。

## Phase 2：Agent Runtime Builder

工作：

-   把现有 Agent 组装逻辑提取为 Runtime Builder。
-   按 Profile 解析 Instructions、模型、工具和 Middleware。
-   绑定 Workspace、Session、Checkpointer。
-   保留 `create_jarvis()` 兼容入口。

验收：

-   同一内核可创建不同身份。
-   不同 Runtime 的 Instructions、工具和 Checkpoint 不串用。
-   支持并发 Worker。
-   TUI、CLI、Headless 正常。

## Phase 3：Profile-aware Skills

工作：

-   增加 Common、Agent、Project Skill 层。
-   实现 include / exclude。
-   实现冲突检测和 Skill Manifest。
-   保留旧 Skill 路径。
-   将解析结果实际传入 Runtime / Middleware。

验收：

-   Developer 加载自己的 Skill。
-   Researcher 不自动加载 Developer 专属 Skill。
-   公共 Skill 可复用。
-   Project Skill 仅在对应项目加载。
-   来源可追踪。

## Phase 4：Agent Memory

工作：

-   定义 Memory Namespace。
-   分离 User、Secretary、Agent、Project、Task、Conversation /
    Checkpoint。
-   实现 Memory Router、Recall、Candidate、审核和晋升。
-   实现并发安全写入。
-   兼容旧 Memory。

验收：

-   Developer Memory 不自动暴露给 Researcher。
-   同 Profile 的不同 Worker 可读取共享 Agent Memory。
-   Task Memory 和 Checkpoint 独立。
-   删除 Task 文件夹不会删除 Agent Memory。
-   普通 Worker 不能无审核修改 User Memory。

## Phase 5：权限与安全

工作：

-   统一 Tool Permission Resolver。
-   实现全局策略和 Profile 策略交集。
-   在工具调用时强制权限检查。
-   检查 Backend 文件系统边界。
-   测试符号链接和路径穿越。
-   增加审批和审计日志。

验收：

-   Prompt 无法绕过权限。
-   项目配置无法扩大权限。
-   路径穿越不能访问工作区外文件。
-   高风险操作不能静默执行。

## Phase 6：Local Dots 集成

工作：

-   Headless API 增加 `profile_id`、Profile Version、Task / Session /
    Project ID。
-   返回身份、运行状态、Artifacts 和 Memory Candidates。
-   保留旧调用方式。
-   提供 Local Dots 示例。

验收：

-   Local Dots 可指定 Profile 和 Workspace。
-   同一 Profile 可多次调用。
-   Worker 退出后 Agent Memory 保留。
-   Task / Session 不串线。

## Phase 7：动态委派（后续）

工作：

-   主 Agent 根据任务选择 Profile。
-   动态创建 Profile-backed Worker。
-   支持并行、进度汇报、取消、超时和结果验收。
-   限制委派深度和并发数量。

验收：

-   简单任务可由主 Agent 直接完成。
-   复杂任务可动态委派。
-   不需要为每个任务预建固定角色。
-   失败 Worker 不污染其他 Worker 上下文。

------------------------------------------------------------------------

# 16. 测试计划

## Profile

-   配置不存在或 Schema 错误。
-   Profile ID 重复。
-   Skill / Tool 引用不存在。
-   Profile Version / Hash 变化。
-   项目覆盖冲突。

## Runtime

创建 `developer` 和 `researcher` 两个 Profile，验证：

-   Instructions 不同。
-   Tools 不同。
-   Skill Manifest 不同。
-   Memory Namespace 不同。
-   可以使用相同 Engine。
-   并发运行不污染状态。

## Memory

1.  Developer Worker A 提交候选记忆。
2.  审核后晋升到 Developer Memory。
3.  Developer Worker B 能读取。
4.  Researcher 默认不能读取。
5.  删除 Worker A 的 Task Memory。
6.  Developer 长期记忆仍存在。
7.  授权的两个 Profile 可共享 Project Memory。
8.  未授权 Worker 不能写 User Memory。

## Skills

-   Common Skill 可被多个 Profile 复用。
-   Agent Skill 隔离。
-   Project Skill 按项目加载。
-   Exclude 有效。
-   同名冲突可检测。
-   未授权 Skill 不加载。

## 安全

-   `../` 路径穿越。
-   Windows 盘符越界。
-   UNC 路径。
-   符号链接越界。
-   未注册工具调用。
-   deny 工具调用。
-   项目配置尝试扩大权限。
-   Prompt Injection 尝试读取其他 Agent Memory。
-   Worker 尝试修改其他 Profile 文件。
-   并发 Memory 写入。

## 兼容

-   旧 `create_jarvis()`。
-   旧配置。
-   旧 SubAgent。
-   旧 Skill 路径。
-   旧 Memory。
-   TUI、CLI、Headless。
-   原有测试集。

## 最小端到端测试

1.  创建 Researcher Worker，研究一个技术问题。
2.  创建 Developer Worker，在测试项目中实现一个小功能。
3.  两者使用同一个 Jarvis 内核。
4.  两者加载不同身份、Skill 和 Memory。
5.  两者拥有不同 Workspace。
6.  两者拥有独立 Task Memory 和 Checkpoint。
7.  两者分别提交 Agent Memory Candidate。
8.  清理任务目录。
9.  再次创建两个 Worker。
10. 验证长期记忆保留且没有串用。

------------------------------------------------------------------------

# 17. 依赖升级策略

如果当前 DeepAgents 版本较旧：

1.  记录当前 lock 版本。
2.  独立创建依赖升级分支。
3.  检查官方 Changelog。
4.  阅读关键 API 的真实签名。
5.  运行原有测试。
6.  测试自定义 Middleware、Backend、SubAgent、Checkpointer 和 Skills。
7.  通过后再合并升级。

不要将依赖升级和 Profile
大改造混成一个提交。不能为了追逐最新版本牺牲已有可运行能力。

------------------------------------------------------------------------

# 18. 首批 Profile

第一批只实现三个身份：

### Secretary

负责理解用户目标、安排工作、选择代理、验收结果。拥有自己的 Secretary
Memory。

### Researcher

负责研究、来源核实、比较和知识整理。拥有自己的 Researcher Memory 与研究
Skill。

### Developer

负责代码开发、调试、测试和工程维护。拥有自己的 Developer Memory 与开发
Skill。

示例 Skill 名称必须映射到仓库真实存在的 Skill，或明确创建对应 Skill。

------------------------------------------------------------------------

# 19. 可观测性与运维

至少记录：

-   Profile loaded / validation failed。
-   Runtime created。
-   Runtime cache hit / miss。
-   Skills resolved。
-   Tools resolved。
-   Memory recall。
-   Memory candidate created / promoted / rejected。
-   Tool permission denied。
-   Approval requested / approved / rejected。
-   Worker started / completed / failed / cancelled。
-   Checkpoint resumed。

每次执行建议记录：

``` text
runtime_id
profile_id
profile_version
task_id
session_id
engine
workspace_id
skill_manifest_hash
tool_policy_hash
started_at
finished_at
status
```

日志不得直接输出敏感记忆、凭证、完整 Prompt 或用户隐私。

提供 Profile 列表、Profile 校验、Memory Namespace 查看、Skill Manifest
查看和权限诊断能力。

------------------------------------------------------------------------

# 20. 最终验收清单

## 身份

-   [ ] 有稳定 Profile ID。
-   [ ] 有独立 Profile 配置。
-   [ ] 有 Loader / Registry。
-   [ ] 有 Profile Version / Hash。
-   [ ] 不同 Profile 可使用同一 Jarvis 内核。

## Runtime

-   [ ] 可按 Profile 创建 Runtime。
-   [ ] 同一 Profile 可创建多个 Worker。
-   [ ] Session / Checkpoint 独立。
-   [ ] Profile 配置不串用。
-   [ ] 旧 `create_jarvis()` 兼容。

## Skill

-   [ ] Common Skill 可共享。
-   [ ] Agent Skill 可隔离。
-   [ ] Project Skill 可按项目加载。
-   [ ] include / exclude 生效。
-   [ ] Skill 来源可追踪。

## Memory

-   [ ] User Memory 独立。
-   [ ] Secretary Memory 独立。
-   [ ] Agent Memory 独立。
-   [ ] Project Memory 独立。
-   [ ] Task Memory 独立。
-   [ ] Checkpoint 与语义记忆分离。
-   [ ] 同 Profile 的 Worker 可跨任务读取 Agent Memory。
-   [ ] 普通 Worker 不能无审核修改 User Memory。
-   [ ] 并发写入安全。

## 安全与兼容

-   [ ] 工具权限由程序强制执行。
-   [ ] 权限只能按策略收紧。
-   [ ] 文件系统边界有效。
-   [ ] 符号链接和路径穿越有测试。
-   [ ] 高风险操作有审批。
-   [ ] 旧 TUI / CLI / Headless 正常。
-   [ ] 旧 SubAgent、Skill、Memory 不丢失。
-   [ ] 原有测试通过。

------------------------------------------------------------------------

# 21. 给开发 Agent 的第一轮任务

**第一轮只审计和设计，不改代码。**

请完成：

1.  完整阅读仓库。
2.  画出当前 Agent 创建、配置、Skill、Memory、Checkpointer、SubAgent
    的真实调用链。
3.  对照当前锁定的 DeepAgents 版本，核实原生能力。
4.  将当前实现映射到本文目标架构。
5.  标明哪些可直接复用、哪些需要自定义、哪些不适合当前版本。
6.  给出最小改造方案和文件级变更清单。
7.  给出配置、数据库和 Memory 迁移方案。
8.  给出测试计划。
9.  输出实施计划，等待评审后再改代码。

第一轮交付：

``` text
docs/
└── agent-profile/
    ├── 00-current-architecture.md
    ├── 01-api-compatibility.md
    ├── 02-implementation-plan.md
    └── 03-migration-and-test-plan.md
```

评审通过后按 Phase 1 至 Phase 6 顺序开发。Phase 7
动态委派属于后续增强，不要抢先做。

------------------------------------------------------------------------

# 22. 最终架构原则

1.  **Profile 是身份，不是进程。**
2.  **Worker 是一次执行实例，不是新的永久代理。**
3.  **Engine 是执行内核，不等于 Agent 身份。**
4.  **Memory 是跨任务知识，不等于 Checkpoint。**
5.  **Skill 是可复用方法，不等于 Memory。**
6.  **Project Memory 属于项目，不属于某个 Agent。**
7.  **权限必须由程序执行，不能只写在 Prompt 里。**
8.  **临时任务可以使用长期身份，但不应自动成为长期代理。**
9.  **一个 Profile 可以创建多个并发 Worker。**
10. **先建立稳定的身份、运行时和记忆边界，再做自主多代理组织。**

最终目标：

> Truly-Jarvis 是一个通用 Agent Runtime。它可以通过 Profile
> 定义多个长期逻辑身份；每个身份可以拥有独立
> Instructions、Skills、Memory 和
> Permissions；同一身份可以在不同任务中创建多个隔离 Worker；这些 Worker
> 可以共享该身份的长期知识，同时保持任务状态、工作目录和 Checkpoint
> 独立。Local Dots 可以通过稳定 API 选择 Profile、指定任务和
> Workspace，并调用 Jarvis 完成工作。

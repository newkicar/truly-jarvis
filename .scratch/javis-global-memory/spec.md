## Spec: 长期记忆目录全局化（javis-global-memory）

### 用户诉求
Jarvis 在项目目录创建 memory/agent-memory.md（长期记忆）与 /dream 沉淀。要求：memory 目录放到 %user%\.jarvis 下，默认从此读取，跨项目复用；/dream 同步全局化。

### 设计定稿（实机侦察：项目与全局 jarvis.json 都已显式写 memory_dir=memory，仅改默认不生效 → 哨兵语义）
1. T1 config 哨兵解析（src/config.py L192）：memory_dir 缺省 或值∈{memory,""（旧模板默认视为未配置）} → user_home()/"memory"（~/.jarvis/memory，JARVIS_HOME 可覆盖）；其他显式值：相对→项目根解析、绝对→原样。config.py 顶部补 import user_home。
2. T2 一次性迁移（新模块 src/memory_dir.py，钩子 main.py 两个 load_config 之后、build_agent 之前；异常只 stderr 告警）：生效目录==全局默认时，合并 {project_root}/memory/ → 全局：顶层 *.md（含其他顶层常规文件）目标无→move；同名同容→跳过留源（幂等）；同名异容→{stem}__{project_name}.md（再冲突加 __2）；dream/ 子目录逐文件同规则；rag-index/ 目标已有→跳过留原地（索引会重建）、目标无→整目录移；其他子目录原地保留并记日志。永不删目标、永不 raise；源==目标短路。返回日志行 list 写 stderr。
3. T3 init 清理+措辞面：project_init.py 模板删 memory_dir 行（L28）、建目录循环删 memory（L118）；tests/test_project_init.py L11 断言改为不建目录+模板无该键；commands.py L46 与 slash_completion.py L34 的 /dream 措辞→「梦境沉淀：回顾近期会话，蒸馏可复用知识到梦境知识库（默认全局 ~/.jarvis/memory/dream/）」；agent.py/dream.py/scheduler.py/tui.py/rag.py 全部动态跟随 config.memory_dir 零改动（已 grep 验证）。

### 测试
tests/test_config.py 6 处 fixture 含 memory_dir=memory 但无 cfg.memory_dir 断言→不破。新 tests/test_memory_dir.py 覆盖：缺省→全局/哨兵→全局/显式相对/显式绝对/JARVIS_HOME 覆盖/md 移动/同名异容后缀/同容幂等/dream 合并/rag-index 已存跳过/显式目录不迁移/init 无键不建目录。自建目录纪律（tempfile.gettempdir()+os.makedirs，禁 tmp_path）。

### 先例对齐
codex：memory 走 ~/.codex/ 全局用户层（跨项目）；opencode：~/.config 全局 config + 项目 config 深合并项目胜出（与本设计全局+项目 jarvis.json 合并语义一致）；deepagents 官方无 memory 目录约定（FilesystemBackend 根由调用方决定），虚拟前缀 /memories/ 原生路由机制不变、仅换 root 落点——目录策略属 harness 层自研但建立在官方机制之上，非闭门造车。

### 验收
全量 pytest 无新增失败（预存 test_config×3 不算本批）；commit + push + CI 绿。

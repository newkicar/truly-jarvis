## Tickets: javis-global-memory（纵切）

### T1 config memory_dir 哨兵解析 [done]
seam: src/config.py load_config L192。memory_dir 缺省或哨兵值（memory、空串——旧模板默认视为未配置）→ user_home()/memory（~/.jarvis/memory，JARVIS_HOME 可覆盖）；显式相对→项目根解析、绝对→原样。顶部补 import user_home。测试：test_memory_dir.py 解析组（缺省/哨兵/显式相对/显式绝对/JARVIS_HOME 覆盖）。验收：test_config.py 不破（fixture 无 memory_dir 断言）。

### T2 一次性迁移 src/memory_dir.py + main 钩子 [done]
seam: 新模块 maybe_migrate_memory(config) 返回日志行 list；main.py 两个 load_config 路径之后、build_agent 之前调用，stderr 输出 [memory] 前缀行，异常只告警不炸启动。规则：生效目录==全局默认时合并 项目根/memory/ → 全局：顶层 *.md 与顶层常规文件（目标无→move；同名同容→跳过留源幂等；同名异容→{stem}__{项目名} 再冲突加 __N 计数）；dream/ 子目录逐文件同规则；rag-index/ 目标已存→跳过留原地（索引不可合并会重建）、目标无→整目录移；其他子目录原地保留记日志；源==目标短路；永不删目标、永不 raise。测试：迁移组 8 条。

### T3 project_init 清理 + /dream 措辞面 [done]
seam: project_init.py 模板删 memory_dir 行（L28）与建目录循环删 memory（L118）；tests/test_project_init.py L11 断言改为不建 memory 目录 + 模板无该键；commands.py L46 与 slash_completion.py L34 /dream 措辞→默认全局 ~/.jarvis/memory/dream/。agent.py/dream.py/scheduler.py/tui.py/rag.py 动态跟随 config.memory_dir 零改动。

批次收尾：清理 .scratch 一次性脚本、AGENTS.md 新条目、全量 pytest、commit + push + CI 检查。

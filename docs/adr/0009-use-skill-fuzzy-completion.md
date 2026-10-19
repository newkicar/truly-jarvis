# ADR-0009: /use skill 名称模糊补全

**状态:** 已接受（2026-10-19）

## 背景

tui-ux5 起 manual-only skill（ADR-0007）后，`/use <skill> [说明]` 是手动注入 skill 指令的唯一入口。两个痛点：① 用户输入 `/use `（带空格）后，`slash_query` 遇空格即返回 None，补全 overlay 直接落到 `@` 路径分支——**零候选提示**，用户须先查 `/skills` 记住名字；② skill 名普遍含 `-`（如 `book-meeting-room`），精确匹配也要把连字符敲全。

## 决策

1. **候选池 = 全部 skill**（不限 manual-only）：manual-only 的语义是「模型不自动调用」（ADR-0007），不是「`/use` 不能指定」；非 manual skill 也可经 `/use` 手动注入（覆盖模型自动判断、注入当轮全文）。
2. **仅匹配 `name`、大小写不敏感（casefold）**；不匹配 description 与全文。
3. **四档匹配**（高档先、不跨档混排）：① 精确 > ② 前缀 > ③ 子串 > ④ 子序列（贪心左到右，可跳过 `-` 与任意字符，`bkmtg` → `book-meeting-room`）；子序列档内命中块更少（更连续）者优先、再按名称短者优先，同分按名称序。
4. **20 条上限**：空 query → 名称序前 20；无匹配 → 空列表（overlay 自动隐藏）。
5. **数据层与 TUI 层分离**：`src/skill_discovery.py` 新增 `fuzzy_filter_skills(catalog, query, limit=20)`（纯 stdlib 纯函数、唯一数据缝）；TUI 侧 `src/tui_completion.py` 新增 `use_query(value, cursor)`（触发判定，at_index=5）与 `_skill_item` 行映射，`resolve_overlay_state` 增 `skills=` 参数与 kind="skill"；overlay 控件与 `apply_suggestion` **零改动复用**（接受候选后输入框变 `/use <skill> `，可续打说明）。
6. **触发边界**：`/use ` 后恰好一个空格且 query 内无空格才触发；`/use`、`/uses`（无空格/前缀）走 slash 补全语义；出现第二个空格（进入说明段）→ 关闭 overlay；`skills=None`（config 缺失或发现异常）→ 静默回落 kind="none"，不崩。
7. **不缓存**：TUI 逐键重跑 `discover_skill_catalog`（新增 skill 即现）；`/use` 执行内核与 CLI 行为不变。

## 被否决的选项

- **desc/全文匹配**：信号面过宽（多个 skill 的 description 用词重叠），且用户意图是「挑名字」不是「搜描述」；保持 name-only。
- **编辑距离或引入 fuzzy 依赖（fuzzymatch/thefuzz 等）**：四档贪心子序列已覆盖跳字匹配且纯 stdlib，第三方依赖无实质增益。
- **结果缓存**：skill 目录变更低频但重扫成本毫秒级；逐键重扫更简单、无失效逻辑、新 skill 即现。
- **说明段补全**（skill 名后空格之后继续给候选）：说明是自由文本，候选无意义。

## 影响

- `src/skill_discovery.py`：新增 `fuzzy_filter_skills` + `_subsequence_runs`（数据层，纯 stdlib）；`SkillMeta` / `discover_skill_catalog` 不变。
- `src/tui_completion.py`：`use_query`、`_skill_item`、`OverlayState.kind` 增 `"skill"`、`resolve_overlay_state(skills=...)`。
- `src/tui.py`：`_skills_catalog`（逐键重扫、不缓存；config 缺失/异常 → None），接入 `resolve_overlay_state`。
- `src/slash_completion.py` / `src/commands.py`：`/use` 帮助行与 `/skills` 尾部措辞同步（明确「也可指定任意 skill」）。
- 测试：`tests/test_skill_discovery.py` +8、`tests/test_tui_completion.py` +7；全量 pytest 无新增失败。

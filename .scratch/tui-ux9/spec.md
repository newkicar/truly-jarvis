# TUI 体验九（tui-ux9）：/use skill 名称模糊补全

**Type:** feature
**Status:** ready-for-agent
**Blocked by:** 无（skill 目录发现 #09 已落地，overlay 基建已有，纯增量）

## Problem Statement

`/use <skill> [说明]`（ADR-0007 manual-only skill 机制）要求**精确** skill 名称。
skill 散布全局层 `~/.jarvis/skills/` 与项目层 `config.skills` 两层；
TUI 的 `/` 补全（`slash_query`）在第一个空格即失效（query 含空格 → 返回 None），
因此键入 `/use ` 之后对可用的 skill 名称**零提示**——用户必须先 `/skills` 翻清单，
再精确手抄名称（名称长且含 `-`，如 `skill-book-meeting-room`），易拼错、效率低。

## Solution

两个工单串行：01 数据层 `fuzzy_filter_skills`（`src/skill_discovery.py` 纯函数），
02 TUI 层 `/use` skill overlay（`src/tui_completion.py` + `src/tui.py` 接线 + 措辞 +
ADR-0009 + AGENTS.md 一行）。

TUI 输入框键入 `/use `（光标位于第二个 token 内）时，弹出 skill 名称补全 overlay
（复用现有 `PathCompletionOverlay` 组件与 `apply_suggestion` 逻辑）：

- 空 query → 展示全部候选（至多 20 条，名称排序）；
- 边输边缩窄：仅匹配 name、大小写不敏感、子序列匹配（中间可跳过 `-` 与任意字母，
  如 `bkmtg` → `book-meeting-room`、`bookmtg` → `book-meeting`）；
- 排序四档：精确（CI）> 前缀 > 子串 > 子序列；子序列档内命中块更少（更连续）者先，
  再按名称更短者先；结果截断 20 条；
- 每行 = `name`（manual-only 追加 `[manual]` 标记）+ description 截断 40 字符 hint；
- Tab/Enter 接受高亮行，插入「skill 名 + 尾随空格」（`apply_suggestion` 现有语义，
  零改动），输入框变为 `/use <skill> `，光标在空格后可直接续打说明；
- 第二个空格（进入说明段）或任何其他形态 → 隐藏 overlay；
- 候选池 = `discover_skill_catalog(config)` 的**全部** skill（全局 + 项目两层，
  后层同名覆盖）；非 manual-only skill 同样可被 `/use` 注入（ADR-0007 的
  manual-only 语义只限制*模型自动调用*，不限制用户手动注入）。

## User Stories

1. 作为 TUI 用户，我键入 `/use ` 后立即看到全部候选 skill 名（前 20，名称排序），
   不必先查清单。
2. 作为用户，我每敲一个字符候选集实时缩窄，overlay 始终反映截至光标的输入。
3. 作为用户，我跳过 `-` 打字（如 `bookmtg`）仍能命中 `book-meeting` 系名称。
4. 作为用户，我跳过若干字母打字（如 `bkmtg`）仍能命中 `book-meeting-room`。
5. 作为用户，我不必关心大小写（`BOOKMTG` 同样命中）。
6. 作为用户，多候选都命中时，更短、更连续的名称排在前面（排序可预期）。
7. 作为用户，无匹配时 overlay 隐藏（与 @ 路径补全空结果行为一致）。
8. 作为用户，我用上下键选择、Tab/Enter 接受高亮行。
9. 作为用户，接受后输入框恰为 `/use <skill> `（尾随空格，光标其后，可直接打说明）。
10. 作为用户，接受后再按空格（开始输入说明段）overlay 消失，后续输入不再当 skill 名。
11. 作为用户，manual-only skill 行尾带 `[manual]` 标记，与常规 skill 视觉可区分。
12. 作为用户，每行 hint 显示 description 截断 40 字符，帮我确认选对 skill。
13. 作为用户，我可以用 `/use` 指定**非** manual-only skill，专门注入某个想用的 skill。
14. 作为用户，`/use`（不带空格）仍走原 `/` 命令补全，互不干扰。
15. 作为用户，`/uses`（不带空格）不触发 skill 补全。
16. 作为用户，新增/修改 skill 后下一次输入立即出现（无缓存，逐键重扫）。
17. 作为用户，skill 目录为空或无 config 时 overlay 静默不显示，应用不崩。

## Implementation Decisions

- **数据层（工单 01，`src/skill_discovery.py`）**：新增纯函数
  `fuzzy_filter_skills(catalog: list[SkillMeta], query: str, limit: int = 20) -> list[SkillMeta]`：
  - 大小写不敏感（两侧 lower）；
  - 四档匹配（高档先，不跨档混排）：① 精确 ② 前缀 ③ 子串 ④ 子序列
    （贪心左到右，`-` 与任意字符可跳过）；
  - 子序列档内：命中块更少（更连续）者先，再按名称短者先；
  - 空 query → 名称排序的 catalog 前 `limit` 条；无匹配 → `[]`；
  - 纯 stdlib，不引新依赖；不改 `discover_skill_catalog` / `SkillMeta`。
- **TUI 层（工单 02，`src/tui_completion.py`）**：
  - `use_query(value, cursor) -> tuple[int, str] | None`：`value[:cursor]` 形如
    `/use <q>`（`/use` 后恰好一个空格，q 内无空格）→ 返回 `(5, q)`；否则 None；
  - `resolve_overlay_state` 增加可选 kwarg `skills: list[SkillMeta] | None = None`
    （None = 功能关闭，不崩）；`OverlayState.kind` 的 Literal 扩为含 `"skill"`；
    命中时 items = `fuzzy_filter_skills(skills, q)` 映射为
    `SuggestionItem(insert=name, label=name(+ " [manual]"), hint=desc[:40]+("…" if 截断))`；
    过滤与排序全部委托数据层，TUI 层不写模糊逻辑；
  - `apply_suggestion` 零改动（自动补尾随空格）。
- **接线（工单 02，`src/tui.py`）**：`_refresh_suggestions`（约 L1453）每次按键传
  `skills=discover_skill_catalog(self.config) if self.config else None`——逐键重扫、
  不缓存（新 skill 立即出现）；`config is None` → 静默降级，无 skill 补全。
- **措辞（工单 02）**：`slash_completion.py` 的 `/use` 帮助行 →
  「手动注入指定 skill（名称模糊补全）」；`commands.py` `skills_report` 尾部说明
  增加「也可 /use <skill> [说明] 指定任意 skill」。
- **文档（工单 02）**：新增 `docs/adr/0009-use-skill-fuzzy-completion.md`
  （决策：候选池 = 全部 skill；name-only 子序列模糊；四档 + 连续度排序；
  20 条上限；复用 overlay 与 apply_suggestion；`/use` 内核精确匹配语义不变）
  + AGENTS.md TUI 段一行（TUI 体验九：/use skill 模糊补全）。
- **不改动**：`/use` 执行内核（`expand_use_command` / `build_skill_use_message`
  的精确匹配行为）、CLI 路径、`@` 路径补全、`slash_query` 逻辑、
  `discover_skill_catalog` 发现规则（后层同名覆盖）。

## Testing Decisions

- 两个纯函数缝，不新增 Textual app driver：
  - 缝① `fuzzy_filter_skills` → `tests/test_skill_discovery.py` 追加：
    钉子用例 `bkmtg→book-meeting-room`（跳 `-` 与字母）、`bookmtg→book-meeting`
    （跳 `-` + 短名胜）、大小写不敏感、四档排序、子序列打平（块数 → 长度）、
    空 query = 名称排序前 20（构造 25 条断言截断）、无匹配 = 空列表；
    SkillMeta 直接构造 fixture，无文件系统。
  - 缝② `resolve_overlay_state` → `tests/test_tui_completion.py` 追加：
    触发/关闭边界（`/use x` 触发、`/use` 无空格 → slash kind、`/uses` 不触发、
    双空格关闭、光标在 token 中段）、`skills=None` 不崩、items 顺序与
    `fuzzy_filter_skills` 输出一致（透传断言）、`[manual]` 标记与 40 字 hint 格式。
- 回归面：`test_tui_completion` / `test_skill_discovery` / `test_slash_completion` /
  `test_tui` 全绿；全量 pytest 无新增失败（预存失败不变）。
- 纪律：不用 `tmp_path`（本机 pytest 临时目录中毒，已知陷阱）；测试直接构造
  SkillMeta，或 `os.makedirs` 自建目录。

## Out of Scope

- description / 全文匹配（决策：仅匹配 name）。
- `@` 位置的 skill 补全。
- CLI（`--cli`）的 skill 名补全（CLI 无 overlay）。
- catalog 缓存 / 热加载事件（逐键重扫即满足当前规模）。
- `/use` 内核精确匹配语义变更（overlay 插入的名称走内核原路径，零改动）。
- hint 中的层来源标注（skill 来自全局层还是项目层）。

## Further Notes

- 缝清单：① 数据函数 `fuzzy_filter_skills`（skill_discovery.py），
  ② TUI 状态函数 `resolve_overlay_state(skills=...)`（tui_completion.py）；
  接线正确性由 ② 的参数测试 + 既有 overlay 回归 + 手动冒烟（`smoke_test --tui`）覆盖。
- 系列：tui-ux4…8 已落地（对应 ADR-0005–0008），本批 = tui-ux9，ADR-0009 为下一空号。
- 工单线性依赖：01（数据层，无依赖）→ 02（TUI 层，Blocked by 01）。
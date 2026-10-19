# 02 — TUI /use skill overlay（触发 + 接线 + 措辞 + ADR-0009）

**What to build:** 在 01 的 `fuzzy_filter_skills` 之上，让 TUI 键入 `/use ` 后弹出
skill 名称补全 overlay（复用现有 `PathCompletionOverlay` 与 `apply_suggestion`）：

- `src/tui_completion.py`：
  - `use_query(value, cursor) -> tuple[int, str] | None`：`value[:cursor]` 形如
    `/use <q>`（`/use` 后恰好一个空格、q 内无空格）→ `(5, q)`；
    `/use` 无空格 / `/uses` / 双空格 → None；
  - `resolve_overlay_state` 增加可选 kwarg `skills: list[SkillMeta] | None = None`
    （None = 功能关闭，不崩）；`OverlayState.kind` 的 Literal 扩为含 `"skill"`；
    命中时 items = `fuzzy_filter_skills(skills, q)` 映射为
    `SuggestionItem(insert=name, label=name(+ " [manual]" if manual_only else ""),
    hint=desc[:40] + ("…" if len(desc) > 40 else ""))`；过滤/排序全部委托数据层；
  - `apply_suggestion` 零改动（接受时自动补尾随空格 → 输入框变 `/use <skill> `，
    光标在空格后，可直接续打说明段）。
- `src/tui.py` `_refresh_suggestions`（约 L1453）：每次按键传
  `skills=discover_skill_catalog(self.config) if self.config else None`
  （逐键重扫不缓存——新增/修改 skill 下一次输入即现；config None → 静默降级）。
- 措辞：`src/slash_completion.py` 的 `/use` 帮助行 → 「手动注入指定 skill（名称模糊补全）」；
  `src/commands.py` `skills_report` 尾部说明增加「也可 /use <skill> [说明] 指定任意 skill」。
- 文档：新增 `docs/adr/0009-use-skill-fuzzy-completion.md`（决策：候选池 = 全部
  skill（含非 manual-only；manual-only 只限模型自动调用，ADR-0007 语义不变）/
  name-only 子序列模糊 / 四档 + 连续度排序 / 20 条上限 / 复用 overlay 与
  apply_suggestion / `/use` 内核精确匹配不变）+ AGENTS.md TUI 段一行
  （TUI 体验九：/use skill 模糊补全）。
- 测试（`tests/test_tui_completion.py` 追加，纯函数缝，无 Textual driver；
  SkillMeta 直接构造，不用 `tmp_path`）：
  - 触发/关闭边界：`/use x` 触发（kind="skill"）、`/use` 无空格 → slash kind 不变、
    `/uses` 不触发、双空格关闭、光标在 token 中段正常；
  - `skills=None` 不崩（kind="none"）；
  - items 顺序与 `fuzzy_filter_skills` 输出一致（透传断言）；
  - `[manual]` 标签与 40 字 hint 格式（含 `…` 截断）。

**Type:** feature
**Status:** done (2026-10-19, commit 06d565d)
**Blocked by:** 01（fuzzy_filter_skills）

## 验收
- [x] use_query 触发/关闭边界测试全绿（含 `/use` 无空格 → slash、`/uses` 不触发、双空格关闭）
- [x] `skills=None` 不崩；items 顺序透传、`[manual]` 标签、40 字 hint 断言全绿
- [x] `/use` 帮助行与 `/skills` 尾部说明措辞更新
- [x] ADR-0009 与 AGENTS.md 一行落文档
- [x] `tests/test_tui_completion.py` / `test_slash_completion.py` / `test_tui.py` 无回归；全量 pytest 无新增失败

## Comments

实施记录（实现提交 06d565d）：
- `src/tui_completion.py`：`use_query`（`/use <q>` 且 q 内无空格才触发，at_index=5；`/use` 无空格 / `/uses` / 双空格说明段均不触发）；`resolve_overlay_state` 增可选 kwarg `skills`，命中时 `OverlayState.kind` = "skill"（复用 overlay 与 `apply_suggestion` 零改动，接受后输入框 = `/use <skill> ` 可续打说明）；过滤/排序全部委托 `fuzzy_filter_skills`；候选池 = 全部 skill（非 manual-only 亦可 /use 指定；manual-only 语义只限模型自动调用，ADR-0007 不变）。
- `src/tui.py` `_skills_catalog` 逐键重扫不缓存（新增/修改 skill 下一次输入即现；config 缺失/异常 → None 静默降级不崩）。
- 措辞同步：`slash_completion` /use 行「手动注入指定 skill（名称模糊补全）」+ `skills_report` 尾「/use 也可指定任意 skill」。
- `docs/adr/0009-use-skill-fuzzy-completion.md` 新增（实现提交）；AGENTS.md TUI 体验九一行记录于本 docs 提交（commit 2）。
- `tests/test_tui_completion.py` +7 条测试（纯函数缝，无 Textual driver，不用 `tmp_path`）。

验收勾选（记录于本 docs 提交（commit 2），实现于 commit 06d565d）：
- 新增 15 条（fuzzy 8 + overlay 7）逐条点名定向全绿；批次 `python -m pytest -q --ignore=tests/test_rag.py --ignore=scratch`：406 passed；2 failed（drain flaky 已知 + HILT tempfile WinError 5 环境因素）+ 173 errors 均为基 temp WinError 5 中毒；无本改动引入的新失败。

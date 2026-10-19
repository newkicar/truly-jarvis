# 01 — 数据层 fuzzy_filter_skills（skill 名子序列模糊过滤）

**What to build:** `/use <skill>` 目前只认精确 skill 名；skill 散布全局 + 项目两层、
名称长且含 `-`（如 `skill-book-meeting-room`），用户只能先 `/skills` 翻清单再手抄。
在 `src/skill_discovery.py` 新增纯函数（工单 02 的 TUI overlay 将直接调用它）：

```python
def fuzzy_filter_skills(catalog: list[SkillMeta], query: str, limit: int = 20) -> list[SkillMeta]:
    ...
```

- 大小写不敏感（两侧 lower）；
- 四档匹配，高档先、不跨档混排：① 精确 ② 前缀 ③ 子串 ④ 子序列
  （贪心左到右，`-` 与任意字符可跳过：`bkmtg` → `book-meeting-room`、
  `bookmtg` → `book-meeting`）；
- 子序列档内：命中块更少（更连续）者先，再按名称短者先；
- 空 query → catalog（名称排序，即 `discover_skill_catalog` 输出序）前 `limit` 条；
  无匹配 → `[]`；结果一律截断 `limit`（默认 20）；
- 纯 stdlib 实现，不引新依赖；不改 `discover_skill_catalog` / `SkillMeta` / 发现规则。

直接单测（`tests/test_skill_discovery.py` 追加，SkillMeta 直接构造 fixture，
无文件系统、不用 `tmp_path`）：

- `bkmtg` → 命中且首位 `book-meeting-room`（跳 `-` 与字母）；
- `bookmtg` → `book-meeting` 排在 `book-meeting-room` 前（跳 `-` + 短名称优先）；
- 大小写：`BOOKMTG` 与 `bookmtg` 结果一致；
- 四档排序：构造覆盖 精确/前缀/子串/子序列 四档的名称集，断言档间顺序；
- 子序列打平：块数相同比长度、块数不同比块数；
- 空 query = 名称排序前 20（构造 25 条断言截断与顺序）；
- 无匹配 = 空列表；`limit` 参数生效。

**Type:** feature
**Status:** done (2026-10-19, commit 06d565d)
**Blocked by:** 无（skill 目录发现 #09 已落地，纯增量函数，可立即开始）

## 验收
- [x] 钉子用例全绿（bkmtg / bookmtg / 大小写 / 四档排序 / 块数+长度打平 / 空 query=前 20 / 无匹配=空 / limit）
- [x] `tests/test_skill_discovery.py` 既有用例无回归；全量 pytest 无新增失败

## Comments

实施记录（实现提交 06d565d）：
- `src/skill_discovery.py` 新增纯函数 `fuzzy_filter_skills`：纯 stdlib、仅匹配 name、大小写不敏感；四档 精确 > 前缀 > 子串 > 子序列（子序列贪心左到右、可跳过 `-`/任意字母，`bkmtg` → `book-meeting-room`）；子序列档内命中块少者优先、再短名优先；空 query = 名称序前 20、无匹配 = []、一律截断 limit（默认 20）；`discover_skill_catalog` / `SkillMeta` / 发现规则零改动。
- `tests/test_skill_discovery.py` +8 条测试（fixture 直接构造 SkillMeta，无文件系统、不用 `tmp_path`）：bkmtg / bookmtg / 大小写 / 四档排序 / 块数+长度打平 / 空 query=前 20 / 无匹配=空 / limit 全绿。

验收勾选（记录于本 docs 提交（commit 2），实现于 commit 06d565d）：
- 批次 `python -m pytest -q --ignore=tests/test_rag.py --ignore=scratch`：406 passed；2 failed（drain flaky 已知 + HILT tempfile WinError 5 环境因素，单独跑亦 fail）+ 173 errors 均为基 temp WinError 5 中毒；无本改动引入的新失败。

# 04 — @ 路径补全泛化（workspace 优先 + 多后缀 + 前缀）

**What to build:** 改造 `path_completion.py`：默认排序 workspace > memories > vault；workspace 扫描常见代码/配置后缀；支持 query 前缀 `@vault/`、`@mem/` 过滤域。

**Blocked by:** 03

**Status:** done

## 背景

- 现只 `rglob("*.md")`，vault 笔记淹没 workspace。  
- 路线票 07 的「Inbox 优先 vault md」偏知识库场景，需 supersede。

## 范围

- [ ] `WORKSPACE_GLOBS`：`.py` `.md` `.json` `.yaml` `.toml` `.ts` `.tsx` 等（可配置常量）  
- [ ] `sort_paths_workspace_first()` 替代或扩展 `sort_paths_inbox_first`  
- [ ] `at_query` 解析：`@vault/foo` → 只过滤 vault 候选  
- [ ] `filter_paths` limit 可调；大 vault 时避免一次缓存全量（按 query 懒扫或 cap）  
- [ ] 更新 `tests/test_path_completion.py`  
- [ ] TUI overlay 每项可选 hint（「项目」「知识库」）— 展示可在票 06

## 验收

- workspace 含 `src/foo.py` 时 `@src` 匹配 workspace 路径且排在 vault 前  
- `@vault/` 仅 vault 路径  
- 单测覆盖排序与前缀

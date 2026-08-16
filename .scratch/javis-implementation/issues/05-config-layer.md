# 05 — 配置层

**What to build:** JARVIS 能从 `.env`（当前是 `:` 分隔、小写键的非标准格式）与 `javis.json` 加载全部配置，产出可在代码里直接使用的配置对象。这是所有其它模块的基础——没有它，模型 key、vault 路径、记忆目录都无法拿到。

**Blocked by:** None — 可以立即开始

**Status:** resolved

- [x] `.env` 兼容解析：同时支持 `KEY:VALUE` 与 `KEY=VALUE` 两种分隔，键名大小写不敏感，能读出 `BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`
- [x] `javis.json` 读取：模型 env 名映射、`obsidian_vault`、`memory_dir`、`skills`、`mcps`、`schedules`
- [x] 产出配置 dataclass；所有路径转为绝对路径（Windows）
- [x] 缺关键配置时给出明确报错
- [x] 单测：两种 `.env` 格式、javis.json 解析、路径绝对化、缺 key 报错（tests/test_config.py）

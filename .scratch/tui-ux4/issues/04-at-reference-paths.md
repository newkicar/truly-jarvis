# 04 — @ 引用路径前缀映射可见化（双路径呈现）

**What to build:** 提交时路径锚点行（虚拟→真实映射）+ shell 守卫报错补真实目录 + @ 补全 dual/real/virtual 三态（默认 dual）。不改 deepagents 路由。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 01

## 验收
- [ ] commands.virtual_path_mappings(config) 返回前缀→真实根目录（workspace/vault/memories/skills）
- [ ] commands.path_anchor_lines(text, mapping) 纯函数，命中的虚拟路径出 dim 锚点行；_handle_user_message 追加
- [ ] InheritedEnvShellBackend(prefix_map=...) 守卫报错列出命中前缀的真实目录
- [ ] agent._make_backend 传 prefix_map
- [ ] tui.at_reference_style（virtual/dual/real，默认 dual）：resolve_overlay_state 按 style 转换标签/hint/插入值；缺省参数行为不变（既有测试不动）
- [ ] 单测：映射/锚点行/守卫报错/补全 style

## 参考
codex：@ 文件引用直接落真实路径，无虚拟层；本项目保留虚拟前缀（deepagents 路由），只在呈现层做映射可见化。

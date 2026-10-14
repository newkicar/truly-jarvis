# 04 — @ 引用路径前缀映射可见化（双路径呈现）

**What to build:** 提交时路径锚点行（虚拟→真实映射）+ shell 守卫报错补真实目录 + @ 补全 dual/real/virtual 三态（默认 dual）。不改 deepagents 路由。

**Type:** task
**Status:** done
**Blocked by:** 01

## 验收
- [x] commands.virtual_path_mappings(config) 返回前缀→真实根目录（workspace/vault/memories/skills）
- [x] commands.path_anchor_lines(text, mapping) 纯函数，命中的虚拟路径出 dim 锚点行；_handle_user_message 追加
- [x] InheritedEnvShellBackend(prefix_map=...) 守卫报错列出命中前缀的真实目录
- [x] agent._make_backend 传 prefix_map
- [x] tui.at_reference_style（virtual/dual/real，默认 dual）：resolve_overlay_state 按 style 转换标签/hint/插入值；缺省参数行为不变（既有测试不动）
- [x] 单测：映射/锚点行/守卫报错/补全 style

## 参考
codex：@ 文件引用直接落真实路径，无虚拟层；本项目保留虚拟前缀（deepagents 路由），只在呈现层做映射可见化。

## Comments
- 2026-10-14：done。commands.virtual_path_mappings（workspace/vault/memories + skill 层路由，config=None 兜底 {}）+ path_anchor_lines（长前缀优先、去重、上限 5 条 dim 行），_handle_user_message 用户消息后追加锚点行；InheritedEnvShellBackend 新增 prefix_map 参数，_virtual_prefix_error 命中前缀时追加「对应真实目录」指路行；agent._make_backend 组 prefix_map 传入；resolve_overlay_state 新增 path_mapping/at_reference_style（缺省 virtual 行为不变），_style_item 实现 dual/real 双路径；tui._at_reference_style 读 tui.at_reference_style（默认 dual）。单测 tests/test_at_reference.py 12 项全绿；test_shell_backend 18、test_tui_completion 2、test_commands+test_agent+test_tui 102 全绿。

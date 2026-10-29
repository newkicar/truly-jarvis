# 05 — 会话侧栏与 AI 命名

**What to build:** 左侧会话侧栏：条目 = 短名 + 摘要，当前会话高亮，「＋ 新会话」一键开 thread（切会话换栈不重建 runtime，01/03 既有模型）；`sched-*` 线程过滤（沿用 CLI 展示约定 + 自动清理）。会话默认名 = **AI 一次性总结**（用户裁定：首轮 `finalize_turn` 后后台生成，用当前模型小 prompt；失败/超时静默回落首条用户消息截断 18 字），支持手动改名。存储 = 项目级 `sessions.json` 注册表（schema 来自 spec）：

```json
{ "thread_id": { "title": "修复登录 401", "ai_generated": true } }
```

注册表 gitignore、可删（重建 = 回落摘要），检查点库不加 schema。

**Blocked by:** 01（GUI 运行时骨架）、03（对话区与输入区：会话切换=换栈的消息栈模型）

**Status:** ready-for-agent

- [ ] 侧栏列出全部非 sched-* 会话（最新在前），点击切换，新会话即时入栏
- [ ] 首轮结束自动命名（生成中占位「命名中…」，失败回落摘要，`ai_generated` 标记写回注册表）
- [ ] 右键/双击改名即时生效 + 持久化（重启 app 后仍在）
- [ ] 删 sessions.json 后重启回落摘要名，不崩
- [ ] 命名生成走后台 worker，不阻塞 UI（offscreen 可注入 fake 模型即时返回）

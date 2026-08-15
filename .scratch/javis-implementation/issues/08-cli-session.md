# 08 — CLI 会话

**What to build:** 用户在终端启动 `python src/main.py` 进入对话，用自然语言提问，JARVIS 走完整心智管道给出回答。会话有记忆：重启后同一会话的上下文仍在，可延续讨论。支持 `/exit` 退出。

**Blocked by:** 07

**Status:** resolved

- [ ] 标准库 `input()` 交互循环，启动即进入对话
- [ ] 每次提问经主代理 invoke，输出回答（渲染 markdown 为可读文本）
- [ ] 会话标识：`thread_id` 即 `session_id`；新会话自动分配，可指定继续某会话
- [ ] 重启后上下文仍在（SqliteSaver 持久化生效）
- [ ] `/exit` 正常退出
- [ ] 冒烟：启动 → 问「调研 XXX」→ 得到回答（可用真实模型手动验证）

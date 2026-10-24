# Spec: /compact [提示] 上下文压缩

/compact 把当前会话历史压缩为一条延续性摘要，写回 checkpointer（纯消息层；文件/Inbox 不动）。
- 可选文字引导：/compact 保留与部署相关细节 → 压缩倾向保留该主题；无引导模型自行判断。
- 实现 commands.compact(agent, thread_id, guide=None) -> str：
  1. agent._jarvis_model 缺失 → 「无法压缩上下文：模型不可用」。
  2. get_state 取 messages，不足 4 条 → 「消息太少（不足 4 条），无需压缩」。
  3. 压缩 prompt（保留 目标/约束/已完成/当前进度/未决问题/可复用的文件与命令参数；
     guide 非空追加「用户提示（压缩时优先保留与该提示相关的细节）：{guide}」），输入取 messages[-200:]。
  4. update_state(thread_config(tid), {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES),
     SystemMessage("[上下文压缩]\n"+摘要)]}, as_node="model")（与 sanitize_history 同手法，随 checkpoint 持久化）。
- 摘要为空/异常 → 友好报错，不动历史。
- TUI：/compact 进 turn gate（_gate_command_worker）；slash_completion 增一条；TUI_HELP 增 /compact 行。

## 验收
- 测试：无模型 / 消息不足 / 正常压缩（update_state 形状 + REMOVE_ALL + SystemMessage 前缀）/ guide 透传 / 摘要为空不动历史。

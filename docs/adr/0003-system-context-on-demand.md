# ADR-0003: 系统上下文按需读取（日期 / 时间 / 位置）

**状态:** 已接受（2026-08-19）

## 背景

启动时把「当前日期时间」或「用户所在地」写进主代理 `system_prompt` 会立刻过期，且污染常驻上下文。
把地址写进 `javis.json` 也不合适：用户可能在不同地点，不能写死单一坐标。

此前代理在简单问答（如「现在几点、我在哪」）上曾出现：混用宿主机绝对路径与虚拟路径、误读
`javis.json` 找 location、委派 researcher 跑本地脚本、以及把问题扩成写 `/vault/Reports/` 的报告任务。

## 决策

1. **主 system prompt 结果导向**：写目标、完成标准、约束、停止规则；不写逐步操作流程。
   细节见 `src/agent.py` 的 `MAIN_SYSTEM_PROMPT`。
2. **日期 / 时间 / 星期按需读取**：
   - 主代理工具 `get_system_context`（`src/system_context.py`），返回本机 JSON；
   - skill `skills/system-context/` 按需加载（Gotchas + 完成标准）；
   - **不**在启动时注入静态时间，**不**写入 `javis.json`。
3. **用户所在地**：
   - JARVIS **无 GPS**，不在 `javis.json` 或 `memory/user-profile.md` 预置固定「所在地」；
   - 用户问了位置时，说明无法自动定位，仅依据**当轮对话**中用户的说明作答；
   - 用户若希望长期记住常用地点，可自行编辑 `memory/*.md`，但非必填、非默认行为。
4. **Skills 虚拟路径**：`skills/` 映射为 `/workspace/skills/` 传入 deepagents，禁止模型使用 `E:/...` 探路。
5. **简单事实问答的停止规则**：能回答用户本轮问题即停，禁止顺带调研、写 Reports 或委派 researcher。

## 被否决的选项

- **启动时注入 datetime 到 system prompt**：秒级过期，且占常驻 token。
- **`javis.json` 的 `location` 字段**：把移动用户写死在机器配置里。
- **在 profile 预填默认地址**：用户不一定在同一地点，不能假设。
- **委派 researcher 执行本地时间脚本**：子代理无 `get_system_context`，且易触发无关检索/报告。

## 影响

- 新增 / 维护：`src/system_context.py`、`skills/system-context/`、`get_system_context` 主代理工具。
- `Config` 与 `javis.json` **无** `location` 字段。
- 术语见仓库根 `CONTEXT.md`；设计文档 §3 主代理提示词要点已同步。

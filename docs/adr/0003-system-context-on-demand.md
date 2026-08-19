# ADR-0003: 系统上下文按需读取（日期 / 时间 / 位置）

**状态:** 已接受（2026-08-19）

## 背景

启动时把「当前日期时间」或「用户所在地」写进主代理 `system_prompt` 会立刻过期，且污染常驻上下文。
把地址写进 `javis.json` 也不合适：用户可能在不同地点，不能写死单一坐标。

此前代理在简单问答（如「现在几点、我在哪」）上曾出现：混用宿主机绝对路径与虚拟路径、误读
`javis.json` 找 location、委派 researcher 跑本地脚本、以及把问题扩成写 `/vault/Reports/` 的报告任务。

## 决策

1. **主 system prompt 结果导向**：目标 → 工作方式 → 完成标准 → 约束 → 停止规则 → 输出（见 `src/agent.py` 的 `MAIN_SYSTEM_PROMPT`）。
2. **日期 / 时间 / 星期按需读取**：
   - 主代理工具 `get_system_context`（`src/system_context.py`），返回本机 JSON（含 `date`/`time`/`weekday`/`city`/`location` 等）；
   - skill `skills/system-context/` 按需加载（Gotchas + 完成标准）；
   - **不**在启动时注入静态时间，**不**写入 `javis.json`。
3. **用户所在地（城市级）**：
   - 由 `get_system_context` 调用 IP 地理定位 API（`ip-api.com`）**按需推算**，不写进 `javis.json`，不读 `user-profile.md`；
   - ISP 级精度，非 GPS；VPN/代理可能不准，失败时如实说明；
   - **禁止**在 profile 预填固定「所在地」作为默认答案。
4. **Skills 虚拟路径**：`skills/` 映射为 `/workspace/skills/` 传入 deepagents，禁止模型使用 `E:/...` 探路。
5. **简单事实问答的停止规则**：能回答用户本轮问题即停，禁止顺带调研、写 Reports 或委派 researcher。

## 被否决的选项

- **启动时注入 datetime 到 system prompt**：秒级过期，且占常驻 token。
- **`javis.json` 的 `location` 字段**：把移动用户写死在机器配置里。
- **在 profile 预填默认地址**：用户移动时地址会变；应用 IP 按需推算，不用静态 profile。
- **读 user-profile 找所在地**：城市应由 IP 按需推算，profile 仅承载用户偏好等非位置信息。
- **委派 researcher 执行本地时间脚本**：子代理无 `get_system_context`，且易触发无关检索/报告。

## 影响

- 新增 / 维护：`src/system_context.py`、`skills/system-context/`、`get_system_context` 主代理工具。
- `Config` 与 `javis.json` **无** `location` 字段。
- 术语见仓库根 `CONTEXT.md`；设计文档 §3 主代理提示词要点已同步。

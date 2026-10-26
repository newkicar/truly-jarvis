# 02 — LLM 用户自配（配置层 + 凭据管理 + 端点探测 + 首启向导）

**What to build:** 小白双击 exe 后配 LLM 的完整链路：用户全局 `%APPDATA%\Jarvis\config.json`（与安装目录分离、多用户隔离、损坏自愈回退最近 backup + version 单调迁移）；API key 走 `keyring` → Windows Credential Manager，config 只存 `key_ref` 不落明文，组策略禁写降级 DPAPI user-scope；保存 provider 时五档端点探测（Jan 先例，纯函数状态表）：

| 探测结果 | 文案 | 动作 |
|---|---|---|
| OK | 连接成功 | 填模型下拉 |
| 401 | 密钥无效 | 提示改 key |
| 403 | 无访问权限 | 提示找管理员 |
| 429 | 限流 | 提示稍后重试 |
| 网络错 | 连不上服务（refused 专条） | 检查网络/服务 |
| 404 | URL 缺 /v1 | 提示补全 |

`probe_supported:false`（内网网关无 /models）允许手填 model id，保存成功不算失败。首启 5 步向导可跳过（欢迎+安全承诺→选 provider 类别→填地址密钥→测试连接→选默认模型；本地推理 `sk-no-key` 占位）；key_ref 悬空（域账号重置）启动校验 → 回向导第 3 步不崩；项目 jarvis.json `model.provider` 钉住项目级 LLM 源，旧 `*_env` 键保留一个版本兼容读。

**Blocked by:** None — can start immediately（与 01 并行；GUI 骨架先用既有 .env 路径，本工单接通后切自配层）

**Status:** done（2026-10-26）

- [ ] 五档探测纯函数（status_code→文案/动作表）单测全覆盖，网络注入 fake
- [ ] keyring 读写/缺失/悬空 ref 分支测试（CM 后端可注入 fake；DPAPI 降级路径断言）
- [ ] config 损坏自愈（backup 回退 + version 迁移）单测
- [ ] 向导 5 步 offscreen 走通（可跳过、幂等重入、测试连接不过可存草稿）
- [ ] 启动读取时序：config.json→key_ref 取 key→注入 ChatOpenAI（= 既有 .env 三件套运行时等价物）

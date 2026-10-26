# T-003 研究：桌面用户自配 LLM 端点/密钥先例

> 工单：`.scratch/gui-wayfinder/tickets/T-003-llm-config.md` · 研究子代理 · 2026-10-26
> 检索方式：2026-10-26 在线检索（GitHub 仓库/官方文档，链接均真实）；个别条目本次未独立复核，标注 **【离线推断、未验证】** 或「未完全验证」。

## TL;DR 推荐

1. **配置位置 = 用户全局层 `%APPDATA%\Jarvis\`（Windows），与安装目录分离**——五个先例（Chatbox/Jan/LM Studio/AnythingLLM/Continue）全部把用户配置放在 userData/APPDATA 或系统凭据库，没有一个把用户可变的 LLM 配置打进安装包。升级/重装不覆盖用户配置；多用户机器天然隔离。现有 `jarvis.json`（项目级）保留，LLM 端点/密钥下沉到用户全局层；项目级只留「本项目钉住哪个 provider」。
2. **密钥 = Windows Credential Manager（经 Python `keyring` 库，纯 ctypes、无原生依赖）；`config.json` 里只存引用（`key_ref`）不存明文**。先例梯度：Continue = OS 凭据库存主密钥 + 本地 AES-GCM 密文；Jan/Chatbox = 本地明文文件（Electron 时代产物，可接受但不作为我们的底线）；LM Studio = 本地推理无密钥需求（`sk-no-key` 占位）。我们面向「非程序员 + 公司内网密钥」，选最高档。
3. **端点探测抄 Jan**：保存 provider 时自动 `GET {base_url}/models`；结果分 5 档（OK / 401 Invalid / 403 Forbidden / 429 Rate limited / 网络错误）+ 故障翻译表（404=缺 `/v1`、连接拒绝=服务没起）；取不到 models 允许手填 model id（Jan 原语义）。
4. **首启向导 5 步**：选 provider 类别 → 填 base_url + key → 「测试连接」→ 模型下拉自动填充 → 选默认模型；可跳过（先使用、后配置），与 LM Studio「先跑本地、后配远端」的渐进式哲学一致。

## 先例清单（带链接 + 可抄的做法）

### ① Chatbox（最直接同构：用户自配 OpenAI 兼容端点）
- 数据位置：https://chatboxai.app/en/guide/faq/data-storage —— Windows `%APPDATA%\chatbox\`、macOS `~/Library/Application Support/chatbox/`、Linux `~/.config/chatbox/`；官方 FAQ 明说 API key 本地保存、不上送服务器。
- 源码：https://github.com/chatboxai/chatbox —— `src/main/store-node.ts`：配置 = `app.getPath('userData')` 下 `config.json`；**加载校验 + 自动备份恢复**（config.json 非法 → 用最近 `config-backup-*.json` 恢复）；sqlite 放 `chatbox-databases/` 子目录（规避 Chromium 清理 userData 根目录的坑）。
- **可抄**：①userData 与安装目录分离（升级不覆盖）②config 校验 + 备份双文件模式 ③密钥本地化承诺的文案。

### ② Jan（自定义端点 + 多 key 测试 UX 的范本）
- 数据目录：https://docs.jan.ai/desktop/data-folder —— `%APPDATA%\Jan\data`（Settings→General 可改，写 `settings.json` 的 `data_folder`）；`store.json` 损坏可删重建。
- 自定义端点：https://docs.jan.ai/desktop/remote-models/custom-endpoint —— 选 OpenAI/Anthropic 兼容格式；Base URL **须含 `/v1`**；本地无鉴权填 `sk-no-key` 占位；**保存时自动 fetch `{base_url}/models`**，取不到则手动加 model id。
- 多 key 与测试 UX（同页 Advanced 节）：key #1 为主 + fallbacks；`Test keys` 按钮逐个调 `/models`，状态显示 **OK / 401 Invalid / 403 Forbidden / 429 Rate limited / Network error**；401/403/429 自动轮换下一个 key。
- 故障排查表：https://docs.jan.ai/desktop/troubleshooting —— 404=缺 `/v1`、401/403=key 问题、429=限流、connection refused=服务没起。
- **可抄**：测试连接的状态分档文案（直接对非程序员可读）；`/v1` 强制提示；key 轮换（多 provider 切换的底层机制）；store.json 可删重建的容错承诺。

### ③ Continue（密钥存储的最高档先例）
- 仓库：https://github.com/continuedev/continue —— `extensions/vscode/src/stubs/SecretStorage.ts`：**混合方案**——AES-256-GCM 主密钥存 `vscode.SecretStorage`（Windows=Credential Manager，macOS=Keychain），被加密的数据写 `globalStorage/<key>.bin`；`config.yaml` 里存明文 key 是已知问题（issue #1729，非 IDE 场景无系统凭据管理可用）。
- **可抄**：「OS 级凭据库存主密钥 + 本地文件存密文」的 key-derivation 架构（比「直接存 Credential Manager 条目」更通用，为日后同步/备份场景留路）。

### ④ LM Studio（本地推理 + 无密钥先例）
- 模型目录 `%APPDATA%\LM Studio\models\`（Win）【离线推断、未验证——LM Studio 闭源，路径来自社区文档】；本地 OpenAI 兼容 server 默认 `localhost:1234`，其他应用接入**无需 key**；bug tracker：https://github.com/lmstudio-ai/lmstudio-bug-tracker （闭源产品，GUI=Electron，先例见 T-001）。
- **可抄**：「`sk-no-key` 占位」处理本地端点（与 Jan 同语义）；首启「先跑起来、后配远端」的渐进式向导哲学。

### ⑤ AnythingLLM（服务端多用户形态的反面参照）
- 仓库：https://github.com/Mintplex-Labs/anything-llm —— API key 管理 = **服务端**（`frontend/src/pages/GeneralSettings/ApiKeys/index.jsx` → `GET /admin/api-keys`、`/system/api-keys`，见 `frontend/src/models/admin.js` / `system.js`，本次在线检索验证）；server `.env` 有 `STORAGE_DIR`。
- **desktop 端（Electron + 嵌入式 server）的本地 key 落盘方式未完全验证**（仓库顶层已重构，旧 `desktop/` 路径 404）——只作参照：多用户/服务端形态 key 集中管在 server DB，对本单机形态无先例价值。
- **可抄**：无直接可抄项（形态不同）；价值在于证明「用户自配端点 + 多 provider」在大厂桌面/服务端产品里是标配能力。

## 推荐配置 schema（对照本仓 .env / jarvis.json 现状）

### 现状（主仓 truly-jarvis-main）
- `.env`：`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY` / `SOK_API_KEY` / `SOK_SERVER_URL`；
- `jarvis.json`（项目级）：`model.{base_url_env, api_key_env, model_id_env}`（**只存 env 键名**，值在 .env）、`knowledge_base`、`rag`（Ollama bge-small-zh-v1.5 + chroma）、`mcps.servers`、`permissions`、`execution.max_steps`、`tui`、`theme`；用户全局目录 `~/.jarvis`（`JARVIS_HOME` 可覆盖）。
- 现状对非程序员用户的问题：env 键名间接引用 + 手工编辑两个文件 + 明文 .env = 三连门槛。

### GUI 版草案（两层）

**L1 用户全局**（新增，GUI 主入口；沿用 TUI 的 `JARVIS_HOME` 覆盖语义，Windows 默认 `%APPDATA%\Jarvis\`）：

```json
// %APPDATA%\Jarvis\config.json（损坏时按 Chatbox 模式自动回退 config-backup-*.json）
{
  "version": 1,
  "default_provider": "company",
  "providers": [
    {
      "id": "company",
      "name": "公司内网端点",
      "type": "openai-compatible",
      "base_url": "https://opencode.ai/zen/go/v1",
      "key_ref": "jarvis:company:api-key",
      "model": "mimo-v2.5",
      "models": ["mimo-v2.5"],
      "probe_supported": true,
      "timeout_s": 60
    },
    {
      "id": "local-llmstudio",
      "type": "openai-compatible",
      "base_url": "http://localhost:1234/v1",
      "key_ref": null,
      "model": "llama-3-8b"
    }
  ],
  "tool_keys": { "tavily_ref": "jarvis:tools:tavily", "sok_ref": "jarvis:tools:sok" }
}
```

- **密钥不入 config.json**：`key_ref` = `keyring.set_password("Jarvis", "provider:<id>", key)` 的引用；默认实现 = Windows **Credential Manager**（`keyring` 库，纯 Python/ctypes、无额外原生依赖、零安装）；备选档 = Continue 式 AES-GCM + Credential Manager 存主密钥（为日后跨机备份留路）；**明文兜底不进发布版**。
- 读取时序：启动读 config.json → 按 `key_ref` 从 Credential Manager 取 key → 注入 deepagents 的 `ChatOpenAI(base_url, api_key, model)`（即 `.env` 三件套的运行时等价物）。

**L2 项目级 `jarvis.json`**（最小改动）：`model` 段从 `{base_url_env, api_key_env, model_id_env}` 升格为：

```json
{ "model": { "provider": "company" } }
```

（钉住本项目用哪个 L1 provider；缺省 = `default_provider`）。旧键（`*_env`）保留一个版本的兼容读路径（读 .env），随 T-005 共存策略处理迁移。工具类 key（TAVILY_KEY/SOK_*）同理迁 `tool_keys` refs；`mcps.servers` 的 `env` 字段可选支持 `{ "from_credential": "jarvis:mcp:<name>" }` 引用形式（P1+）。

### 探测 / 测试连接 UX（抄 Jan，文案面向非程序员）

保存 provider 时自动 `GET {base}/models`（8s 超时）；5 档结果 + 自动动作：

| 状态 | 文案 | 自动动作 |
|---|---|---|
| OK | 连接成功 | 填充模型下拉 |
| 401 | 密钥无效 | 提示改 key；多 key 时轮换 |
| 403 | 无访问权限 | 提示找管理员开权限 |
| 429 | 限流 | 提示稍后重试 |
| 网络错误 | 连不上服务 | 检查网络/服务是否启动（connection refused 专条） |
| 404 | URL 缺 `/v1` | 提示 base_url 通常以 /v1 结尾 |

- `probe_supported: false`（内网网关未实现 /models）：允许手填 model id，保存成功不算失败（Jan 语义）。

### 首次启动向导（5 步，可跳过）

1. 欢迎 + 安全承诺（配置在本机、密钥进系统凭据管理器、不上送任何服务器——抄 Chatbox FAQ 文案）；
2. 选 provider 类别：公司内网 OpenAI 兼容 / OpenAI 官方 / 本地（LM Studio、Ollama、Jan）；
3. 填 base_url + API key（本地类走 `sk-no-key`/空 key 占位）；
4. 「测试连接」按钮（上表 UX，不通过也可存为草稿）；
5. 从模型列表选默认模型 → 完成。向导产物 = `config.json` + Credential Manager 条目，全部幂等可重入。

## 风险与未决

1. **AnythingLLM desktop 侧密钥存储未完全验证**（仅服务端 API key 管理在线验证）；结论不依赖它。
2. **Credential Manager 的机器级 vs 用户级**：默认用户级（每用户一套，符合多用户机器隔离）；域账号机器策略限制场景（组策略禁 Credential Manager 写入）需实测——办公 Windows 90%+ 场景允许【离线推断、未验证】。若受限，降级 DPAPI user-scope（`crypt32.CryptProtectData`，同样不落明文）。
3. **内网端点探测面**：公司 OpenAI 兼容网关未必实现 `/models`（Jan 的 fallback 已覆盖）；部分网关 `/models` 200 但列表为空 → 下拉为空时提示手填。
4. **L1/L2 双源真相期**（GUI 与 TUI 共存，T-005 范围）：`JARVIS_HOME` 与 `%APPDATA%\Jarvis` 的映射规则、`*_env` 旧键弃用时间表，待 T-005 定案。
5. **keyring 的 edge case**：Credential Manager 条目丢失/域账号重置后 `key_ref` 悬空 → 启动时校验 ref 可达性，缺失即回向导第 3 步（不崩）。
6. **升级不覆盖的配套**：config.json 的 `version` 字段 + 单调迁移器（Chatbox 备份双文件是最后一道保险）；Nuitka onedir 装到 Program Files（只读）而 config 在 %APPDATA%（可写）——路径分离天然成立，但首启须在非管理员权限下能完成全部写入（勿写安装目录）。
7. **同步/备份**（P2，未决）：Continue 的 AES-GCM 密文文件模式为「跨机备份 key」预留了升级路径，本期不做。

## 链接总表（2026-10-26 在线检索）

- Chatbox 数据位置 FAQ https://chatboxai.app/en/guide/faq/data-storage ｜ 源码 https://github.com/chatboxai/chatbox （`src/main/store-node.ts` 配置校验/备份）
- Jan 数据目录 https://docs.jan.ai/desktop/data-folder ｜ 自定义端点 https://docs.jan.ai/desktop/remote-models/custom-endpoint ｜ 故障排查 https://docs.jan.ai/desktop/troubleshooting
- Continue 密钥存根 https://github.com/continuedev/continue （`extensions/vscode/src/stubs/SecretStorage.ts`；明文 config.yaml 已知问题 issue #1729）
- LM Studio bug tracker https://github.com/lmstudio-ai/lmstudio-bug-tracker （闭源，models 路径为社区口径【离线推断】）
- AnythingLLM https://github.com/Mintplex-Labs/anything-llm （`frontend/src/pages/GeneralSettings/ApiKeys/index.jsx`、`frontend/src/models/admin.js` 服务端 API key 管理，本次验证）
- Python keyring（Credential Manager 绑定，方案实现库）https://pypi.org/project/keyring/
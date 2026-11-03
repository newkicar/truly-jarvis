# GUI 双 bug 调研：wordwrap 撑宽窗口 & read_file 二进制内容 400

> 调研日期：2026-11-03 · 在线检索（GitHub / 官方文档，链接逐一打开验证；标注【推断】的为离线推理）
> 触发工单（GUI 使用发现）：① 标准（非最大化）窗口下 AI 消息返回后窗体被突然撑宽——文本应适应窗体宽度自动换行，而非窗体适应文本 ② read_file 读取不支持格式文件直接报错整轮死亡——需降级错误、继续运行
> 原则（AGENTS.md）：先去 GitHub / 官方文档找现成解法，严禁闭门造车

## TL;DR

- **① Qt 侧**：QLabel `setWordWrap(True)` 时 minimumSizeHint 不计入换行（官方文档明示），内容含不可断行 token（长 URL / base64 / 文件路径 / 缩略图占位行）时 token 宽度会传播到布局最小宽度进而抬高窗口下限。现成解法 = 子类钳制 minimumSizeHint（我们 `CapLabel` 钳 48px）+ 缩略图行放入无边框横向 `QScrollArea`。先例：Qt 官方文档 QLabel.setWordWrap、StackOverflow 78276854、Qt 论坛 163503、pyedifice#41、Riverbank 邮件列表（PySide 维护者，2010）。
- **② 代理侧**：deepagents 内置 `read_file` 对命中扩展名表的文件返回标准多模态 content block（image/file/audio/video，base64）（deepagents 官方 multimodal 文档）；「模型是否支持该模态」明确由应用侧核对，文档推荐姿势 = 落盘 artifact + 返回短文本描述与路径。我们的模型 mimo-v2.5 为 text-only，媒体块原样回传 OpenAI 兼容网关即 400 「Unsupported content part」整轮死亡。
- **② 的现成先例 = opencode**：`packages/core/src/session/model-request.ts` 的 `unsupportedParts(messages, model.capabilities)` + `replaceMedia` 把不支持的媒体换成占位文本（`IMAGE_REMOVED` 文案即「内容已被移除、勿宣称了解其内容」），`image-generate.ts` 以 `model.capabilities.input` 做能力门控。deepagents 上游无按模型降级的开箱能力（同族 issue 仍开放：langchain-ai/deepagents#6760 read_file 无二进制尺寸上限；langchain-ai/openwiki#65 read_file 在 Anthropic 上 400 崩溃；交叉信号 openai/codex#28316 大 base64 图 tool output 重发问题也未闭环）。
- **结论**：② 项目侧新增 `src/media_guard.py`（`vault_guard.py` 的同级守卫）：无状态共享实例 middleware，模型调用前把媒体 block 降级为中文占位文本（保留 path + mime，提示换文本方式解析），干净输入零开销；`model_image_input="on"`（真多模态）时不挂载。

## 1. Bug ① wordwrap 撑宽窗口（Qt / PySide）

证据（均已验证）：
- Qt 官方文档 QLabel.setWordWrap：wordwrap 下「size hint 计入换行，但 minimum size hint 不计入」——这是窗口下限被撑高的根因，属 Qt 长期行为而非缺陷。
- StackOverflow 78276854「Layout ignoring sizeHints when QLabel with text wrap is present」：wordwrap label 在布局中时布局忽略其 sizeHint、token 宽传播到窗口。
- Qt 论坛 163503「Issue with QLabel and wordwrap」（2025-10 仍在出现同类问题）。
- pyedifice/pyedifice#41「Label wrapped vertical size」：rich text + wordwrap 与布局管理器 sizing 不一致。
- Riverbank（PySide 维护方）邮件列表 2010：「QLabel word wrap causes incorrect sizeHint」。

我们的修法（`src/gui/pane.py`，对应测试 `tests/test_gui_pane.py` +3）：
- `CapLabel(QLabel)` 覆写 `minimumSizeHint`：横向钳 48px、纵向保留——不可断 token 不再推宽窗口，文本随窗体宽度自动换行（「文字适应窗体」语义）；
- AI 图片缩略图行（横向气泡行）宿主包入无边框 `QScrollArea`（H ScrollBarAsNeeded / V AlwaysOff、固定高度），溢出走横向滚动而非撑大布局；
- `ChatPane.minimumSizeHint` 降为 `QSize(200,120)` 给布局留呼吸。
UI 层问题，与 deepagents 无关；参考解法即「钳制部件最小尺寸提示」这一通用 Qt 惯用法。

## 2. Bug ② read_file 不支持格式整轮死亡（deepagents / langchain）

现成解法与缺口：
- deepagents 官方文档（docs.langchain.com/oss/python/deepagents/multimodal，2026-11-03 验证）：
  - 内置 `read_file`「对支持的多模态文件返回标准 content blocks 而非纯文本」（扩展名表：.png/.jpg/.jpeg/.gif/.webp/.heic/.heif、.mp4/.mov/...、.wav/.mp3/...、.pdf/.ppt/.pptx），并明确「when the selected model supports the corresponding modality. Check the provider documentation」——模态门控是应用的责任，框架不做；
  - 文档对大二进制的推荐姿势：「save the artifact to a backend and return a concise text description plus a path or URL. This keeps message history smaller」——与我们占位文本方案同形；
  - 上下文压缩只对文本有效（summarization 会丢媒体块、offloading 只数 token）——多模态负载规划是应用侧的事。
- 上游缺口（同族问题仍开放，证明无现成开箱能力）：
  - langchain-ai/deepagents#6760「read_file has no size limit for inline binary content」：9 MiB PDF → 12.6M 字符 ToolMessage；
  - langchain-ai/openwiki#65「read_file crashes with Anthropic 400 on extensionless files」：MIME 仅按扩展名猜 + 不支持块直传 → 400 崩溃，与我们同族；
  - 交叉框架信号：openai/codex#28316「Codex should not resend large base64 image tool outputs」——codex 的历史 base64 重发问题也未闭环。
- 我们的具体根因链：mimo-v2.5 在 models.dev 无 profile（能力全默认 True）+ ChatOpenAI 对非 PDF file block 的宽容假设 → base64 媒体块回传 OpenAI 兼容网关 → 400 「Unsupported content part」→ 整轮死亡。

## 3. 成熟框架对照：opencode 的现成形状

- anomalyco/opencode `packages/core/src/session/model-request.ts`（2026-11-03 验证）：
  - `unsupportedParts(messages, model.capabilities, provider)` 按模型能力算出不支持的媒体 part；
  - `replaceMedia(messages, ...)` 将之替换为占位文本；`IMAGE_REMOVED` 文案：「[This image was removed to reduce the request size... Do not make claims about its contents from memory...]」——「删了并且告诉模型删了、别装知道」，与我们的占位文本同形；
  - `image-generate.ts` `acceptsImages(model)` 以 `model.capabilities.input` 门控。
- openai/codex `codex-rs` local_file_system 【推断】：其 fs 层为 raw-bytes 读写（sandbox + 策略，不做模型门控编码），媒体处理依赖 OpenAI Responses API 协议，#28316 表明其历史重发问题仍在处理中。
- langchain model profile 方案【评估后否决】：即便为 mimo-v2.5 写 text-only profile，deepagents read_file 的扩展名表（image/file block）并不读 profile，块已在 ToolMessage 里原样回传；可用注入点只有应用侧模型调用 middleware（wrap/awrap_model_call）。

结论：无可直接复用的 drop-in（opencode 实现绑定其 Model.Capabilities 目录与 Effect 运行时），但「能力门控 + 占位文本替换」模式已被验证；我们用 deepagents AgentMiddleware 实现同模式（scrub 函数 + 无状态共享实例，挂载 ~40 行）。

## 4. 落地映射（对应代码）

- `src/media_guard.py`（新增）：`scrub_unsupported_media_blocks`（image/file/audio/video block → 中文占位文本，保留 read_file_path + mime，提示改用 execute 跑解析脚本等文本方式；干净输入按引用原样返回，零开销）+ `MediaGuardMiddleware`（wrap/awrap 独立实现、无状态共享实例安全、langchain 1.3.18 / 1.4.6 版本无关）。
- `src/agent.py`：`model_image_input == "on"` 不挂，其余自动挂；同实例经 `subagents.py` / `config_agents.py` 注入 researcher / knowledge_keeper / 自定义子代理。
- `tests/test_media_guard.py` +8：占位替换 / 干净零开销恒等 / Human-AI 不触碰 / wrap+awrap 双路 / 子代理接线（test_subagents 4 类 spec、test_config_agents 3 件套契约联动）。
- 已知边界：占位文本只告知模型「该内容被略过」；真要解析二进制仍需工具路线（execute + 解析脚本 / RAG 分块），守卫只做「不整轮死亡」兜底。

## 附：验证日期与版本
- deepagents 0.7.x / langchain（本机 dev 1.3.18、CI 1.4.6）；GUI = PySide6。
- 2026-11-03 在线验证：Qt QLabel 文档 / StackOverflow 78276854 / Qt 论坛 163503 / pyedifice#41 / deepagents multimodal 文档 / deepagents#6760 / openwiki#65 / codex#28316 / opencode model-request.ts + image-generate.ts。

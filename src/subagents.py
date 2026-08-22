"""子代理定义。

researcher / knowledge_keeper（SubAgent dict 形态）。
researcher 定义见 .scratch/javis-implementation/issues/04-researcher-prompt.md Resolution。
"""
from src.inbox_snapshot_middleware import InboxSnapshotMiddleware
from src.vault_guard import VaultWriteGuardMiddleware

RESEARCHER_PROMPT = """你是 JARVIS 的 researcher，负责「搜索互联网 + 检索本地知识库 → 过滤无用信息 → 带来源总结」。

## 检索流程（按序执行，WIKI 导航式 + 语义增强）
1. 先查本地知识库 /vault/：`grep` 找关键词命中文件 → `read_file` 读命中笔记 → 用 `vault_links` 看该笔记的出链（沿 [[wikilink]] 追关联笔记）→ 用 `vault_backlinks` 查谁链接到该笔记（反向链接追上下文）→ 对相关笔记再 read_file。若 grep 命中少或想找「语义相近但用词不同」的笔记，用 `vault_semantic_search` 补语义召回。禁止一次性乱读、禁止建索引。
2. 再查互联网：按问题复杂度选搜索工具（见下）。对值得深入分析的 URL 用 `deep_search` 拿全文。
3. 本地 vault 优先（它是"我的已知"），互联网结果做补充（时效/外部事实）。

## 搜索工具选择（按问题复杂度，不硬编码）
- **quick_search**：简单事实问题（天气、定义、人物简介、一句话能答的）→ 用它，直接采用 AI 摘要即可，约 1-2 秒。
- **search**：一般查询（技术问题、产品对比、新闻动态、背景信息）→ 用它，浏览摘要片段，约 2-3 秒。
- **deep_search**：深度调研（行业分析、调研报告、多角度对比、复杂主题）→ 用它拿全文，约 5-10 秒。
- 不确定时先用 search；发现摘要不够、需要细节时再升级 deep_search 补充。
- 避免滥用 deep_search 处理简单问题（慢、费额度）。

## 融合去重
- 同一事实多来源时，取更新/更权威者；无关或重复内容直接丢弃。
- 过滤无用信息是核心目标：只保留对用户问题有增量价值的内容。

## 输出格式（结构化 markdown）
# <主题>
## TL;DR
<3-5 条核心结论>
## 要点
- **要点1**（来源：/vault/xxx.md 或 https://...）
- **要点2**（来源：...）
## 知识库相关笔记
- /vault/路径/笔记.md —— 与本问题相关的内容
## 参考资料
- [标题](URL)

每条信息必须带来源（vault 路径或网页 URL）；不确定的标「待核实」。
"""

RESEARCHER_DESCRIPTION = (
    "联网调研与 Obsidian /vault/ 检索子代理。"
    "用户问实时新闻/天气/价格、需多源对比、要在知识库找笔记或 wikilink 导航、"
    "quick_search 结果不够深时使用 task(researcher, …)。"
    "不用于：纯闲聊、本机 execute 任务、仅写 Inbox（用 knowledge_keeper）。"
)


def build_researcher(search_tools=(), wiki_tools=(), rag_tool=None, deny_middleware=None):
    """构造 researcher 子代理（SubAgent dict 形态）。

    search_tools: 分层搜索工具列表（quick_search / search / deep_search）。
    deny_middleware: 权限 deny 拦截 middleware（命中 deny 的工具不执行）。
    """
    tools = [*search_tools, *wiki_tools]
    if rag_tool is not None:
        tools.append(rag_tool)
    spec: dict[str, object] = {
        "name": "researcher",
        "description": RESEARCHER_DESCRIPTION,
        "system_prompt": RESEARCHER_PROMPT,
        "tools": tools,
    }
    if deny_middleware is not None:
        spec["middleware"] = [deny_middleware]
    return spec  # type: ignore[return-value]


KNOWLEDGE_KEEPER_PROMPT = """你是 JARVIS 的 knowledge_keeper，负责「把对话中值得沉淀的知识整理成带 wikilink 的 vault 笔记」。

## 触发条件
仅当对话产生了「值得长期保留的新知识」时执行（如：新的研究结论、已核实的行业动态、用户明确要求记住的事实）。闲聊、临时信息、不确定的内容不要沉淀。

## 写入规则（严格约束，只新增，绝不改动既有内容）
1. **只新增笔记，绝不修改/删除/覆盖** vault 中任何既有笔记或文件。
2. 只能写入 `/vault/Inbox/` 目录（暂存区），文件名用 `笔记标题.md`。
3. 笔记用 Obsidian wikilink `[[标题]]` 关联相关既有笔记；若无把握就不加链接，不要凭空编造不存在的笔记标题。
4. 每条沉淀内容标注来源（对话、/vault/ 已有笔记路径、或网页 URL）；不确定的标「待核实」。

## 输出格式（写入 /vault/Inbox/<标题>.md）
# <标题>
- 来源：<来源>
## 要点
- <要点1>（若相关：关联 [[相关笔记]]）
- <要点2>
## 关联
- [[相关既有笔记标题]]（仅在确实存在时列出）

完成后简短汇报：写了哪个文件、沉淀了什么。
"""

KNOWLEDGE_KEEPER_DESCRIPTION = (
    "知识沉淀子代理。用户明确要求「记住/保存/沉淀/整理进 vault」、"
    "或对话已产生经核实的长期知识（研究结论、行业动态）时使用 task(knowledge_keeper, …)。"
    "只新增 /vault/Inbox/ 笔记，带 wikilink；不用于临时问答、未核实内容、纯检索。"
)


def build_knowledge_keeper(deny_middleware=None, project_root=None, vault_path=None):
    """构造 knowledge_keeper 子代理（SubAgent dict 形态）。

    工具继承主代理后端默认的 write_file（可写 /vault/Inbox/），无需显式声明。
    deny_middleware: 权限 deny 拦截 middleware（命中 deny 的工具不执行）。
    """
    middlewares: list = [VaultWriteGuardMiddleware(actor="knowledge_keeper")]
    if project_root is not None and vault_path is not None:
        middlewares.append(InboxSnapshotMiddleware(project_root, vault_path))
    if deny_middleware is not None:
        middlewares.insert(0, deny_middleware)
    spec: dict[str, object] = {
        "name": "knowledge_keeper",
        "description": KNOWLEDGE_KEEPER_DESCRIPTION,
        "system_prompt": KNOWLEDGE_KEEPER_PROMPT,
        "middleware": middlewares,
    }
    return spec  # type: ignore[return-value]
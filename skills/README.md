# skills/

已安装 skill 目录（**安装包默认层**）。运行时还会扫描：

| 层 | 磁盘路径 | 虚拟路径 |
|---|---|---|
| 安装包默认 | `{install_root}/skills/` | `/builtin-skills/` |
| 用户全局 | `~/.javis/skills/`（`JARVIS_HOME` 可改） | `/skills/` |
| 项目 | `{project_root}/skills/`（`javis.json` 的 `skills` 段） | `/workspace/skills/` |

同名 skill：**项目 > 用户全局 > 安装默认**。不拷贝，启动时合并扫描。

deepagents 扫描各层子目录里的 `SKILL.md`。
本文件是 **skill 编写指南**（基于 Claude Code 的 skill-creator 方法论，结合本项目约定本地化）。

---

## Skill 是什么

Skill = 自包含的「流程包」：给 JARVIS 提供特定领域的**工作流、专业判断、可复用资源**。
相当于给主代理写的一份「上岗指南」——把模型不天然具备的过程性知识固化下来。

### 一个 Skill 能提供什么

1. **专业工作流** — 多步骤流程（如「整理 vault 笔记」「生成周报」）
2. **工具/格式集成** — 特定文件格式、API 的操作规范
3. **领域知识** — 业务规则、schema、约定
4. **打包资源** — scripts（确定性脚本）、references（按需加载文档）、examples（可复制示例）

### Skill 与 子代理 的边界（重要，先判这个）

| 维度 | Skill | 子代理（researcher / knowledge_keeper） |
|------|-------|-----------------------------------------|
| 谁执行 | **主代理自己**读指令后执行 | 委派独立代理（有独立 prompt + tools） |
| 依赖 | 主代理现有工具 | 子代理独有工具/上下文 |
| 触发 | 主代理看 description 判断 | 主代理 `task(subagent_type=...)` 委派 |

**判断规则：**
- 已有子代理覆盖的能力 → **不做 skill**（redundant）。例如：网络调研已被 researcher 完整覆盖（Tavily 三档搜索 + 流程 + 选档策略），不要再写 research skill。
- Skill 适合：主代理**直接用现有工具**执行的流程规范（文件整理、配置、写作风格）。
- 违背「子代理生成、母代理归档」这类跨层拆分 → **克制**，保持单一归属，宁可不建。

---

## SKILL.md 格式

每个 skill 一个子目录：`skills/<skill-name>/SKILL.md`

```
skills/<skill-name>/
├── SKILL.md            # 必需：YAML frontmatter + markdown 正文
├── scripts/            # 可选：可执行代码（确定性任务）
├── references/         # 可选：按需加载的文档（大文件放这）
└── examples/           # 可选：可复制的工作示例
```

### SKILL.md 必需字段

```yaml
---
name: my-skill
description: This skill should be used when the user asks to "具体触发短语1", "触发短语2"。提供……的能力。
---
```

- `name`：小写字母 + 连字符（≤64 字符）。目录名与 name 一致。
- `description`：**第三人称**（"This skill should be used when..."）+ **具体触发短语**（用户会说的话）。描述质量直接决定主代理会不会用这个 skill。

### 正文写作规范

- **祈使句**（动词开头），不用第二人称：
  - ✅ "To accomplish X, do Y" / "Parse the frontmatter using grep"
  - ❌ "You should do X" / "Claude should extract fields"
- **保持精简**：正文 1,500–2,000 词理想（<5k 上限），细节移 references/。
- **引用资源**：正文末尾明确列出 references/scripts/examples 文件名，否则主代理不知道它们存在。
- 大文件（>10k 词）在正文给出 grep 搜索模式。

---

## 渐进式披露（三级加载）

| 级别 | 内容 | 何时加载 |
|------|------|----------|
| L1 | name + description（frontmatter） | 常驻上下文（~100 词） |
| L2 | SKILL.md 正文 | skill 触发时（<5k 词） |
| L3 | scripts / references / examples | 主代理判断需要时（scripts 可执行不读入上下文） |

**由此得出设计原则：**
- description 写得好不好，决定 skill 会不会被用。
- SKILL.md 只留核心流程，详细内容全部下沉到 references/。
- 信息只放一处（SKILL.md 或 references/），不重复。

---

## Skill 创建流程（6 步）

### Step 1：理解场景（用具体例子）
先问清具体用例：
- "你会怎么用这个 skill？给几个例子"
- "用户说什么话会触发它？"
避免一次问太多问题，从最关键的开始。

### Step 2：规划可复用内容
对每个用例分析：
1. 从零执行这个任务需要什么？
2. 重复执行时哪些 scripts / references / assets 会有帮助？
例：PDF 旋转 → 每次重写同样代码 → 建 `scripts/rotate_pdf.py`。

### Step 3：创建目录结构
```bash
mkdir -p skills/<skill-name>/{references,examples,scripts}
touch skills/<skill-name>/SKILL.md
```
只建实际需要的子目录，不留空壳。

### Step 4：编辑 SKILL.md
- 先写可复用资源（scripts/references/examples），再写 SKILL.md。
- description 用第三人称 + 触发短语。
- 正文用祈使句，回答三个问题：
  1. 这个 skill 的目的（几句话）
  2. 何时用（进 frontmatter description）
  3. 怎么用（引用所有可复用资源）

### Step 5：校验
对照下方「校验清单」。可让主代理自检："Review this skill and check if it follows best practices"。

### Step 6：迭代
真实任务上使用 → 记录卡点 → 更新 SKILL.md / 资源 → 再测。

---

## 校验清单

**结构**
- [ ] `skills/<skill-name>/SKILL.md` 存在，frontmatter 有效
- [ ] frontmatter 含 `name` 和 `description`
- [ ] 正文实质存在
- [ ] 正文引用的文件真实存在

**描述质量**
- [ ] 第三人称（"This skill should be used when..."）
- [ ] 含用户会说的具体触发短语
- [ ] 列出具体场景，不模糊不泛化

**内容质量**
- [ ] 正文用祈使句，无第二人称
- [ ] 正文精简（1,500–2,000 词理想，<5k 上限）
- [ ] 细节已移 references/，无重复

**归属判断**
- [ ] 未被已有子代理覆盖（researcher/knowledge_keeper 的能力不做 skill）
- [ ] 主代理能用现有工具执行，不需要独立子代理

---

## 常见错误

| 错误 | 反例 | 正例 |
|------|------|------|
| 触发描述模糊 | `Provides guidance for hooks.` | `This skill should be used when the user asks to "create a hook", "add a PreToolUse hook", ...` |
| 全塞一个文件 | SKILL.md 8k 词 | SKILL.md 1.8k 词 + references/patterns.md 2.5k 词 |
| 第二人称 | `You should validate the input.` | `Validate the input before processing.` |
| 资源未引用 | references/ 存在但正文没提 | 正文 `## 参考文件` 列 `references/patterns.md` |
| 与子代理重复 | research skill（researcher 已覆盖） | 不建，或调整归属 |

---

## 模板（新建 skill 时复制）

```markdown
---
name: <skill-name>
description: This skill should be used when the user asks to "触发短语1", "触发短语2", "触发短语3"。提供 <能力> 的规范。
---

# <Skill 名称>

## 目的
<几句话说明这个 skill 做什么>

## 使用时机
<何时用，何时不用（含与子代理的边界）>

## 步骤
1. <第一步>
2. <第二步>

## 参考文件
- `references/<file>.md` — <用途>
- `scripts/<script>` — <用途>
```

---

## 参考

- Claude Code skill-creator 方法论：anthropics/claude-code `plugins/plugin-dev/skills/skill-development/`
- 本项目执行机制：deepagents `SkillsMiddleware`（frontmatter 索引 + 渐进式披露），`src/agent.py` 的 `build_agent(skills=...)` 注入
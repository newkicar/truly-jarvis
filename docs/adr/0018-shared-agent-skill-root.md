# ADR-0018: 共享 agent skill 根 ~/.agents/skills/（shared agent skill root）

**状态:** 已接受（2026-11-26）

## 背景

jarvis 的 skill 发现是两层模型（对齐 opencode）：用户全局
`~/.jarvis/skills`（`/skills/`）+ 项目层（`Config.skills` → 虚拟路径，
如 `.jarvis/skills` → `/workspace/.jarvis/skills/`，ADR-0016）。

用户同时使用其他 agent 工具（codex 等），跨工具共享 skill 放在用户主目录
的 `~/.agents/skills/`（codex 个人 skill 根；本机实证存在多个真实
skill）。jarvis 读不到该层：同一批 skill 要在 `~/.jarvis/skills` 再拷贝
一份维护，两份内容漂移。

Issue #12 需求：把 `~/.agents/skills/` 作为**共享 skill 层**挂进 jarvis
的 skill 发现——最低优先级、只读挂载、可开关关闭。

## 决策

1. **共享层挂载**（src/skill_paths.py，工单 01）：
   - `discover_skill_layers()` 升为三层：共享 SHARED（最低）→ 用户全局
     USER → 项目 PROJECT（最高）；同名 skill 后层覆盖前层语义不变。
   - `SHARED_SKILLS_VPATH = "/shared-skills/"`——独立虚拟前缀，避开
     用户层 `/skills/` 与 profile 层 `/agent-skills/`。
   - 挂载条件：`config.share_agent_skills=True` **且**
     `agents_home()/"skills"` 是目录（目录不存在 = 不挂载，零影响）。
   - **只读挂载**：仅 `is_dir()` 决定挂不挂，绝不 mkdir / 迁移 /
     seeding；`ensure_user_home()` 不触碰 `.agents`（无目录创建、无
     内容搬运，与 jarvis 用户层 seed 语义彻底分开）。
2. **路径解析**（src/project_paths.py）：`agents_home()` =
   `AGENTS_HOME` 环境变量（strip 后 expanduser + resolve，可覆盖）或
   `Path.home()/".agents"`；对齐 `JARVIS_HOME` → `user_home()` 的覆盖
   模式。
3. **开关**（src/config.py）：jarvis.json 的 `share_agent_skills`，
   GLOBAL_DEFAULTS 缺省 `True`；非布尔值 → `logging.warning` 回落 `True`
   （不误判为关）。`skill_virtual_sources` / `skill_backend_routes` 按
   layers 统一遍历，零改动。
4. **测试隔离**：本机存在真实 `~/.agents/skills`（多个真实 skill），
   新增/既有测试一律 `AGENTS_HOME` 指到不存在的隔离目录（目录不存在
   则不挂载）；`tests/test_skill_discovery.py` 补 5 处
   `monkeypatch.setenv("AGENTS_HOME", ...)`（该文件此前只隔离
   JARVIS_HOME，真实 .agents 层会污染断言）。

## 基准

- **codex 个人 skill 根**：`~/.agents/skills`（本机实证；r1 skill 根
  即该目录）——共享层路径直接对齐，不发明新位置。
- **opencode 两层模型**（ADR-0016 基准）：用户全局 + 项目两层已对齐；
  共享层是叠加在用户层之下的**跨工具用户层**，不改既有两层语义。
- **deepagents**：skill 发现 = FilesystemBackend 虚拟挂载
  （`skills=` 路径列表 → 虚拟前缀路由），对目录位置无意见，上游零
  改动。

## 残余风险

- **同名覆盖方向**：共享层 skill 与用户/项目层同名时高层胜出——用户
  只改共享层副本时改动被高层同名 skill 遮蔽；预期语义（最低优先级
  定义如此），非 bug。
- **跨工具格式漂移**：`.agents/skills` 是多工具共享约定；jarvis
  发现只读 SKILL.md frontmatter 的 name/description（宽容解析），
  其他工具的额外 frontmatter 字段被忽略，不影响挂载。
- **AGENTS_HOME 误配**：指向不存在路径 → 共享层自然不挂（is_dir()
  假）；若误配到与 JARVIS_HOME 相同的物理 skills 目录，同一批
  SKILL.md 会以两个虚拟前缀出现，目录中同名条目由用户层胜出；低
  概率误配，不做特判。

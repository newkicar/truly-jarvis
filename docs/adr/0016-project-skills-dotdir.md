# ADR-0016: 项目 skills 收进 .jarvis/skills/（project skills under dotdir）

**状态:** 已接受（2026-11-25）

## 背景

jarvis 项目初始化时会在项目根创建顶层 skills/ 目录作为项目级技能层
（jarvis.json 的 skills 条目 "skills" / "skills/x"）。当用户的项目本身
是 agent 工程时，项目里通常也有一个 skills/ 目录（用户自己的 agent 技能）
——两个同名顶层目录在同一项目根下直接冲突：jarvis 模板会撞上用户既有
skills/，用户的 agent 工具链也会把 jarvis 的项目技能误认为自己的技能。

预期语义（用户确认）：jarvis 在项目里创建的目录全部收进
{project_root}/.jarvis/ dotdir（与 checkpoints/、sessions.json 先例一致），
项目技能层改为 .jarvis/skills/；既有顶层 skills/ 由启动迁移器**整目录
move**（非保守逐文件合并）进 .jarvis/skills/，同名冲突时目标
（.jarvis/ 侧）优先、源侧同名内容永久删除、无备份。

## 决策

1. **布局与模板**（src/project_init.py，工单 01）：
   JARVIS_JSON_TEMPLATE 的 skills 条目 = [".jarvis/skills/"]；
   init_project 骨架循环创建 .jarvis/skills/（不再创建顶层 skills/）；
   auto_init_project（main.py / gui_main.py 首次运行兜底）同样只建
   .jarvis/skills/。--init CLI 与 GUI 自动初始化共用同一模板与循环，
   GUI 层零改动。
2. **启动迁移**（src/project_paths.py migrate_project_dotdir skills 段，工单 02）：
   - 顶层 skills/ 是目录且 .jarvis/skills/ 不存在 → 整目录 rename（move）；
   - 目标已存在 → 逐条目处置：**目标优先**——.jarvis/skills/ 下同名已存在
     则源侧同名目录 shutil.rmtree / 同名文件 unlink（永久删除、无备份，
     用户约定）；不冲突条目 rename 进目标；源目录清空后 rmdir，
     有 rename 失败残留则保留；
   - .jarvis/skills 是文件而非目录 → warn note，源保留（不猜意图）；
   - 项目根 == 安装根（开发模式）整段跳过（root != install_root().resolve()
     双侧 resolve 比较）；
   - jarvis.json skills 条目以 "skills" / "skills/x" 开头者改写为
     .jarvis/skills 前缀；改写独立于目录 move（JSON 缺失/损坏不影响目录
     move），非字符串条目原样保留，仅实际改写时回写文件；
   - **幂等**：迁移后顶层无 skills/、JSON 无旧前缀 → 二次运行零 note、零 IO。
   返回人类可读 note 列表（main.py / gui_main.py 启动时打印、不阻塞）。
3. **读路径零改动**（src/skill_paths.py）：skill 发现 = Config.skills 每项
   解析为绝对路径 → 相对项目根得虚拟路径（.jarvis/skills →
   /workspace/.jarvis/skills/）→ virtual_mode=True FilesystemBackend 路由。
   模板与迁移器写对路径后，发现、路由、seed 自动跟上；
   deepagents 原生 skill 发现零改动。

## 基准

- **仓库自身 .jarvis/ dotdir 先例**：checkpoints/、sessions.json 已收进
  {project_root}/.jarvis/（project_paths.py「0.1.x 遗留布局…统一进
  .jarvis/」注释）；skills 是第三个成员，语义一致：项目状态进 dotdir，
  顶层命名空间留给用户项目。
- **VS Code 项目隐藏状态惯例**：编辑器把项目级状态放 dot 目录
  （.vscode/ 等），不占用户可见的顶层命名空间。
- **deepagents**：N/A——skill 发现是纯 FilesystemBackend 虚拟挂载
  （skills= 路径列表 → 虚拟前缀路由），对目录位置无意见，上游无先例。
- **GitHub 调研**：无框架层 issue 可引；agent 项目自带 skills/ 的冲突
  场景属项目布局惯例，按 dotdir 惯例定案。

## 残余风险

- **同名冲突删源无备份**：.jarvis/skills/ 侧同名内容胜出，源侧同名目录/
  文件永久删除（用户已确认语义，不接受保守合并）；触发面 = 用户手工把
  旧版 jarvis 项目技能放回顶层 skills/ 且与 .jarvis/skills/ 同名不同内容。
- **跳过规则依赖 .resolve() 双侧比较**：开发模式（项目根 == 安装根）整段
  跳过；符号链接归一失败时可能误跳/误迁移，影响面 = 开发模式用户自己的
  仓库，可修正后重跑（幂等）。
- **JSON 改写只动 skills 键**：仅改写 "skills" / "skills/x" 前缀字符串条目
  （casefold 归一、去首尾 /）；其他键与非字符串条目不碰；JSON 损坏时
  静默跳过改写（目录 move 不受影响、不产生 note）。

# 02 — 首次运行自动生成项目配置

**What to build:** `jarvis` 命令检测到 cwd 无 `jarvis.json` 时，自动生成项目级默认配置 + skills/ 目录（对标 opencode 开箱即用体验）。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** 01-pyproject-toml

## 首次运行流程

```
用户 cd D:\my-project && jarvis
    ↓
检测 cwd 无 jarvis.json → 生成项目级默认配置
    ↓
检测 ~/.jarvis/ 不存在 → 生成全局默认配置 + skills/
    ↓
启动 TUI
```

## 项目级自动生成内容

```bash
D:\my-project\
├── jarvis.json        ← 默认配置（模型、权限、项目名=文件夹名）
└── skills/            ← 空目录（用户自定义 skill 放这里）
```

## 全局自动生成内容

```bash
~/.jarvis/
├── jarvis.json        ← 全局默认配置
├── skills/            ← 内置 skill（从 builtin-skills 复制）
└── JARVIS.md          ← 默认全局指令（可选）
```

## 实现要点

- `discover_project_root()` 返回 cwd（无 jarvis.json 时）→ main.py 检测并自动生成
- 项目名默认取 cwd 文件夹名
- 生成前不提示用户（静默生成，对标 opencode）
- `--init` 保留为高级选项（可指定目录、强制覆盖）

## 验收
- [ ] 空目录运行 `jarvis` → 自动生成 jarvis.json + skills/
- [ ] 生成的 jarvis.json 包含合理的默认值
- [ ] ~/.jarvis/ 首次运行自动生成
- [ ] 二次运行不重复生成
- [ ] --init 仍可手动指定目录

# jarvis 产品化打包 Spec

日期：2026-08-26
状态：planning

## 背景

将 JARVIS 从「开发项目」变成「可安装的 TUI 产品」。同事安装后，在任意文件夹输入 `jarvis` 即可启动，cwd 成为项目根。

## 分发方式

- 目标用户：自己 + 团队内部（不需要公开 PyPI）
- 安装方式：`uv tool install` / `pipx install` / `pip install`（wheel）
- 不做 PyInstaller 单文件 exe（暂时）

## 配置结构（两层）

```
~/.jarvis/                       ← 全局（安装后首次运行自动创建）
├── jarvis.json                  ← 全局默认配置
└── skills/                      ← 全局 skill（跨项目共享）

<project>/                       ← 同事在某个文件夹启动 cmd
├── jarvis.json                  ← 项目专属配置（覆盖全局）
└── skills/                      ← 项目专属 skill
```

## 首次运行体验

1. 用户 `cd D:\my-project && jarvis`
2. 检测到 cwd 无 `jarvis.json` → 自动生成项目级默认配置 + skills/
3. 检测到 `~/.jarvis/` 不存在 → 自动生成全局默认配置 + skills/
4. 启动 TUI

## 需要的文件

| 文件 | 作用 |
|------|------|
| `pyproject.toml` | 包元数据 + 依赖 + console_scripts 入口 |
| `src/__main__.py` | `python -m jarvis` 入口 |
| `src/main.py` | 首次运行检测 + 自动初始化 |

## 与现有代码的关系

- `discover_project_root()` 已实现（向上找 jarvis.json）→ 保持
- `--init` 已实现（手动初始化）→ 保持，作为高级选项
- `install_root()` 已实现（找 builtin-skills）→ 保持
- 新增：首次运行自动生成（对标 opencode 开箱即用）

## 验收

- [ ] `pip install -e .` 后 PATH 里有 `jarvis` 命令
- [ ] `python -m jarvis` 也能启动
- [ ] 首次运行自动生成 `~/.jarvis/` + 项目级 `jarvis.json` + `skills/`
- [ ] 二次运行直接启动（不重复生成）
- [ ] 全量测试通过

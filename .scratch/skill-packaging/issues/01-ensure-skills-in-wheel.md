# 01 — 确保 skills/ 目录随包安装时打进 wheel

**What to build:**
确认（或修复）`pyproject.toml` 的 `package-data`，确保非 editable 安装（`pip install .`）时 `skills/` 目录及其子目录被正确打进 wheel，使 `install_root()/skills` 在非 editable 环境下可用。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** user-skill-seeding/01（seed 逻辑依赖 `install_root()/skills` 存在）

## 背景

- 方案 A（user-skill-seeding/01）把 `install_root()/skills` 作为 seed 源，首次运行时拷贝到 `~/.jarvis/skills`。
- 当前 `pyproject.toml` 配置：

```toml
[tool.setuptools.packages.find]
include = ["src*", "jarvis*"]

[tool.setuptools.package-data]
src = ["*.md"]
"skills" = ["**/*"]
```

- **问题**：`skills/` 没有 `__init__.py`（不是 Python 包），`packages.find` 的 `include = ["src*", "jarvis*"]` 不含 `skills`。`package-data` 的 key 必须引用已安装的包——`skills` 不是包，该条目**大概率被忽略**，非 editable 安装不会包含 `skills/` 内容。
- editable 安装（`pip install -e .`）时 `install_root()` = repo 根，`skills/` 直接可见，所以开发阶段没问题，但 end user 真实安装时 seed 源为空。

## 目标

### 1. 验证问题

```bash
pip install . --target /tmp/jarvis-test
ls /tmp/jarvis-test/jarvis/skills 2>/dev/null || echo "skills/ 未打包"
```

或 `python -m build` 后解压 `.whl` 检查是否包含 `skills/` 目录。

### 2. 修复打包配置

方案 A（推荐，最小改动）：在 `skills/` 下加 `__init__.py` 使其成为 Python 包：

```toml
# pyproject.toml
[tool.setuptools.packages.find]
include = ["src*", "jarvis*", "skills*"]
```

方案 B（不加 `__init__.py`）：改用 `data-files` 或 `[tool.setuptools.package-data]` 配合 `packages.find` 的 `include` 补丁，但这种方式对 wheel 分发不可靠。

### 3. 验证修复

```bash
pip install . --target /tmp/jarvis-test2
ls /tmp/jarvis-test2/skills/          # 方案 A
# 或
ls /tmp/jarvis-test2/jarvis/skills/   # 方案 A（取决于包层级）
```

确认 14 个 skill 目录均存在。

### 4. 更新 README / 文档

若安装方式有变化（如需 `pip install .` 而非 `pip install -e .`），同步更新 `README.md` 快速开始部分。

## 验证

- `python -m build && ls dist/*.whl` 后解压确认 `skills/` 在 wheel 内
- `pip install . --target /tmp/test && ls /tmp/test/skills/` 确认存在
- `pytest tests/ -q` 全量通过

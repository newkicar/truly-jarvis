# Python 规则执行者台账

| 规则 ID | 约束与执行者 | 验收方式 |
|---|---|---|
| `py-ruff-project-config` | 项目本地检查器运行固定版本 Ruff，并加载项目 Ruff 配置。 | `python .engineering-kit/python-style`。 |
| `py-import-order` | 检查器强制启用 Ruff `I`，约束导入分组与排序。 | 在 Python 文件中打乱 import 顺序，运行检查器应失败。 |
| `py-function-complexity` | 检查器强制启用 Ruff `C90`，函数圈复杂度上限为 10。 | 构造复杂度超过 10 的函数，运行检查器应报告 `C901`。 |

项目 Ruff 配置仍控制其他规则；`select` 和 `ignore` 不会关闭上述 kit 门槛。确需例外时，在具体导入或函数上使用 `# noqa: I001` 或 `# noqa: C901`，说明原因并在 [决策日志](DECISION_LOG.tsv) 记录。

架构边界取决于项目的真实模块和层次，安装器不会猜测目录或框架。项目确认边界后，为每条约束增加独立 ID、执行者和可复现的验收命令；可用 Import Linter 或明确的 Ruff 导入规则实现。重复错误的历史事例和例外写入 [决策日志](DECISION_LOG.tsv)。

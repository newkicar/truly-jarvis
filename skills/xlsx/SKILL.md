---
name: xlsx
description: "Use this skill any time a spreadsheet file is the primary input or output — .xlsx, .xlsm, .csv, .tsv. Triggers: user references a spreadsheet file by name/path, wants to open/read/edit/create/fix a spreadsheet, add columns, compute formulas, format, chart, clean messy data, or convert between tabular formats."
---

# Excel 处理指南

## 工具选择

| 任务 | 工具 |
|------|------|
| 创建/编辑（含公式/格式） | `openpyxl` |
| 批量数据读写 | `pandas`（`read_excel`, `to_excel`） |
| 快速查看内容 | `execute` 运行 Python 读取 |

用 `execute` 工具运行 Python 脚本，直接 `import openpyxl` / `import pandas`，无需额外安装。

## 核心要求

- **用公式，不要硬编码结果**：写 `sheet['B10'] = '=SUM(B2:B9)'`，不要写 Python 计算出的值
- **零公式错误**：写完后用 `data_only=True` 验证结果
- **专业字体**：默认 Arial 或宋体，除非用户指定
- **文档假设**：硬编码数字旁写注释说明来源

## openpyxl 注意事项

- **读取模型需要两次加载**：`data_only=True` 得缓存值（无公式），默认模式得公式字符串（无值）
- **`data_only=True` 保存会丢失公式**：不要在 `data_only` 模式下保存
- **合并单元格**：只写左上角锚点
- **`.xlsm` 保留宏**：`load_workbook(file, keep_vba=True)`
- **含空格的 sheet 名**：跨表引用需加引号 `='Sheet 1'!$B$5`

## 财务模型配色

- 蓝色文字：硬编码输入
- 黑色：公式
- 绿色：跨 sheet 引用
- 黄色填充：关键假设/待填单元格

## 数字格式

- 货币：`$#,##0`
- 百分比：存为小数（`0.15` 显示为 `15.0%`）
- 负数用括号：`($1,234)`
- 年份存为文本：`"2024"`

## 公式兼容性

- ✅ 用 Excel 2007 时代函数：`SUMIFS`, `INDEX`, `MATCH`, `IFERROR`, `SUMPRODUCT`
- ⚠️ 2007+ 函数需加前缀：`_xlfn.TEXTJOIN`, `_xlfn.IFS`
- ❌ 不要用：`XLOOKUP`, `XMATCH`, `SORT`, `FILTER`, `UNIQUE`

## 快速验证

```python
import openpyxl
wb = openpyxl.load_workbook('output.xlsx', data_only=True)
for sheet in wb.sheetnames:
    ws = wb[sheet]
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None and cell.data_type == 'f':
                print(f'⚠️ {cell.coordinate}: 公式无缓存值')
```

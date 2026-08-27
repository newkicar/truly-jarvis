---
name: docx
description: "Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx). Triggers: mention of 'Word doc', '.docx', requests for reports/memos/letters/templates as Word files, extracting content from .docx, find-and-replace, or converting content into polished Word documents."
---

# Word 文档处理指南

## 工具选择

| 任务 | 工具 |
|------|------|
| 创建新文档 | `python-docx` |
| 读取内容 | `python-docx` 或 `execute` 运行 Python |
| 编辑已有文档 | `python-docx`（追加/修改段落） |

用 `execute` 工具运行 Python 脚本，直接 `from docx import Document`。

## python-docx 核心操作

### 创建文档

```python
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
doc.add_heading('标题', 0)
doc.add_paragraph('正文内容')
doc.add_table(rows=3, cols=3)
doc.save('output.docx')
```

### 读取内容

```python
from docx import Document
doc = Document('input.docx')
for para in doc.paragraphs:
    print(para.text)
for table in doc.tables:
    for row in table.rows:
        print([cell.text for cell in row.cells])
```

### 格式化

```python
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

para = doc.add_paragraph()
run = para.add_run('加粗文本')
run.bold = True
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0, 0, 0)
para.alignment = WD_ALIGN_PARAGRAPH.CENTER
```

## 注意事项

- **表格宽度**：用 `Inches()` 设置，确保在页面内
- **图片插入**：`doc.add_picture('image.png', width=Inches(4))`
- **页眉页脚**：通过 `section.header` / `section.footer` 访问
- **目录**：需要手动更新字段（python-docx 不支持自动目录刷新）
- **`.doc` 旧格式**：需先转为 `.docx`（用 LibreOffice 或在线工具）

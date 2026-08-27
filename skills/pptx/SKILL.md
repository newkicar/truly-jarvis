---
name: pptx
description: "Use this skill any time a .pptx or .potx file is involved — as input, output, or both. Triggers: creating slide decks/pitch decks/presentations, reading/parsing/extracting text from .pptx, editing/modifying existing presentations, combining/splitting slide files, working with templates/layouts/speaker notes. Also triggers on 'deck', 'slides', 'presentation'."
---

# PowerPoint 处理指南

## 工具选择

| 任务 | 工具 |
|------|------|
| 创建新演示文稿 | `python-pptx` |
| 读取内容 | `python-pptx` |
| 编辑已有幻灯片 | `python-pptx`（修改文本/图片/布局） |

用 `execute` 工具运行 Python 脚本，直接 `from pptx import Presentation`。

## python-pptx 核心操作

### 创建演示文稿

```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()
slide_layout = prs.slide_layouts[0]  # 标题布局
slide = prs.slides.add_slide(slide_layout)
title = slide.shapes.title
title.text = "幻灯片标题"
prs.save('output.pptx')
```

### 读取内容

```python
from pptx import Presentation
prs = Presentation('input.pptx')
for i, slide in enumerate(prs.slides):
    print(f'--- Slide {i+1} ---')
    for shape in slide.shapes:
        if hasattr(shape, 'text'):
            print(shape.text)
```

### 添加文本框

```python
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

left = Inches(1)
top = Inches(1)
width = Inches(8)
height = Inches(1)
textbox = slide.shapes.add_textbox(left, top, width, height)
tf = textbox.text_frame
tf.text = "自定义文本"
tf.paragraphs[0].alignment = PP_ALIGN.CENTER
```

### 添加图片

```python
slide.shapes.add_picture('image.png', Inches(1), Inches(2), width=Inches(4))
```

## 注意事项

- **布局索引**：`prs.slide_layouts[0]` 是标题，`[1]` 是标题+内容，`[5]` 是空白
- **宽屏比例**：默认 16:9（`Inches(10, 5.625)`）
- **表格**：`slide.shapes.add_table(rows, cols, left, top, width, height)`
- **图表**：`python-pptx` 支持基础图表，复杂图表建议用 `matplotlib` 生成图片后插入
- **模板**：`prs = Presentation('template.pptx')` 可基于模板创建
- **Speaker notes**：`slide.notes_slide.notes_text_frame.text = "备注内容"`

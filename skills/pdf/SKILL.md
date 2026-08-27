---
name: pdf
description: "Use this skill whenever the user wants to do anything with PDF files — reading/extracting text/tables, combining/splitting, rotating pages, adding watermarks, creating new PDFs, filling forms, encrypting/decrypting, extracting images, or OCR on scanned PDFs."
---

# PDF 处理指南

## 工具选择

| 任务 | 工具 |
|------|------|
| 读取文本 | `pypdf` 或 `pdfplumber` |
| 提取表格 | `pdfplumber` |
| 创建 PDF | `reportlab` |
| 合并/拆分 | `pypdf` |
| OCR 扫描件 | `pytesseract` + `pdf2image` |

用 `execute` 工具运行 Python 脚本，所有库均可直接 import。

## 读取文本

```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
for page in reader.pages:
    print(page.extract_text())
```

## 提取表格

```python
import pdfplumber
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            df = pd.DataFrame(table[1:], columns=table[0])
            print(df)
```

## 合并 PDF

```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as f:
    writer.write(f)
```

## 创建 PDF

```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf", pagesize=letter)
c.drawString(100, 700, "Hello World!")
c.save()
```

## 拆分 PDF

```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as f:
        writer.write(f)
```

## OCR 扫描件

```python
# 需要: pip install pytesseract pdf2image
import pytesseract
from pdf2image import convert_from_path

images = convert_from_path("scanned.pdf")
for i, image in enumerate(images):
    text = pytesseract.image_to_string(image)
    print(f"Page {i+1}: {text}")
```

## 注意事项

- **`pypdf` vs `pdfplumber`**：pypdf 读文本快，pdfplumber 提取表格更准
- **扫描件 PDF**：`extract_text()` 返回空，需 OCR
- **加密 PDF**：`PdfReader("file.pdf", password="xxx")`
- **`reportlab` 下标/上标**：用 `<sub>` / `<super>` XML 标签，不用 Unicode 字符

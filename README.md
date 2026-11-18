# invoice2data-plus

> **增强型 PDF 发票数据提取工具与 Python 库**  
> *An enhanced Python parser and CLI to extract structured data from PDF invoices.*

---

## 中文文档

### 简介

`invoice2data-plus` 是基于开源发票解析库 `invoice2data` 的增强二次开发版本（路线 A）。它利用预定义的 YAML/JSON 模板及可插拔的多后端级联提取技术，将原本非结构化的 PDF、图片及文本发票精准解析为结构化的业务数据（JSON、CSV 或 XML），广泛适用于电商对账、财税自动化与 ERP 录入场景。

---

### 功能与改进点（对应 CHANGES.md）

本项目在原项目基础上完成了 4 项核心实质增强及 1 项测试套件兼容性加固（共 5 项）：

1. **模板匹配可诊断与透明度提升（`--explain` 深度诊断与 API 支持）**
   - 在 `InvoiceTemplate` 中引入 `diagnose_match()` 与 `diagnose_fields()`，结构化分析模板关键词匹配/缺失、排除词触发以及每项字段的提取结果。
   - 增强 CLI 的 `--explain` 选项：当完全未命中时，诊断并展示最接近的候选模板、缺失关键词列表及排除词触发情况；当必填字段缺失时，明确指出具体模板文件及未匹配字段名。
   - 新增 `explain_matching()` 顶层 Python API，方便开发者在自动化流水线中诊断模板命中状态。

2. **数字与日期解析加固（负数、货币符号与多语言兼容）**
   - 财务会计负数识别：原生支持带括号的会计负数（如 `(1,234.56)` ➔ `-1234.56`）与尾随负号（如 `120.00-` ➔ `-120.0`）。
   - 货币符号与留白剔除：自动识别并剥离各类货币符号（`$`、`€`、`£`、`¥`、`₹`）及 3 字母国际代码（USD、EUR、GBP 等），规范化 Unicode 财务空格（如 `\u00a0`、`\u202f` 等）。
   - 多语言日期清洗加固：优化主流语言（en、de、fr、es、zh）日期前缀、中括号与标点的清洗，提升非标准排版下的解析准确率。

3. **输入后端统一探测、友好依赖缺失提示与自定义级联回退**
   - 新增 `probe_backends()` 与 `get_backend_status()`，一键探测所有已注册后端可用性、环境依赖类型，并提供针对 Ubuntu/Debian（`apt`）、macOS（`brew`）和 Python（`pip`）的友好安装指引。
   - 在系统缺少 `pdftotext` 或 `tesseract` 二进制工具时，抛出包含明确系统安装命令的错误指引，取代晦涩的底层错误。
   - 支持环境变量 `INVOICE2DATA_INPUT_READERS`（如 `pdfium,pdftotext,pdfminer`）与 `extract_data(readers=...)` 参数，允许用户在不同生产环境自定义回退优先级。
   - 新增详细后端选型与对比指南：`docs/backend-comparison.md`。

4. **输出类型稳定与标准化校验（Decimal 金额、ISO 8601 日期与 JSON Schema 校验）**
   - 在 `schema.py` 中发布规范化的 `INVOICE_JSON_SCHEMA`（兼容 JSON Schema Draft 2020-12）。
   - 实现 `standardize_output()`：支持将浮点金额统一转换为财务级高精度 `Decimal`，将日期/时间对象统一转换为 ISO 8601 字符串（`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS`），并对 `lines` 与 `tax_lines` 递归标准化。
   - 新增 `validate_invoice_schema()` 校验函数，支持可选严格模式。
   - CLI 与 Python API 均提供 `--standardize-types`、`--use-decimal` 与 `--validate-schema` 开关，默认保持对旧版本的完全向后兼容。

5. **测试套件环境兼容性加固与全套回归测试**
   - 加固 `tests/test_gvision.py` 与 `tests/test_property.py`，使测试套件在缺少商业云 SDK 或特定环境下优雅跳过，全套 1263 个测试全部稳定通过。
   - 为上述所有增强功能编写了 4 个新测试文件共 52 项单元测试。

---

### 快速开始

#### 1. 安装

```bash
# 推荐克隆后可编辑安装：
cd invoice2data-plus
pip install -e .

# 安装可选依赖（如需要特定后端）：
pip install "pypdfium2>=4"      # 默认纯 Python 极速后端
pip install "dateparser>=1.2.0"  # 多语言本地化月份解析
```

#### 2. 命令行使用（CLI）

```bash
# 基础提取（输出格式为 CSV）
invoice2data invoice.pdf

# 指定输出为 JSON 并导出到文件
invoice2data --output-format json --output-name result.json invoice.pdf

# 启用深度诊断（查看模板命中、缺失关键词与字段解析明细）
invoice2data --explain invoice.pdf

# 启用金额 Decimal 化、日期 ISO 8601 化及 JSON Schema 校验
invoice2data --standardize-types --validate-schema invoice.pdf

# 自定义后端级联回退顺序（环境变量）
INVOICE2DATA_INPUT_READERS="pdfium,pdftotext,pdfminer" invoice2data invoice.pdf
```

#### 3. Python 库调用（API）

```python
from invoice2data import extract_data, explain_matching
from invoice2data.input import probe_backends

# 1. 基础提取
data = extract_data("invoice.pdf")
print(data)

# 2. 高精度金额与标准化日期输出
standard_data = extract_data(
    "invoice.pdf",
    standardize_types=True,
    validate_schema=True,
)
print(standard_data["amount"])  # Decimal('123.45')
print(standard_data["date"])    # '2024-05-18T00:00:00'

# 3. 模板诊断分析
report = explain_matching("invoice.pdf")
print("Matched:", report["matched"])
print("Reason:", report["reason"])

# 4. 后端环境探测
status = probe_backends()
print("pdfium available:", status["pdfium"]["available"])
```

---

### 来源与致谢

本项目基于 [invoice2data](https://github.com/invoice-x/invoice2data) 二次开发，原项目由 invoice-x 以 MIT 许可证开源。

---

### 许可证

沿用原许可证，采用 MIT 许可证开源。全文详见根目录 [LICENSE.md](LICENSE.md)。

---

## English Documentation

### Introduction

`invoice2data-plus` is an enhanced rework (Route A) of the popular open-source PDF invoice parsing library `invoice2data`. It extracts structured data (JSON, CSV, XML) from unstructured PDF, image, and text invoices using predefined YAML/JSON templates and a pluggable multi-backend text extraction cascade.

### Features & Key Enhancements

1. **Template Matching Diagnostics & Transparency (`--explain` & API)**
   - Added `diagnose_match()` and `diagnose_fields()` on `InvoiceTemplate` to inspect keyword matches, missing keywords, exclude keywords triggers, and field extraction status.
   - Enhanced CLI `--explain`: when no template matches, it displays the closest candidates, match percentages, missing keywords, and triggered exclusions; when required fields fail, it reports the exact template and missing field names.
   - Added top-level `explain_matching()` Python API for debugging in pipelines.

2. **Hardened Number and Date Parsing**
   - **Accounting Negatives**: Native support for parenthesized negative amounts (e.g., `(1,234.56)` ➔ `-1234.56`) and trailing minus signs (e.g., `120.00-` ➔ `-120.0`).
   - **Currency & Whitespace Stripping**: Cleans currency symbols (`$`, `€`, `£`, `¥`, `₹`) and common 3-letter codes (`USD`, `EUR`, `GBP`), normalizing Unicode whitespace (`\u00a0`, `\u202f`, etc.).
   - **Multilingual Date Cleaning**: Hardened date preprocessing for English, German, French, Spanish, and Chinese invoices.

3. **Unified Backend Probing & Configurable Cascades**
   - `probe_backends()` and `get_backend_status()` inspect all registered backends and supply OS-specific installation instructions (Ubuntu `apt`, macOS `brew`, `pip`).
   - Friendly actionable error messages when `pdftotext` or `tesseract` binaries are missing from PATH.
   - Support for `INVOICE2DATA_INPUT_READERS` environment variable and `extract_data(readers=...)` parameter.
   - Comprehensive guide at `docs/backend-comparison.md`.

4. **Output Standardization & JSON Schema Validation**
   - Formal `INVOICE_JSON_SCHEMA` specification (JSON Schema Draft 2020-12).
   - `standardize_output()` converts floating-point currency numbers to high-precision `Decimal` and dates to ISO 8601 strings, recursively through line items and tax lines.
   - Optional validation with `validate_invoice_schema()`.
   - Accessible via CLI flags `--standardize-types`, `--use-decimal`, `--validate-schema`.

5. **Test Suite Compatibility & Regression Coverage**
   - Clean skipping for optional cloud/GPU dependencies without failures.
   - 52 new tests across 4 test modules with 1,263 passing tests in the full suite.

### Quickstart

```bash
# Installation
pip install -e .

# CLI extraction with diagnostics
invoice2data --explain invoice.pdf

# CLI extraction with Decimal and ISO dates
invoice2data --standardize-types --validate-schema invoice.pdf
```

```python
from invoice2data import extract_data, explain_matching

# Extract with standardized Decimal amounts and ISO 8601 dates
result = extract_data("invoice.pdf", standardize_types=True, validate_schema=True)
print(result["amount"])  # Decimal('123.45')
```

### Sources and Acknowledgements

This project is a secondary development based on [invoice2data](https://github.com/invoice-x/invoice2data), originally developed by invoice-x and open-sourced under the MIT License.

### License

Licensed under the MIT License. See [LICENSE.md](LICENSE.md) for the full license text.

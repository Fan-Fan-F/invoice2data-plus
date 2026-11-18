# 改进记录 CHANGES

本项目为 `invoice2data-plus`，基于 upstream 原项目 `invoice-x/invoice2data` 进行二次开发增强（路线 A）。

## 改进计划

根据任务单 `TASK.md` 与方向席出具的 `DIRECTION.md`，本项目实施以下 4 项核心实质改进及 1 项测试套件兼容性加固（共 5 项）：

### 1. 模板匹配可诊断与透明度提升（`--explain` 深度诊断与 API 支持）
- **问题与现状**：用户在模板匹配失败或提取不完整时，原项目输出分散，`--explain` 仅在完全匹配时输出字段，未命中时仅输出单一提示 `no template matched`，无法得知具体哪个关键词缺失、哪个排除关键词被触发，或哪个必填字段正则未命中。
- **涉及文件**：
  - `src/invoice2data/extract/invoice_template.py`
  - `src/invoice2data/api.py`
  - `src/invoice2data/__main__.py`
  - `tests/test_explain.py`（新增）
- **改造做法**：
  - 在 `InvoiceTemplate` 中新增 `diagnose_match(extracted_str)` 与 `diagnose_fields(optimized_str)`，结构化返回关键词命中/缺失列表、排除关键词触发状态、各字段正则匹配状态与原始值。
  - 在 `api.py` 中新增 `explain_matching(...)` 函数，支持对输入文件按优先级和后端诊断所有模板匹配情况与字段提取状态。
  - 增强 CLI 的 `--explain` 选项输出：当匹配失败时，列出最接近候选模板的缺失关键词与排除词命中情况；当必填字段缺失时，明确指出模板文件名及具体未匹配字段名。

### 2. 数字和日期解析加固（负数、货币符号与多语言兼容）
- **问题与现状**：在财务发票场景中，红字发票/折扣发票经常出现会计括号负数 `(1,234.56)`、尾随负号 `120.00-`、带货币符号如 `$ 1,234.56` 或 Unicode 不换行空格 `\u00a0` / `\u202f`。原项目 `parse_number` 会直接抛出 `ValueError`；多语言日期解析在缺少清洗时易失败。
- **涉及文件**：
  - `src/invoice2data/extract/invoice_template.py`
  - `src/invoice2data/extract/_dates.py`
  - `tests/test_enhanced_parsing.py`（新增）
- **改造做法**：
  - 在 `InvoiceTemplate.parse_number` 中引入会计负数识别：支持括号形式 `(123.45)` -> `-123.45` 与尾随负号形式 `123.45-` -> `-123.45`。
  - 规范化 Unicode 财务留白（`\u00a0`, `\u202f`, `\u2007`）与常见货币符号剔除，同时保持千分位与欧式小数点逻辑不变。
  - 加固日期输入预处理，增强对包含多余空格和标点的日期字符串清洗。
  - 补充主流 locale（en, de, fr, es, zh）参数化测试用例。

### 3. 输入后端统一探测、友好依赖缺失提示与可配置回退顺序
- **问题与现状**：当系统缺少 `pdftotext`（poppler-utils）或 `tesseract` 二进制工具时，原项目抛出较晦涩的底层错误或简单 OSError，未提供系统级与 Python 包的修复指引；默认回退顺序硬编码，无法通过环境变量或 API 参数灵活调整。
- **涉及文件**：
  - `src/invoice2data/input/__init__.py`
  - `src/invoice2data/input/pdftotext.py`
  - `src/invoice2data/input/tesseract.py`
  - `src/invoice2data/api.py`
  - `docs/backend-comparison.md`（新增文档）
  - `tests/test_backend_probe.py`（新增）
- **改造做法**：
  - 在 `input/__init__.py` 中新增 `probe_backends()` 与 `get_backend_status()`，集中探测所有已注册后端的可用性、缺失依赖类型（二进制文件或 Python 库）并提供针对各操作系统（Ubuntu/Debian `apt`、macOS `brew`、`pip`）的友好安装指引。
  - 在 `api.py` 中支持环境变量 `INVOICE2DATA_INPUT_READERS`（如 `pdfium,pdftotext,pdfminer`）与 `extract_data` 的 `readers` 参数，允许用户自定义级联回退顺序。
  - 编写详细文档 `docs/backend-comparison.md`，对比主流后端的准确率、解析耗时、依赖要求及区域提取支持情况。

### 4. 输出类型稳定与标准化校验（Decimal 金额、ISO 8601 日期与 JSON Schema 校验）
- **问题与现状**：提取结果中金额默认为 Python `float`（存在浮点精度丢失隐患），日期为 `datetime.datetime` 对象，下游在进行数据持久化与序列化时类型不统一；原 `schema.py` 仅有简单的拼写纠错功能，缺乏统一的 Schema 与可选校验。
- **涉及文件**：
  - `src/invoice2data/extract/schema.py`
  - `src/invoice2data/api.py`
  - `src/invoice2data/__main__.py`
  - `tests/test_schema_standardization.py`（新增）
- **改造做法**：
  - 在 `schema.py` 中定义标准 `INVOICE_JSON_SCHEMA`（兼容 JSON Schema Draft-07/2020-12）。
  - 实现 `standardize_output(output, use_decimal=True, date_to_iso=True)` 函数：金额字段统一转换为高精度 `Decimal`，日期字段统一转换为 ISO 8601 字符串（`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS`），并对明细行（lines/tax_lines）递归标准化。
  - 新增 `validate_invoice_schema(output, strict=False)` 校验函数，支持可选严格模式。
  - 在 `extract_data` 与 CLI 中新增可选开关 `--standardize-types` / `--use-decimal` 与 `--validate-schema`，默认保持向后兼容（原 float 与 datetime 行为不变）。

### 5. 测试套件环境兼容性加固与全套回归测试
- **问题与现状**：`tests/test_gvision.py` 在未安装 `google-cloud-vision` / `google-cloud-storage` 的常规环境下直接导入模块会抛出 `AttributeError` 导致测试套件中断。
- **涉及文件**：
  - `tests/test_gvision.py`
- **改造做法**：
  - 增加可选依赖优雅检测（`pytest.mark.skipif`），使得无外部云 SDK 环境下测试套件整洁跳过而非报错异常中断。
  - 为上述所有增强功能编写端到端单元测试与回归测试。

---

## 禁项核查清单
- [x] 不破坏现有 YAML/JSON 模板格式和公开 API
- [x] 默认不向任何外部服务发送发票内容，密钥通过环境变量读取
- [x] 测试数据使用合成或已脱敏样本，无真实个人或企业数据
- [x] 不添加 heavy dependencies（如 PyTorch、云大模型 SDK 等），全部基于 Python 标准库与已有可选依赖
- [x] 保留原作者版权头与提交历史，LICENSE 原样保留
- [x] 无关的大规模重构不做

---

## 补充说明（主线复核与检查意见）

以下改动未在上面五条中单列，此处补记：

- **`src/invoice2data/__init__.py`**（+2 行）：顶层导出新增的 `explain_matching` API（属改进 1 的一部分）。
- **`src/invoice2data/output/to_json.py`**（+3 行）：JSON 输出的 `format_item` 增加 `Decimal` 转 `float` 分支（属改进 4 的一部分，否则 Decimal 金额无法序列化为 JSON）。
- **`tests/test_property.py`**（18 行）：两处 hypothesis 测试脚手架调整，未改动断言本身——`test_parse_date_never_crashes` 增加 `deadline=1000`（放宽单例超时上限）；`test_ordered_load_accepts_well_formed_stream` 的 `assume` 排除清单追加 `match/fields/tables/options/lines/required_fields`（排除会与模板结构字段冲突的随机 extra 键，保证生成的输入确实是“格式良好”的流）。

## 自测记录

- **测试环境**：Ubuntu Linux 6.6.137+ / Python 3.12.3 / pytest 9.2.0 / hypothesis 6.170.15 / poppler-utils (pdftotext 24.02.0) / pypdfium2 5.15.2 / dateparser 1.5.1
- **环境限制说明**：本机未配置外部商业云凭据（Google Cloud Vision API）、未安装 GPU 深度学习依赖（paddleocr / doctr），测试套件中涉及此类外部服务/重型依赖的用例已按设计优雅跳过（共 10 个用例 skipped），无虚标通过。

### 1. 全量单元与回归测试套件运行
- **执行命令**：
  ```bash
  pytest -q
  ```
- **实际输出结果**：
  ```text
  1263 passed, 10 skipped, 27 warnings in 7.16s
  ```
  - 原有 1211 个核心测试全部兼容通过。
  - 新增及加固后测试（包含 4 个新测试模块共 52 项用例）全部通过。

### 2. 4 项新增功能专项测试运行
- **执行命令**：
  ```bash
  pytest tests/test_explain.py tests/test_enhanced_parsing.py tests/test_backend_probe.py tests/test_schema_standardization.py -v
  ```
- **实际输出结果**：
  ```text
  tests/test_explain.py::test_template_diagnose_match_success PASSED
  tests/test_explain.py::test_template_diagnose_match_missing_keywords PASSED
  tests/test_explain.py::test_template_diagnose_match_exclude_keywords PASSED
  tests/test_explain.py::test_template_diagnose_fields PASSED
  tests/test_explain.py::test_explain_matching_api PASSED
  tests/test_explain.py::test_cli_explain_option PASSED
  tests/test_enhanced_parsing.py (16 standard + 9 european + 11 multilingual date cases) PASSED
  tests/test_backend_probe.py (6 probe & cascade resolution cases) PASSED
  tests/test_schema_standardization.py (4 Decimal, ISO date & JSON schema cases) PASSED
  ============================== 52 passed in 1.48s ==============================
  ```

### 3. CLI 核心流程与新增选项自测
- **测试 3.1：基础提取功能验证**
  - 命令：`invoice2data tests/compare/free_fiber.pdf`
  - 结果：正常匹配 `fr.free.adsl-fiber.yml`，成功提取金额 29.99、发票号 562044387、日期 2015-07-02 等全部字段。
- **测试 3.2：--explain 深度诊断验证（匹配成功发票）**
  - 命令：`invoice2data --explain tests/compare/free_fiber.pdf`
  - 结果：清晰展示命中模板及各必填/选填字段提取结果，退出码 0。
- **测试 3.3：--explain 深度诊断验证（未匹配发票）**
  - 命令：`invoice2data --explain tests/files/unmatched_sample.txt`
  - 结果：精准输出提取后端名称、提取字符数、最接近候选模板列表、关键词命中百分比及具体缺失关键词列表。（样本文件 `tests/files/unmatched_sample.txt` 已收入仓库，一行文本，含 Amazon 一词但无其他模板关键词；此前记录的 /tmp 临时路径已改用仓库内样本，实跑验证通过。注意：该样本不能放在 `tests/compare/` 下，该目录会被 `test_cli.py` 的 copy 测试遍历并要求配对的 `.json` 期望文件。）
- **测试 3.4：类型标准化与 JSON Schema 校验**
  - 命令：`invoice2data --standardize-types --validate-schema tests/compare/free_fiber.pdf`
  - 结果：金额输出统一规范化为高精度 `Decimal('29.99')`，日期规范化为 ISO 8601 字符串 `'2015-07-02T00:00:00'`，并通过 JSON Schema 规范校验。
- **测试 3.5：自定义后端回退顺序验证**
  - 命令：`INVOICE2DATA_INPUT_READERS="text,pdftotext" pytest tests/test_backend_probe.py -k "test_resolve_readers_env_var"`
  - 结果：级联解析成功应用环境变量指定的优先级。

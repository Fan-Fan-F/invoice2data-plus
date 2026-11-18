# Input Backend Comparison and Selection Guide

`invoice2data-plus` supports multiple text extraction backends (also called readers). Each backend makes different trade-offs between extraction speed, visual layout preservation, area-restricted extraction capability, OCR capability, and installation dependencies.

This guide provides an architectural and operational comparison to help you choose or configure the optimal cascade order for your deployment environment.

---

## 1. Quick Comparison Matrix

| Backend | Engine / Technology | Type | Speed | Layout Fidelity | Area Extraction (`SUPPORTS_AREA`) | Page Ranges (`SUPPORTS_PAGES`) | Primary Dependencies |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`pdfium`** *(default lead)* | Google PDFium (`pypdfium2`) | Digital PDF | **Ultra Fast** (~10–30ms) | Good | No | Yes | `pypdfium2` (pip wheel, zero C-binaries) |
| **`pdftotext`** *(default fallback)* | Poppler `pdftotext -layout` | Digital PDF | Fast (~30–80ms) | **Excellent** | **Yes** (bbox caching) | Yes | `poppler-utils` (system binary) |
| **`pdfoxide`** | Rust `pdf-oxide` | Digital PDF | Fast (~20–40ms) | Moderate | No | Yes | `pdf-oxide` (pip wheel) |
| **`pdfminer`** | Python `pdfminer.six` | Digital PDF | Moderate (~100–300ms) | Good | No | Yes | `pdfminer.six` (pip) |
| **`pdfplumber`** | `pdfminer` + geometry | Digital PDF | Moderate (~150–400ms) | Very Good | Yes | Yes | `pdfplumber` (pip) |
| **`hotpdf`** | Fast bbox indexer | Digital PDF | Very Fast (~20–50ms) | Good | No | Yes | `hotpdf` (pip) |
| **`tesseract`** | Tesseract OCR + ImageMagick | Scanned / Image | Slow (~1–3s) | Good | **Yes** | No | `tesseract-ocr`, `imagemagick` (system binaries) |
| **`ocrmypdf`** | OCRmyPDF wrapper | Scanned PDF | Slow (~2–5s) | High | No | Yes | `ocrmypdf`, `tesseract-ocr` |
| **`doctr`** | docTR Deep Learning | Scanned / Image | Resource heavy | High | No | No | `python-doctr[torch]` |
| **`paddleocr`** | PaddlePaddle OCR | Scanned / Image | Resource heavy | High | No | No | `paddleocr`, `paddlepaddle` |
| **`gvision`** | Google Cloud Vision API | Cloud OCR | Network bound (~1–2s) | **Best** | No | No | `google-cloud-vision`, `google-cloud-storage` |
| **`text`** | Built-in plaintext | Raw text / mock | Instant | N/A | No | No | None (Python standard library) |

---

## 2. Default Cascade Strategy

When no `--input-reader` (CLI) or `input_module` (Python API) is explicitly requested, `invoice2data-plus` runs an automated **two-tier cascade**:

1. **`pdfium`** runs first. It is packaged as self-contained binary wheels (`pypdfium2`), requiring no external OS packages. It processes digital PDFs in tens of milliseconds.
2. If `pdfium` cannot match all required fields, drops declared table line items, or if the matched template specifically pins `input_module: pdftotext`, the engine automatically cascades to **`pdftotext`**.
3. If all digital text extractors fail (e.g., scanned images disguised as PDFs), the engine automatically falls back to available OCR backends if installed (`tesseract` / `ocrmypdf`).

---

## 3. Configuring Custom Backend Cascades

In production, you can customize the backend fallback order without code changes using the `INVOICE2DATA_INPUT_READERS` environment variable or the API parameter:

### Via Environment Variable
```bash
# Prioritize pdfium, then pdftotext, then pdfminer:
export INVOICE2DATA_INPUT_READERS="pdfium,pdftotext,pdfminer"

invoice2data invoice.pdf
```

### Via Python API
```python
from invoice2data import extract_data

# Explicit list of readers in priority order:
result = extract_data(
    "invoice.pdf",
    readers=["pdfium", "pdftotext", "pdfminer"],
)
```

---

## 4. Probing Backend Availability Programmatically

You can probe backend availability, installed dependencies, and platform-specific installation commands directly in your application:

```python
from invoice2data.input import probe_backends, get_backend_status

# Probe all registered backends
status = probe_backends()
for name, info in status.items():
    print(f"{name:12s} available={info['available']} type={info['type']}")

# Inspect a single backend and retrieve installation commands
tesseract_info = get_backend_status("tesseract")
if not tesseract_info["available"]:
    print("Install hints:", tesseract_info["install_hints"])
```

---

## 5. System Dependency Installation Commands

### Ubuntu / Debian
```bash
# For pdftotext (Poppler)
sudo apt-get update && sudo apt-get install -y poppler-utils

# For Tesseract OCR and ImageMagick
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng imagemagick
```

### macOS (Homebrew)
```bash
brew install poppler
brew install tesseract imagemagick
```

### Pure-Python / Wheel Backends (Docker & Serverless Friendly)
If your deployment container cannot install OS packages via `apt` or `brew`, use `pdfium` and `pdfminer`:
```bash
pip install pypdfium2 pdfminer.six
```

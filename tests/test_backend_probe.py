"""Unit tests for backend availability probing, dependency hints, and reader cascade resolution."""

from pathlib import Path
import pytest

from invoice2data.api import _resolve_readers
from invoice2data.input import get_backend_status
from invoice2data.input import pdftotext
from invoice2data.input import pdfium
from invoice2data.input import probe_backends
from invoice2data.input import text
from invoice2data.input import tesseract


def test_probe_backends_structure() -> None:
    backends = probe_backends()
    assert isinstance(backends, dict)
    assert "pdfium" in backends
    assert "pdftotext" in backends
    assert "text" in backends
    assert "tesseract" in backends

    # Verify backend structure
    pdfium_info = backends["pdfium"]
    assert pdfium_info["name"] == "pdfium"
    assert isinstance(pdfium_info["available"], bool)
    assert isinstance(pdfium_info["supports_area"], bool)
    assert isinstance(pdfium_info["supports_pages"], bool)
    assert "package" in pdfium_info
    assert "install_hints" in pdfium_info

    # text backend should always be available
    assert backends["text"]["available"] is True


def test_get_backend_status_valid_and_invalid() -> None:
    status = get_backend_status("pdftotext")
    assert status["name"] == "pdftotext"
    assert "install_hints" in status

    with pytest.raises(KeyError, match="Unknown input backend"):
        get_backend_status("nonexistent_reader_xyz")


def test_resolve_readers_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test setting custom reader cascade via INVOICE2DATA_INPUT_READERS
    monkeypatch.setenv("INVOICE2DATA_INPUT_READERS", "text,pdftotext")
    readers = _resolve_readers("sample.pdf", None)
    assert readers[0] == text
    assert len(readers) >= 1


def test_resolve_readers_parameter() -> None:
    readers = _resolve_readers("sample.pdf", None, readers=["text", "pdftotext"])
    assert readers[0] == text


def test_pdftotext_friendly_error_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Simulate missing pdftotext binary
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy")

    with pytest.raises(OSError, match="Install poppler-utils"):
        pdftotext.to_text(str(dummy_pdf))


def test_tesseract_friendly_error_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Simulate missing tesseract binary
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    dummy_img = tmp_path / "dummy.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(OSError, match="Install tesseract-ocr"):
        tesseract.to_text(str(dummy_img))

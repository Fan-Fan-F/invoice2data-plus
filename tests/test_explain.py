"""Unit tests for template diagnostic and explain matching functionality."""

from click.testing import CliRunner
import pytest

from invoice2data import explain_matching
from invoice2data.__main__ import main
from invoice2data.extract.invoice_template import InvoiceTemplate


def test_template_diagnose_match_success() -> None:
    tpl = InvoiceTemplate(
        {
            "template_name": "test_tmpl",
            "issuer": "Acme Corp",
            "keywords": ["Invoice", "Acme", "Total"],
            "exclude_keywords": ["Draft", "Estimate"],
        }
    )
    doc_text = "Acme Corp Invoice Total $100.00 Thank you"
    diag = tpl.diagnose_match(doc_text)

    assert diag["matched"] is True
    assert set(diag["keywords_matched"]) == {"Invoice", "Acme", "Total"}
    assert diag["keywords_missing"] == []
    assert diag["exclude_triggered"] is False
    assert diag["match_ratio"] == 1.0


def test_template_diagnose_match_missing_keywords() -> None:
    tpl = InvoiceTemplate(
        {
            "template_name": "test_tmpl",
            "issuer": "Acme Corp",
            "keywords": ["Invoice", "Acme", "VAT"],
            "exclude_keywords": [],
        }
    )
    doc_text = "Acme Corp Invoice Total $100.00"
    diag = tpl.diagnose_match(doc_text)

    assert diag["matched"] is False
    assert set(diag["keywords_matched"]) == {"Invoice", "Acme"}
    assert diag["keywords_missing"] == ["VAT"]
    assert pytest.approx(diag["match_ratio"], 0.01) == 2 / 3
    assert "Missing keywords: VAT" in diag["reason"]


def test_template_diagnose_match_exclude_keywords() -> None:
    tpl = InvoiceTemplate(
        {
            "template_name": "test_tmpl",
            "issuer": "Acme Corp",
            "keywords": ["Invoice", "Acme"],
            "exclude_keywords": ["Proforma"],
        }
    )
    doc_text = "Acme Corp Proforma Invoice"
    diag = tpl.diagnose_match(doc_text)

    assert diag["matched"] is False
    assert diag["exclude_triggered"] is True
    assert diag["exclude_keywords_matched"] == ["Proforma"]
    assert "exclude keywords triggered" in diag["reason"].lower()


def test_template_diagnose_fields() -> None:
    tpl = InvoiceTemplate(
        {
            "template_name": "test_fields_tmpl",
            "issuer": "Acme Corp",
            "keywords": ["Acme"],
            "required_fields": ["amount", "invoice_number"],
            "fields": {
                "amount": r"Total:\s*\$([0-9.]+)",
                "invoice_number": r"INV-(\d+)",
                "optional_ref": r"REF:(\w+)",
            },
        }
    )
    # Both required fields match
    text_ok = "Acme Corp INV-9988 Total: $123.45"
    diag_ok = tpl.diagnose_fields(text_ok)
    assert diag_ok["success"] is True
    assert diag_ok["required_fields_missing"] == []
    assert diag_ok["fields_matched"]["amount"] == 123.45
    assert diag_ok["fields_matched"]["invoice_number"] == "9988"
    assert "optional_ref" in diag_ok["fields_missing"]

    # Missing one required field
    text_bad = "Acme Corp Total: $123.45"
    diag_bad = tpl.diagnose_fields(text_bad)
    assert diag_bad["success"] is False
    assert diag_bad["required_fields_missing"] == ["invoice_number"]


def test_explain_matching_api() -> None:
    report = explain_matching("tests/compare/free_fiber.pdf")
    assert "invoicefile" in report
    assert "reader" in report
    assert "closest_candidates" in report
    assert isinstance(report["closest_candidates"], list)
    assert report["text_length"] > 0


def test_cli_explain_option() -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--explain", "tests/compare/free_fiber.pdf"],
    )
    assert result.exit_code == 0
    assert "free_fiber.pdf" in result.output
    # Must report either matched template or diagnostic details
    assert "matched:" in result.output or "[diagnostic]" in result.output

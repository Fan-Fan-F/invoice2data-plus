"""Unit tests for output type standardization (Decimal, ISO 8601) and JSON Schema validation."""

import datetime
from decimal import Decimal
from pathlib import Path
from click.testing import CliRunner
import pytest

from invoice2data import extract_data
from invoice2data.__main__ import main
from invoice2data.extract.schema import INVOICE_JSON_SCHEMA
from invoice2data.extract.schema import standardize_output
from invoice2data.extract.schema import validate_invoice_schema


def test_standardize_output_decimal_and_iso_dates() -> None:
    raw = {
        "issuer": "Test Corp",
        "invoice_number": "INV-1001",
        "amount": 1234.56,
        "amount_untaxed": 1000.0,
        "amount_tax": 234.56,
        "date": datetime.datetime(2024, 5, 1, 14, 30, 0),
        "date_due": datetime.date(2024, 6, 1),
        "currency": "EUR",
        "lines": [
            {
                "name": "Widget A",
                "qty": 2,
                "price_unit": 500.0,
                "price_total": 1000.0,
            }
        ],
        "tax_lines": [
            {
                "price_subtotal": 1000.0,
                "line_tax_percent": 23.456,
                "line_tax_amount": 234.56,
            }
        ],
    }

    std = standardize_output(raw, use_decimal=True, date_to_iso=True)

    # Top-level amount fields must be Decimal
    assert isinstance(std["amount"], Decimal)
    assert std["amount"] == Decimal("1234.56")
    assert isinstance(std["amount_untaxed"], Decimal)
    assert isinstance(std["amount_tax"], Decimal)

    # Date fields must be ISO strings
    assert isinstance(std["date"], str)
    assert std["date"] == "2024-05-01T14:30:00"
    assert isinstance(std["date_due"], str)
    assert std["date_due"] == "2024-06-01"

    # Nested lines must be standardized
    line = std["lines"][0]
    assert isinstance(line["price_unit"], Decimal)
    assert isinstance(line["price_total"], Decimal)
    assert line["qty"] == 2

    # Nested tax_lines must be standardized
    tax_line = std["tax_lines"][0]
    assert isinstance(tax_line["price_subtotal"], Decimal)
    assert isinstance(tax_line["line_tax_percent"], Decimal)
    assert isinstance(tax_line["line_tax_amount"], Decimal)


def test_validate_invoice_schema() -> None:
    valid_data = {
        "issuer": "Amazon Web Services",
        "invoice_number": "42183017",
        "date": "2014-08-03",
        "amount": 4.11,
        "currency": "USD",
        "lines": [
            {"name": "AWS Data Transfer", "price_unit": 0.01}
        ],
    }

    is_valid, errors = validate_invoice_schema(valid_data, strict=False)
    assert is_valid is True
    assert errors == []

    # Missing mandatory 'issuer'
    invalid_data = {
        "invoice_number": "42183017",
        "amount": 4.11,
    }
    is_valid_inv, errors_inv = validate_invoice_schema(invalid_data, strict=False)
    assert is_valid_inv is False
    assert len(errors_inv) > 0

    with pytest.raises(ValueError, match="Invoice schema validation failed"):
        validate_invoice_schema(invalid_data, strict=True)


def test_extract_data_with_standardization() -> None:
    res = extract_data(
        "tests/compare/free_fiber.pdf",
        standardize_types=True,
        validate_schema=True,
    )
    assert res, "Should extract data from sample invoice"
    assert isinstance(res["amount"], Decimal)
    assert isinstance(res["date"], str)
    assert res["issuer"] == "Free"


def test_cli_standardize_and_validate_flags(tmp_path: Path) -> None:
    runner = CliRunner()
    out_json = tmp_path / "out.json"
    result = runner.invoke(
        main,
        [
            "--standardize-types",
            "--validate-schema",
            "--output-format",
            "json",
            "--output-name",
            str(out_json),
            "tests/compare/free_fiber.pdf",
        ],
    )
    assert result.exit_code == 0
    assert out_json.exists()
    import json
    data = json.loads(out_json.read_text())
    assert data[0]["issuer"] == "Free"

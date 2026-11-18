"""Unit tests for enhanced numeric, currency, accounting negative, and multilingual date parsing."""

import datetime
import pytest

from invoice2data.extract._dates import parse_date
from invoice2data.extract.invoice_template import InvoiceTemplate


@pytest.fixture
def standard_template() -> InvoiceTemplate:
    return InvoiceTemplate(
        {
            "template_name": "test_num_en",
            "issuer": "Test",
            "keywords": ["Test"],
            "options": {"decimal_separator": "."},
        }
    )


@pytest.fixture
def european_template() -> InvoiceTemplate:
    return InvoiceTemplate(
        {
            "template_name": "test_num_eu",
            "issuer": "Test",
            "keywords": ["Test"],
            "options": {"decimal_separator": ","},
        }
    )


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("(1,234.56)", -1234.56),
        ("( 123.45 )", -123.45),
        ("120.00-", -120.0),
        ("1,500.25-", -1500.25),
        ("120.00\u2212", -120.0),  # unicode minus
        ("-120.00", -120.0),
        ("$ 1,234.56", 1234.56),
        ("($ 1,234.56)", -1234.56),
        ("-$ 50.00", -50.0),
        ("USD 2,500.00", 2500.0),
        ("2,500.00 USD", 2500.0),
        ("£ 99.99", 99.99),
        ("¥ 5000", 5000.0),
        ("₹ 1,500.50", 1500.50),
        ("100.00", 100.0),
        (" 42.50 ", 42.50),
    ],
)
def test_parse_number_standard_locale(
    standard_template: InvoiceTemplate, raw_value: str, expected: float
) -> None:
    parsed = standard_template.parse_number(raw_value)
    assert parsed == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("1.234,56", 1234.56),
        ("(1.234,56)", -1234.56),
        ("120,00-", -120.0),
        ("1 234,56 €", 1234.56),
        ("€ 1.234,56", 1234.56),
        ("1\u00a0234,56", 1234.56),  # non-breaking space
        ("1\u202f234,56", 1234.56),  # narrow non-breaking space
        ("EUR 1.234,56", 1234.56),
        ("50,00", 50.0),
    ],
)
def test_parse_number_european_locale(
    european_template: InvoiceTemplate, raw_value: str, expected: float
) -> None:
    parsed = european_template.parse_number(raw_value)
    assert parsed == pytest.approx(expected)


@pytest.mark.parametrize(
    "raw_date,languages,date_formats,expected_year,expected_month,expected_day",
    [
        # English
        ("2024-05-18", (), (), 2024, 5, 18),
        ("Date: 2024-05-18", (), (), 2024, 5, 18),
        ("[2024-05-18]", (), (), 2024, 5, 18),
        ("18 May 2024", ("en",), ("%d %B %Y",), 2024, 5, 18),
        # French
        ("02 juillet 2015", ("fr",), ("%d %B %Y",), 2015, 7, 2),
        ("Date : 02 juillet 2015", ("fr",), ("%d %B %Y",), 2015, 7, 2),
        # German
        ("15. März 2023", ("de",), ("%d. %B %Y",), 2023, 3, 15),
        ("Datum: 15. März 2023", ("de",), ("%d. %B %Y",), 2023, 3, 15),
        # Spanish
        ("12 de octubre de 2022", ("es",), (), 2022, 10, 12),
        ("Fecha: 12 de octubre de 2022", ("es",), (), 2022, 10, 12),
        # Chinese / numeric
        ("2023年08月15日", ("zh",), (), 2023, 8, 15),
    ],
)
def test_parse_date_multilingual_and_cleaned(
    raw_date: str,
    languages: tuple[str, ...],
    date_formats: tuple[str, ...],
    expected_year: int,
    expected_month: int,
    expected_day: int,
) -> None:
    parsed = parse_date(raw_date, date_formats=date_formats, languages=languages)
    assert parsed is not None
    assert parsed.year == expected_year
    assert parsed.month == expected_month
    assert parsed.day == expected_day

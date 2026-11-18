"""This module abstracts templates for invoice providers.

Templates are initially read from .yml files and then kept as class.
"""

import unicodedata
from collections import OrderedDict as OrderedDictType
from logging import DEBUG
from logging import getLogger
from pprint import pformat
from typing import Any

from ..exceptions import RequiredFieldsMissingError
from ..exceptions import TemplateSyntaxError
from ..input import extract_text
from ..input import supports_area
from . import _dates
from . import _regex
from . import parsers
from . import schema
from . import unece_uom
from .plugins import camelot
from .plugins import lines
from .plugins import tables


logger = getLogger(__name__)

#: Dedicated logger for the optimized_str dump, so `--debug-optimized-str` can show
#: just that (without the rest of the debug noise) by raising this logger alone.
optimized_str_logger = getLogger("invoice2data.optimized_str")


def _keyword_matches(keyword: str, text: str) -> bool:
    r"""Return whether ``keyword`` matches ``text`` as a regex (issue #742).

    The tutorial has always documented ``keywords`` / ``exclude_keywords`` as
    regex patterns (e.g. ``Company\s+(US|UK)``, ``(?i)Accor``), but the code
    was doing a plain ``in`` substring test -- so ~16 bundled templates that
    already used regex syntax silently under-matched. Use :func:`regex.search`
    to honour the documented contract.

    Falls back to a plain substring check when the pattern does not compile
    as valid regex, so an existing simple-string keyword containing a stray
    metacharacter (``Company (Ltd)``) keeps matching literally instead of
    breaking. The fallback is DEBUG-logged so a template author can spot it
    when investigating why their pattern didn't match.
    """
    try:
        return _regex.search(keyword, text) is not None
    except _regex.error as exc:
        logger.debug(
            "keyword %r is not a valid regex (%s); falling back to substring match",
            keyword,
            exc,
        )
        return keyword in text


OPTIONS_DEFAULT = {
    "remove_whitespace": False,
    "remove_accents": False,
    "lowercase": False,
    "currency": "EUR",
    "date_formats": [],
    "languages": [],
    "decimal_separator": ".",
    "replace": [],  # example: see templates/fr/fr.free.mobile.yml
}

PARSERS_MAPPING = {
    "lines": parsers.lines,
    "regex": parsers.regex,
    "static": parsers.static,
}

PLUGIN_MAPPING = {"lines": lines, "tables": tables, "camelot": camelot}


class InvoiceTemplate(OrderedDictType[str, Any]):
    """Represents single template files that live as .yml files on the disk.

    Methods:
      prepare_input(extracted_str)
          Input raw string
          and perform transformations, as set in the template file.
      matches_input(extracted_str)
          Check if the string matches keywords set in the template file.
      parse_number(value)
          Parse number, remove decimal separator and add other options.
      parse_date(value)
          Parse date and return the date after parsing.
      coerce_type(value, target_type)
          Change the type of values.
      extract(optimized_str)
          Given a template file and a string, extract matching data fields.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Merge template-specific options with defaults
        self.options: dict[str, Any] = OPTIONS_DEFAULT.copy()

        if "options" in self:
            self.options.update(self["options"])

        languages = self.options.get("languages", [])

        if not isinstance(languages, list):
            languages = [languages]

        for lang in self.options.get("languages", []):  # type: ignore [attr-defined]
            if len(lang) != 2:
                raise AssertionError(
                    "Error in Template %s lang code must have 2 letters"
                    % self["template_name"]
                )

        # Set issuer, if it doesn't exist.
        if "issuer" not in self.keys():
            self["issuer"] = self["keywords"][0]

    def prepare_input(self, extracted_str: str) -> str:
        """Input raw string and do transformations, as set in template file."""
        # Remove whitespace
        if self.options["remove_whitespace"]:
            optimized_str = _regex.sub(" +", "", extracted_str)
        else:
            optimized_str = extracted_str

        # Remove accents
        if self.options["remove_accents"]:
            optimized_str = _regex.sub(
                "[\u0300-\u0362]", "", unicodedata.normalize("NFKD", optimized_str)
            )

        # Convert to lower case
        if self.options["lowercase"]:
            optimized_str = optimized_str.lower()

        if not isinstance(self.options.get("replace", []), list):
            self.options["replace"] = [self.options["replace"]]

        # Specific replace
        for replace in self.options.get("replace", []):
            if len(replace) != 2:
                raise TemplateSyntaxError(
                    "A `replace` entry must be a [pattern, repl] pair "
                    f"(got {len(replace)} elements)",
                    self.get("template_name"),
                )
            optimized_str = _regex.sub(replace[0], replace[1], optimized_str)

        return optimized_str

    def matches_input(self, extracted_str: str) -> bool:
        """Check if the extracted string matches the template keywords.

        ``keywords`` and ``exclude_keywords`` are matched as **regex patterns**
        (the documented long-standing contract in the tutorial). A keyword is
        considered found when :func:`regex.search` returns a match anywhere in
        the extracted text. Any keyword that does not compile as a valid regex
        falls back to a plain substring check, so simple string keywords like
        ``"ACME"`` continue to work unchanged.

        Args:
            extracted_str (str): The extracted text from the invoice.

        Returns:
            bool: True if the extracted string matches the template keywords,
                False otherwise.
        """
        if all(_keyword_matches(k, extracted_str) for k in self["keywords"]):
            # All keywords found
            if self["exclude_keywords"] and any(
                _keyword_matches(k, extracted_str) for k in self["exclude_keywords"]
            ):
                # At least one exclude_keyword found
                logger.debug(
                    "Template: %s | Keywords matched. Exclude keyword found!",
                    self["template_name"],
                )
                return False
            # No exclude_keywords or none found, template is good
            logger.debug(
                "Template: %s | Keywords matched. No exclude keywords found.",
                self["template_name"],
            )
            return True
        logger.debug(
            "Template: %s | Failed to match all keywords.", self["template_name"]
        )
        return False

    def diagnose_match(self, extracted_str: str) -> dict[str, Any]:
        """Diagnose whether and why this template matches the extracted text.

        Returns structured diagnostic details on keyword matching, missing
        keywords, and any exclude_keywords triggered.

        Args:
            extracted_str (str): The extracted text from the invoice.

        Returns:
            dict[str, Any]: Structured diagnosis containing:
                - template_name: str
                - matched: bool
                - keywords_matched: list[str]
                - keywords_missing: list[str]
                - exclude_keywords_matched: list[str]
                - exclude_triggered: bool
                - match_ratio: float (0.0 to 1.0)
                - reason: str
        """
        keywords = self.get("keywords") or []
        exclude_keywords = self.get("exclude_keywords") or []

        matched_kws = [k for k in keywords if _keyword_matches(k, extracted_str)]
        missing_kws = [k for k in keywords if not _keyword_matches(k, extracted_str)]
        exclude_matched = [
            k for k in exclude_keywords if _keyword_matches(k, extracted_str)
        ]
        exclude_triggered = bool(exclude_matched)

        all_kws_matched = (len(missing_kws) == 0) if keywords else True
        matched = all_kws_matched and not exclude_triggered

        ratio = (
            (len(matched_kws) / len(keywords))
            if keywords
            else (1.0 if not exclude_triggered else 0.0)
        )

        if matched:
            reason = "All keywords matched and no exclude keywords triggered."
        elif not all_kws_matched and exclude_triggered:
            reason = (
                f"Missing keywords ({', '.join(missing_kws)}) and "
                f"exclude keywords triggered ({', '.join(exclude_matched)})."
            )
        elif not all_kws_matched:
            reason = f"Missing keywords: {', '.join(missing_kws)}."
        else:
            reason = f"Exclude keywords triggered: {', '.join(exclude_matched)}."

        return {
            "template_name": self.get("template_name", "<unknown>"),
            "matched": matched,
            "keywords_matched": matched_kws,
            "keywords_missing": missing_kws,
            "exclude_keywords_matched": exclude_matched,
            "exclude_triggered": exclude_triggered,
            "match_ratio": ratio,
            "reason": reason,
        }

    def diagnose_fields(
        self, optimized_str: str, invoice_file: str = "", input_module: Any = None
    ) -> dict[str, Any]:
        """Diagnose field extraction results against optimized text.

        Runs field parsers and reports which fields matched, their extracted
        values, which fields were missing, and whether required fields are
        satisfied.

        Args:
            optimized_str (str): The preprocessed text for this template.
            invoice_file (str): Optional path to invoice file (for file-based plugins).
            input_module (Any): Optional input module used.

        Returns:
            dict[str, Any]: Structured field diagnosis containing:
                - template_name: str
                - fields_matched: dict[str, Any]
                - fields_missing: list[str]
                - required_fields: list[str]
                - required_fields_missing: list[str]
                - success: bool
                - output: dict[str, Any]
                - error: str | None
        """
        output = _initialize_output_and_log(self, optimized_str)
        fields_config = self.get("fields") or {}
        declared_fields = list(fields_config.keys())
        error_msg = None

        try:
            for k, v in fields_config.items():
                if isinstance(v, dict):
                    parser_settings = dict(v)
                    pages = parser_settings.pop("pages", self.get("pages"))
                    optimized_str_for_parser = _handle_area(
                        self,
                        parser_settings,
                        input_module,
                        invoice_file,
                        optimized_str,
                        pages,
                    )
                    if "parser" in parser_settings:
                        _handle_parser(
                            self, k, parser_settings, optimized_str_for_parser, output
                        )
                elif k.startswith("static_"):
                    output[k.replace("static_", "")] = v
                else:
                    _handle_legacy_syntax(self, k, v, optimized_str, output)

            output.setdefault("currency", self.options.get("currency", "EUR"))

            for plugin_keyword, plugin_func in PLUGIN_MAPPING.items():
                if plugin_keyword in self.keys():
                    plugin_func.extract(self, optimized_str, output, invoice_file)

            schema.normalize_line_fields(output)
            unece_uom.normalize_lines_uom(output)
            _apply_tax_to_lines(output)
            _compute_line_tax(output)
            _validate_tax_total(output, self.get("template_name"))
            _validate_fields(self, output)
        except Exception as exc:
            error_msg = str(exc)

        # Check required fields
        if "required_fields" in self:
            required = list(self["required_fields"])
        else:
            required = ["date", "amount", "invoice_number", "issuer"]

        missing_required = [f for f in required if f not in output]
        matched_fields = {k: v for k, v in output.items() if not k.startswith("_")}
        missing_fields = [
            k
            for k in declared_fields
            if k not in output and k.replace("static_", "") not in output
        ]

        return {
            "template_name": self.get("template_name", "<unknown>"),
            "fields_matched": matched_fields,
            "fields_missing": missing_fields,
            "required_fields": required,
            "required_fields_missing": missing_required,
            "success": len(missing_required) == 0 and error_msg is None,
            "output": output,
            "error": error_msg,
        }

    def parse_number(self, value: str) -> float:
        """Parses a number from a string.

        This function parses a numerical value from a string, handling
        different decimal separators, thousands separators, accounting
        parentheses negatives, trailing minus signs, currency symbols, and
        Unicode whitespace based on locale.

        Args:
            value (str): The string containing the number to be parsed.

        Returns:
            float: The parsed numerical value.

        Raises:
            TypeError: If ``value`` is not a string (internal invariant).
            TemplateSyntaxError: If ``options.decimal_separator`` is not a
                string, or the decimal separator appears more than once in
                ``value``.
        """
        if not isinstance(value, str):
            # Internal invariant: parsers upstream always hand us a string;
            # keep as a runtime TypeError (not asserting on hot path).
            raise TypeError(f"parse_number expected str, got {type(value).__name__}")

        # Normalize unicode whitespace (non-breaking, narrow non-breaking, etc.)
        cleaned = (
            value.replace("\u00a0", " ")
            .replace("\u202f", " ")
            .replace("\u2007", " ")
            .replace("\u200b", "")
            .strip()
        )

        is_negative = False

        # Accounting negative parentheses: (1,234.56) or ( 123.45 )
        if cleaned.startswith("(") and cleaned.endswith(")"):
            is_negative = True
            cleaned = cleaned[1:-1].strip()

        # Trailing negative sign: 120.00- or 120.00 − (U+2212)
        if cleaned.endswith("-") or cleaned.endswith("\u2212"):
            is_negative = True
            cleaned = cleaned[:-1].strip()

        # Leading negative sign: -120.00 or −120.00
        if cleaned.startswith("-") or cleaned.startswith("\u2212"):
            is_negative = True
            cleaned = cleaned[1:].strip()

        # Strip currency symbols and common currency codes
        cleaned = _regex.sub(r"[\$€£¥₹₽₩₪¢]", "", cleaned).strip()
        cleaned = _regex.sub(
            r"(?i)^(?:USD|EUR|GBP|CAD|AUD|CHF|CNY|JPY)\s+",
            "",
            cleaned,
        ).strip()
        cleaned = _regex.sub(
            r"(?i)\s+(?:USD|EUR|GBP|CAD|AUD|CHF|CNY|JPY)$",
            "",
            cleaned,
        ).strip()

        # Early exit if no thousands separator or custom decimal separator is present
        if not any(char in cleaned for char in r",.'\s"):
            parsed = float(cleaned)
            return -abs(parsed) if is_negative else parsed

        if not isinstance(self.options["decimal_separator"], str):
            raise TemplateSyntaxError(
                "`options.decimal_separator` must be a string",
                self.get("template_name"),
            )
        if cleaned.count(self.options["decimal_separator"]) >= 2:
            raise TemplateSyntaxError(
                "Decimal separator cannot appear more than once in a value",
                self.get("template_name"),
            )

        # Determine the thousands separator based on the decimal separator
        thousands_separator = "," if self.options["decimal_separator"] == "." else "."

        # Remove all possible thousands separators
        amount_no_thousand_sep = _regex.sub(
            r"[\s']", "", cleaned.replace(thousands_separator, "")
        )

        # Replace the decimal separator with a dot
        parsed = float(
            amount_no_thousand_sep.replace(str(self.options["decimal_separator"]), ".")
        )
        return -abs(parsed) if is_negative else parsed

    def parse_date(self, value: str) -> Any:
        """Parses date and returns date after parsing."""
        res = _dates.parse_date(
            value,
            tuple(self.options["date_formats"] or ()),
            tuple(self.options["languages"] or ()),
        )
        logger.debug("result of date parsing=%s", res)
        return res

    def coerce_type(self, value: str, target_type: str) -> Any:
        """Coerces a value to the specified target type.

        Args:
            value (str): The value to be coerced.
            target_type (str): The target type to which the value should be coerced.
                                  Valid values: 'int', 'float', 'date'.

        Returns:
            Any: The coerced value.

        Raises:
            TemplateSyntaxError: If ``target_type`` is not one of the supported
                values.
        """
        if target_type == "int":
            if not value:
                return 0
            return int(self.parse_number(value))
        if target_type == "float":
            if not value:
                return 0.0
            return float(self.parse_number(value))
        if target_type == "date" or target_type == "datetime":
            return self.parse_date(value)
        raise TemplateSyntaxError(
            f"Unknown field type {target_type!r}; expected int/float/date/datetime",
            self.get("template_name"),
        )

    def extract(
        self, optimized_str: str, invoice_file: str, input_module: Any
    ) -> dict[str, Any]:
        """Extracts data from the optimized string using the template.

        Args:
            optimized_str (str): The optimized string.
            invoice_file (str): The path to the invoice file.
            input_module (Any): The input module used.

        Returns:
            dict[str, Any]: The extracted data.

        """
        output = _initialize_output_and_log(self, optimized_str)

        for k, v in self["fields"].items():
            if isinstance(v, dict):
                parser_settings = dict(v)
                # A modern field is a text selector in its own right. Keep
                # ``pages`` out of parser settings: it controls input text,
                # rather than the regex/lines parser's behaviour.
                pages = parser_settings.pop("pages", self.get("pages"))
                optimized_str_for_parser = _handle_area(
                    self,
                    parser_settings,
                    input_module,
                    invoice_file,
                    optimized_str,
                    pages,
                )

                if "parser" in parser_settings:
                    _handle_parser(
                        self, k, parser_settings, optimized_str_for_parser, output
                    )

            elif k.startswith("static_"):
                logger.debug("field=%s | static value=%s", k, v)
                output[k.replace("static_", "")] = v

            else:
                _handle_legacy_syntax(self, k, v, optimized_str, output)
        # Fall back to the template's `options.currency` only when no field
        # extracted a currency. Prior versions unconditionally overwrote the
        # captured value with the option (default "EUR"), silently defeating
        # dynamic currency extraction; use setdefault to preserve it.
        output.setdefault("currency", self.options["currency"])

        # Run plugins (invoice_file is needed by path-based plugins like camelot):
        for plugin_keyword, plugin_func in PLUGIN_MAPPING.items():
            if plugin_keyword in self.keys():
                plugin_func.extract(self, optimized_str, output, invoice_file)
        # Normalise line/tax_line field names to the canonical vocabulary before
        # any computation/validation runs on them. Then derive `unece_code` from
        # captured `uom` literals so the OCA Odoo importer can map it straight.
        schema.normalize_line_fields(output)
        unece_uom.normalize_lines_uom(output)
        _apply_tax_to_lines(output)
        _compute_line_tax(output)
        _validate_tax_total(output, self["template_name"])
        _validate_fields(self, output)
        return _check_required_fields(self, output)


def _initialize_output_and_log(
    self: InvoiceTemplate, optimized_str: str
) -> dict[str, Any]:
    """Initialize the output dictionary and log debug information."""
    optimized_str_logger.debug(
        "START optimized_str ========================\n%s", optimized_str
    )
    optimized_str_logger.debug("END optimized_str ==========================")
    logger.debug(
        "Date parsing: languages=%s date_formats=%s",
        self.options["languages"],
        self.options["date_formats"],
    )
    logger.debug(
        "Float parsing: decimal separator=[%s]", self.options["decimal_separator"]
    )
    logger.debug("keywords=%s", self["keywords"])
    logger.debug(self.options)

    output = {}
    output["issuer"] = self["issuer"]
    # Expose which template matched, for downstream tooling (issue #618).
    output["template_name"] = self.get("template_name", "")
    return output


def _handle_area(
    self: InvoiceTemplate,
    v: dict[str, Any],
    input_module: Any,
    invoice_file: str,
    optimized_str: str,
    pages: Any = None,
) -> str:
    """Select a field's optional page range and/or physical area."""
    if "area" in v and supports_area(input_module):
        logger.debug(f"Area was specified with parameters {v['area']}")
        optimized_str_area: str = extract_text(
            input_module, invoice_file, v["area"], pages=pages
        )
        logger.debug(
            "START pdftotext area result ===========================\n%s",
            optimized_str_area,
        )
        logger.debug("END pdftotext area result =============================")
        return optimized_str_area
    if pages is not None:
        return extract_text(input_module, invoice_file, pages=pages)
    return optimized_str


def _handle_parser(
    self: InvoiceTemplate,
    k: str,
    v: dict[str, Any],
    optimized_str_for_parser: str,
    output: dict[str, Any],
) -> None:
    """Handle parsing using different parsers."""
    if v["parser"] in PARSERS_MAPPING:
        parser = PARSERS_MAPPING[v["parser"]]
        value = parser.parse(self, k, v, optimized_str_for_parser)
        if value or value == 0.0:
            output[k] = value
        else:
            logger.warning("Failed to parse field %s with parser %s", k, v["parser"])
    else:
        logger.error("Field %s has unknown parser %s set", k, v["parser"])


def _handle_legacy_syntax(
    self: InvoiceTemplate, k: str, v: Any, optimized_str: str, output: dict[str, Any]
) -> None:
    """Handle legacy syntax for backward compatibility."""
    result = None
    if k.startswith("sum_amount") and type(v) is list:
        k = k[4:]
        result = parsers.regex.parse(
            self, k, {"regex": v, "type": "float", "group": "sum"}, optimized_str, True
        )
    elif k.startswith("date") or k.endswith("date"):
        result = parsers.regex.parse(
            self, k, {"regex": v, "type": "date"}, optimized_str, True
        )
    elif k.startswith("amount"):
        result = parsers.regex.parse(
            self, k, {"regex": v, "type": "float"}, optimized_str, True
        )
    else:
        result = parsers.regex.parse(self, k, {"regex": v}, optimized_str, True)

    if result or result == 0.0:
        output[k] = result
    else:
        logger.warning("regexp for field %s didn't match", k)


def _to_float(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it cannot be converted.

    Args:
        value (Any): The value to convert (already type-coerced in most templates).

    Returns:
        float | None: The float value, or ``None`` when conversion fails.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _set_line_rate(line: dict[str, Any], percent: Any) -> None:
    """Set ``line_tax_percent`` on a line and compute its ``line_tax_amount``.

    The amount is only computed when a ``price_subtotal`` is present and no
    ``line_tax_amount`` was extracted.

    Args:
        line (dict[str, Any]): A single product line, modified in place.
        percent (Any): The tax rate to apply.
    """
    line["line_tax_percent"] = percent
    if "line_tax_amount" not in line and "price_subtotal" in line:
        subtotal = _to_float(line["price_subtotal"])
        rate = _to_float(percent)
        if subtotal is not None and rate is not None:
            line["line_tax_amount"] = round(subtotal * rate / 100, 2)


def _single_active_rate(tax_lines: list[Any]) -> Any:
    """Return the sole non-zero tax rate in a summary, or ``None`` if ambiguous.

    A row counts as "active" when its ``line_tax_percent`` is non-zero and it has
    a non-zero ``price_subtotal`` or ``line_tax_amount`` (goods were taxed at that
    rate). With exactly one distinct active rate the summary is unambiguous; with
    zero or several active rates the rate cannot be assigned to a line safely.

    Args:
        tax_lines (list[Any]): The ``tax_lines`` summary rows.

    Returns:
        Any: The single active rate, or ``None`` when zero/several are present.
    """
    rates: dict[float, Any] = {}
    for row in tax_lines:
        if not isinstance(row, dict):
            continue
        percent = _to_float(row.get("line_tax_percent"))
        if not percent:
            continue
        subtotal = _to_float(row.get("price_subtotal")) or 0.0
        amount = _to_float(row.get("line_tax_amount")) or 0.0
        if subtotal or amount:
            rates[percent] = row["line_tax_percent"]
    if len(rates) == 1:
        return next(iter(rates.values()))
    return None


def _apply_tax_to_lines(output: dict[str, Any]) -> None:
    """Apply the tax-summary rate onto product lines (issue #535).

    Two strategies, both non-destructive (existing line values are kept):

    1. **By code** — when product ``lines`` carry a ``line_tax_code`` (e.g. a
       receipt's "BTW type" column) and the ``tax_lines`` summary maps that code
       to a ``line_tax_percent``, copy the rate onto each matching line.
    2. **Single rate** — when the summary has exactly one active (non-zero) tax
       rate, apply it to every line that still lacks a rate. Mixed-rate summaries
       are left untouched (ambiguous; use the ``tax_lines`` global adjustment).

    In both cases ``line_tax_amount`` is computed from ``price_subtotal`` when
    available.

    Args:
        output (dict[str, Any]): The extracted-fields dictionary, modified in place.
    """
    tax_lines = output.get("tax_lines")
    lines = output.get("lines")
    if not isinstance(tax_lines, list) or not isinstance(lines, list):
        return

    rate_by_code = {
        str(row["line_tax_code"]): row["line_tax_percent"]
        for row in tax_lines
        if isinstance(row, dict)
        and "line_tax_code" in row
        and "line_tax_percent" in row
    }
    for line in lines:
        if not isinstance(line, dict) or "line_tax_percent" in line:
            continue
        if "line_tax_code" in line:
            percent = rate_by_code.get(str(line["line_tax_code"]))
            if percent is not None:
                _set_line_rate(line, percent)

    single_rate = _single_active_rate(tax_lines)
    if single_rate is None:
        return
    for line in lines:
        if isinstance(line, dict) and "line_tax_percent" not in line:
            _set_line_rate(line, single_rate)


def _compute_line_tax(output: dict[str, Any]) -> None:
    """Fill in a missing ``line_tax_amount`` for ``tax_lines`` rows.

    For each per-rate row in ``tax_lines`` that has ``line_tax_percent`` and
    ``price_subtotal`` but no ``line_tax_amount``, compute it as
    ``round(price_subtotal * line_tax_percent / 100, 2)``. Existing values are
    never overwritten. (Product ``lines`` are left untouched.)

    Args:
        output (dict[str, Any]): The extracted-fields dictionary, modified in place.
    """
    rows = output.get("tax_lines")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        if (
            "line_tax_amount" not in row
            and "line_tax_percent" in row
            and "price_subtotal" in row
        ):
            try:
                percent = float(row["line_tax_percent"])
                subtotal = float(row["price_subtotal"])
            except (TypeError, ValueError):
                continue
            row["line_tax_amount"] = round(subtotal * percent / 100, 2)


def _validate_tax_total(output: dict[str, Any], template_name: str) -> None:
    """Warn if the per-rate tax amounts don't add up to ``amount_tax``.

    Purely advisory (a tolerance-based warning); never raises or alters output.

    Args:
        output (dict[str, Any]): The extracted-fields dictionary.
        template_name (str): Template name, for the log message.
    """
    tax_lines = output.get("tax_lines")
    amount_tax = output.get("amount_tax")
    if not isinstance(tax_lines, list) or not isinstance(amount_tax, int | float):
        return
    total = sum(
        row["line_tax_amount"]
        for row in tax_lines
        if isinstance(row, dict) and isinstance(row.get("line_tax_amount"), int | float)
    )
    if total and abs(total - amount_tax) > 0.02:
        logger.warning(
            "tax_lines total (%.2f) does not match amount_tax (%.2f) in %s",
            total,
            amount_tax,
            template_name,
        )


def _validate_fields(self: InvoiceTemplate, output: dict[str, Any]) -> None:
    """Validate output field names against the canonical schema.

    Quiet by default: only warns when an unrecognized field looks like a typo of
    a canonical name. With the template option ``strict_fields: true`` it raises
    on any unrecognized field (except those listed in ``options.extra_fields``).

    Args:
        self (InvoiceTemplate): The template instance.
        output (dict[str, Any]): The extracted-fields dictionary.

    Raises:
        ValueError: If ``strict_fields`` is set and unrecognized fields remain.
    """
    extra = self.options.get("extra_fields", []) or []
    issues = schema.validate_output(output, extra_fields=extra)
    if not issues:
        return
    if self.options.get("strict_fields", False):
        names = ", ".join(name for name, _ in issues)
        raise ValueError(
            f"Unrecognized fields in template {self['template_name']}: {names}"
        )
    for name, suggestion in issues:
        if suggestion:
            logger.warning(
                "Field '%s' is not a recognized field; did you mean '%s'? (%s)",
                name,
                suggestion,
                self["template_name"],
            )
        else:
            logger.debug(
                "Field '%s' is not a canonical field (%s)", name, self["template_name"]
            )


def _check_required_fields(
    self: InvoiceTemplate, output: dict[str, Any]
) -> dict[str, Any]:
    """Check if all required fields are present in the output."""
    if "required_fields" not in self.keys():
        required_fields = ["date", "amount", "invoice_number", "issuer"]
    else:
        required_fields = []
        for v in self["required_fields"]:
            required_fields.append(v)

    if set(required_fields).issubset(output.keys()):
        output["desc"] = "Invoice from %s" % (self["issuer"])
        # pformat is expensive; only build it when debug logging is actually on.
        if logger.isEnabledFor(DEBUG):
            logger.debug("\n %s", pformat(output, indent=2))
        return output
    fields = list(set(output.keys()))
    logger.error(
        "Unable to match all required fields. "
        f"The required fields are: {required_fields}. "
        f"Output contains the following fields: {fields}."
    )
    missing = set(required_fields) - set(fields)
    # RequiredFieldsMissingError subclasses ValueError, so the cascade's existing
    # `except ValueError` retry handling is unaffected.
    raise RequiredFieldsMissingError(missing, self.get("template_name"))

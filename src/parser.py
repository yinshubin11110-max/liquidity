from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Optional, Tuple

from dateutil.parser import parse as dateparse

PL_MONTHS = {
    "stycznia": "01",
    "lutego": "02",
    "marca": "03",
    "kwietnia": "04",
    "maja": "05",
    "czerwca": "06",
    "lipca": "07",
    "sierpnia": "08",
    "wrzesnia": "09",
    "września": "09",
    "pazdziernika": "10",
    "października": "10",
    "listopada": "11",
    "grudnia": "12",
}

DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b")
DATE_POLISH_RE = re.compile(
    r"\b(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})\b", re.IGNORECASE
)

JOIN_PATTERNS = (
    r"z\s+dniem\s+(?P<date>[^,;\n]+)\s+.*?do\s+programu\s+wspierania\s+plynnosci\s+przystapil[aoey]?",
    r"z\s+dniem\s+(?P<date>[^,;\n]+)\s+.*?przystapil[aoey]?\s+.*?do\s+programu\s+wspierania\s+plynnosci",
    r"z\s+dnia\s+(?P<date>[^,;\n]+)\s+.*?przystapil[aoey]?\s+.*?do\s+programu\s+wspierania\s+plynnosci",
)

EFFECTIVE_PATTERNS = (
    r"od\s+sesji\s+w\s+dniu\s+(?P<date>[^,;\n]+)",
    r"zmiana\s+systemu\s+notowan\w*\s+nastapi[^.]*?\s+w\s+dniu\s+(?P<date>[^,;\n]+)",
)

DIACRITIC_MAP = {
    ord("ą"): "a",
    ord("ć"): "c",
    ord("ę"): "e",
    ord("ł"): "l",
    ord("ń"): "n",
    ord("ó"): "o",
    ord("ś"): "s",
    ord("ź"): "z",
    ord("ż"): "z",
    ord("Ą"): "a",
    ord("Ć"): "c",
    ord("Ę"): "e",
    ord("Ł"): "l",
    ord("Ń"): "n",
    ord("Ó"): "o",
    ord("Ś"): "s",
    ord("Ź"): "z",
    ord("Ż"): "z",
}


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    translated = normalized.translate(DIACRITIC_MAP)
    return translated.lower()


def parse_polish_date(raw_date: str) -> Optional[str]:
    """
    Convert Polish textual or numeric date expressions to ISO format (YYYY-MM-DD).

    Supports forms such as "11 lipca 2024 r." or "16.07.2024".
    """
    if not raw_date:
        return None
    cleaned = (
        _normalize(raw_date)
        .replace(" r.", " ")
        .replace(" roku", " ")
        .replace(",", " ")
        .strip()
    )
    cleaned = re.sub(r"\s+", " ", cleaned)

    match = DATE_NUMERIC_RE.search(cleaned)
    if match:
        day, month, year = match.groups()
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
        except ValueError:
            return None

    match = DATE_POLISH_RE.search(cleaned)
    if match:
        day_raw, month_raw, year_raw = match.groups()
        month_key = _normalize(month_raw.lower())
        month = PL_MONTHS.get(month_key)
        if month:
            try:
                return datetime(int(year_raw), int(month), int(day_raw)).strftime(
                    "%Y-%m-%d"
                )
            except ValueError:
                return None

    try:
        return dateparse(cleaned, dayfirst=True).date().isoformat()
    except (ValueError, TypeError):
        return None


def extract_dates(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract join_date and effective_date from GPW announcement body text.

    Returns a tuple of ISO date strings (YYYY-MM-DD). Missing values are None.
    """
    if not text:
        return None, None

    join_date = _scan_patterns(text, JOIN_PATTERNS)
    effective_date = _scan_patterns(text, EFFECTIVE_PATTERNS)
    return join_date, effective_date


def _scan_patterns(text: str, patterns: Tuple[str, ...]) -> Optional[str]:
    normalized = _normalize(text)
    for pattern in patterns:
        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return parse_polish_date(match.group("date"))
    return None


def infer_announcement_date_from_text(text: str) -> Optional[str]:
    """Return the first date-like token in text as ISO date, if any."""
    if not text:
        return None
    normalized = _normalize(text)
    for regex in (DATE_NUMERIC_RE, DATE_POLISH_RE):
        match = regex.search(normalized)
        if match:
            return parse_polish_date(match.group(0))
    return None


__all__ = ["extract_dates", "parse_polish_date", "infer_announcement_date_from_text"]

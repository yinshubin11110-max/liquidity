from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import requests


TICKER_KEYWORDS = (
    "ticker",
    "symbol",
    "code",
    "ticker symbol",
    "交易代码",
    "oznaczenie",
    "ticker / symbol",
    "ticker/ symbol",
)

COMPANY_KEYWORDS = (
    "company",
    "name",
    "issuer",
    "emittent",
    "emitent",
    "spółka",
    "spolka",
    "issuer name",
)

INDEX_URLS: Dict[str, List[str]] = {
    "wig20": [
        "https://en.wikipedia.org/wiki/WIG20",
        "https://pl.wikipedia.org/wiki/WIG20",
    ],
    "mwig40": [
        "https://en.wikipedia.org/wiki/mWIG40",
        "https://pl.wikipedia.org/wiki/mWIG40",
    ],
    "swig80": [
        "https://en.wikipedia.org/wiki/sWIG80",
        "https://pl.wikipedia.org/wiki/sWIG80",
    ],
}


FOOTNOTE_RE = re.compile(r"\[\d+\]")
PAREN_RE = re.compile(r"\s*\(.*?\)")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Entry:
    company: str
    ticker: str


def clean_text(value: str) -> str:
    value = FOOTNOTE_RE.sub("", value or "")
    value = PAREN_RE.sub("", value)
    value = value.replace("\xa0", " ")
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip()


def find_column(columns: Iterable[str], keywords: Iterable[str]) -> str | None:
    for col in columns:
        col_lower = col.lower()
        for keyword in keywords:
            if keyword in col_lower:
                return col
    return None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
}


def extract_entries_from_url(url: str) -> List[Entry]:
    logging.info("Fetching constituents from %s", url)
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    tables = pd.read_html(response.text, header=0)
    entries: List[Entry] = []
    for table in tables:
        columns = [str(col) for col in table.columns]
        ticker_col = find_column(columns, TICKER_KEYWORDS)
        company_col = find_column(columns, COMPANY_KEYWORDS)
        if not ticker_col or not company_col:
            continue
        df = table[[company_col, ticker_col]].dropna()
        for _, row in df.iterrows():
            company = clean_text(str(row[company_col]))
            ticker = clean_text(str(row[ticker_col])).upper()
            if not company or not ticker:
                continue
            entries.append(Entry(company=company, ticker=ticker))
    if entries:
        return entries
    logging.warning("No usable table found at %s", url)
    return []


def fetch_index(index: str) -> List[Entry]:
    index_lower = index.lower()
    urls = INDEX_URLS.get(index_lower)
    if not urls:
        raise ValueError(f"Unsupported index '{index}'.")
    for url in urls:
        try:
            entries = extract_entries_from_url(url)
            if entries:
                return entries
        except Exception as exc:  # pragma: no cover - network errors
            logging.warning("Failed to parse %s: %s", url, exc)
    logging.error("No data extracted for index %s.", index)
    return []


def merge_entries(entries_list: Iterable[List[Entry]]) -> pd.DataFrame:
    rows = [
        {"company": entry.company, "ticker": entry.ticker}
        for entries in entries_list
        for entry in entries
    ]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["company", "ticker", "isin"])
    df["company"] = df["company"].astype(str).str.strip()
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df = df[df["company"] != ""]
    df = df[df["ticker"] != ""]
    df = df.drop_duplicates(subset=["company", "ticker"]).sort_values(
        by=["company", "ticker"]
    )
    df["isin"] = ""
    return df[["company", "ticker", "isin"]]


def write_targets(df: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False, encoding="utf-8")
    logging.info("Wrote %s rows to %s", len(df), output)


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build PWP scraping universe from GPW indices."
    )
    parser.add_argument(
        "--indices",
        default="wig20,mwig40,swig80",
        help="Comma-separated list of indices to fetch (default: wig20,mwig40,swig80).",
    )
    parser.add_argument(
        "--out",
        default="data/targets.csv",
        help="Output CSV path (default: data/targets.csv).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v or -vv).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    indices = [item.strip() for item in args.indices.split(",") if item.strip()]
    if not indices:
        logging.error("No indices provided.")
        return 1
    entries_per_index = [fetch_index(index) for index in indices]
    df = merge_entries(entries_per_index)
    if df.empty:
        logging.error("No entries extracted. Nothing written.")
        return 1
    write_targets(df, Path(args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

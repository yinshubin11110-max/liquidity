from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

try:  # pragma: no cover - optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None

if __package__ is None:  # pragma: no cover - script support
    sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.fetcher import fetch_html, reset_connections  # type: ignore[wrong-import-position]
from src.parser import (
    extract_dates,
    infer_announcement_date_from_text,
    parse_polish_date,
)

BASE_URL = "https://www.gpw.pl"
SEARCH_URL_TEMPLATE = f"{BASE_URL}/komunikaty-i-uchwaly-gpw?query={{query}}"

PAP_BASE_URL = "https://biznes.pap.pl"
PAP_SEARCH_URL_TEMPLATE = (
    f"{PAP_BASE_URL}/pl/news/search?query={{query}}&page=1&sort=1"
)

KEY_PHRASE = "Program Wspierania Płynności"
PWP_DISCOVERY_QUERIES = [
    "Program Wspierania Płynności",
    "Program Wspierania Plynnosci",
]


@dataclass
class Target:
    company: str
    ticker: str
    isin: str


@dataclass
class SearchResult:
    url: str
    title: str
    source: str
    fixture_hint: Optional[str] = None
    raw_date: Optional[str] = None
    search_snippet: Optional[str] = None


@dataclass
class ScrapeRecord:
    company: str
    ticker: str
    isin: str
    announcement_url: str
    announcement_date: Optional[str]
    join_date: Optional[str]
    effective_date: Optional[str]
    snippet: str
    source: str


def load_targets(csv_path: str) -> List[Target]:
    targets: List[Target] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"company", "ticker", "isin"}
        if reader.fieldnames is None or required - {
            field.lower() for field in reader.fieldnames
        }:
            raise ValueError(
                "Input CSV must include company,ticker,isin columns."
            )
        for row in reader:
            company = (row.get("company") or "").strip()
            ticker = (row.get("ticker") or "").strip()
            isin = (row.get("isin") or "").strip()
            if not company:
                continue
            targets.append(Target(company=company, ticker=ticker, isin=isin))
    return targets


def build_queries(target: Target) -> List[str]:
    queries: List[str] = []
    if target.company:
        queries.append(target.company)
    if target.company and target.isin:
        queries.append(f"{target.company}|{target.isin}")
    seen: Set[str] = set()
    ordered: List[str] = []
    for query in queries:
        key = query.strip()
        if key and key not in seen:
            ordered.append(key)
            seen.add(key)
    return ordered


def parse_gpw_search(html: str) -> List[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    hits: List[SearchResult] = []
    containers = soup.select(
        "div.search-result, article, li.search-result, div.gpw__search-result"
    )
    if not containers:
        containers = soup.select("a[href]")
    for container in containers:
        anchor = container if container.name == "a" else container.find("a")
        if not anchor or not anchor.get("href"):
            continue
        title = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "")
        text_blob = f"{title} {href} {container.get_text(' ', strip=True)}"
        if KEY_PHRASE.lower() not in text_blob.lower():
            continue
        url = urljoin(BASE_URL, href)
        snippet_node = (
            container.find(
                class_=lambda attr: bool(attr)
                and any(
                    token in attr.lower()
                    for token in ("description", "snippet", "summary")
                )
            )
            if container is not anchor
            else None
        )
        date_node = (
            container.find(
                class_=lambda attr: bool(attr)
                and "date" in attr.lower()
            )
            if container is not anchor
            else None
        )
        raw_date = date_node.get_text(strip=True) if date_node else None
        snippet = (
            snippet_node.get_text(" ", strip=True)
            if snippet_node
            else container.get_text(" ", strip=True)
        )
        hits.append(
            SearchResult(
                url=url,
                title=title,
                source="GPW",
                fixture_hint=anchor.get("data-fixture"),
                raw_date=raw_date,
                search_snippet=snippet,
            )
        )
    return hits


def parse_pap_search(html: str) -> List[SearchResult]:
    soup = BeautifulSoup(html, "lxml")
    hits: List[SearchResult] = []
    articles = soup.select("article, div.news-item, li.news__item")
    if not articles:
        articles = soup.select("a[href]")
    for node in articles:
        anchor = node if node.name == "a" else node.find("a", href=True)
        if not anchor or not anchor.get("href"):
            continue
        href = anchor["href"]
        title = anchor.get_text(" ", strip=True)
        text_blob = f"{title} {href} {node.get_text(' ', strip=True)}"
        if "program wspierania plynnosci" not in text_blob.lower():
            continue
        if not href.startswith("http"):
            url = urljoin(PAP_BASE_URL, href)
        else:
            url = href
        date_node = None
        if node is not anchor:
            date_node = node.find("time")
            if not date_node:
                date_node = node.find(
                    class_=lambda attr: bool(attr)
                    and "date" in attr.lower()
                )
        raw_date = None
        if date_node:
            raw_date = (
                date_node.get("datetime")
                or date_node.get_text(" ", strip=True)
            )
        snippet = node.get_text(" ", strip=True)
        hits.append(
            SearchResult(
                url=url,
                title=title,
                source="PAP",
                search_snippet=snippet,
            )
        )
    return hits


def search_company(
    target: Target,
    *,
    mode: str,
    fixtures_dir: str,
    use_playwright: bool,
    headless: bool,
) -> List[SearchResult]:
    results: List[SearchResult] = []
    seen_urls: Set[str] = set()
    for query in build_queries(target):
        query_url = SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
        logging.info("Searching GPW for %s with '%s'", target.company, query)
        try:
            html = fetch_html(
                query_url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                use_playwright=use_playwright,
                headless=headless,
            )
        except Exception as exc:
            logging.warning("GPW search failed for '%s': %s", query, exc)
            continue
        for hit in parse_gpw_search(html):
            if hit.url not in seen_urls:
                results.append(hit)
                seen_urls.add(hit.url)
    if results:
        return results

    logging.info("No GPW hits for %s, trying PAP Biznes fallback.", target.company)
    for query in build_queries(target):
        query_url = PAP_SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
        try:
            html = fetch_html(
                query_url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                use_playwright=use_playwright,
                headless=headless,
                fallback="pap_search.html" if mode == "offline" else None,
            )
        except Exception as exc:
            logging.warning("PAP search failed for '%s': %s", query, exc)
            continue
        for hit in parse_pap_search(html):
            if hit.url not in seen_urls:
                results.append(hit)
                seen_urls.add(hit.url)
    return results


def discover_pwp_announcements(
    *,
    mode: str,
    fixtures_dir: str,
    use_playwright: bool,
    headless: bool,
) -> List[SearchResult]:
    seen_urls: Set[str] = set()
    aggregated: List[SearchResult] = []
    for query in PWP_DISCOVERY_QUERIES:
        query_url = SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
        try:
            html = fetch_html(
                query_url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                use_playwright=use_playwright,
                headless=headless,
            )
            for result in parse_gpw_search(html):
                if result.url not in seen_urls:
                    aggregated.append(result)
                    seen_urls.add(result.url)
        except Exception as exc:
            logging.warning("GPW discovery failed for '%s': %s", query, exc)
        pap_url = PAP_SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
        try:
            html = fetch_html(
                pap_url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                use_playwright=use_playwright,
                headless=headless,
                fallback="pap_search.html" if mode == "offline" else None,
            )
            for result in parse_pap_search(html):
                if result.url not in seen_urls:
                    aggregated.append(result)
                    seen_urls.add(result.url)
        except Exception as exc:
            logging.debug("PAP discovery failed for '%s': %s", query, exc)
    return aggregated


def infer_company_name(result: SearchResult, soup: BeautifulSoup) -> str:
    candidates: List[str] = []
    if result.title:
        candidates.append(result.title)
    header = soup.find("h1")
    if header:
        candidates.append(header.get_text(" ", strip=True))
    title_tag = soup.find("title")
    if title_tag:
        candidates.append(title_tag.get_text(" ", strip=True))
    for candidate in candidates:
        if not candidate:
            continue
        if " - " in candidate:
            name = candidate.split(" - ", 1)[0].strip()
        else:
            name = candidate.strip()
        if name:
            return name
    return result.title or "Nieznana spółka"


def extract_body_text(soup: BeautifulSoup) -> str:
    selectors = (
        "article",
        "main",
        "div.komunikat",
        "div.news__content",
        "div.content",
        "div.article",
        "section",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node.get_text(" ", strip=True)
    if soup.body:
        return soup.body.get_text(" ", strip=True)
    return soup.get_text(" ", strip=True)


def extract_announcement_date(soup: BeautifulSoup, text: str, raw_date: Optional[str]) -> Optional[str]:
    meta_selectors = (
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "publish-date"}),
        ("meta", {"itemprop": "datePublished"}),
    )
    for tag, attrs in meta_selectors:
        node = soup.find(tag, attrs=attrs)
        if node and (value := node.get("content")):
            parsed = parse_polish_date(value)
            if parsed:
                return parsed
    time_tag = soup.find("time")
    if time_tag:
        candidate = time_tag.get("datetime") or time_tag.get_text(strip=True)
        parsed = parse_polish_date(candidate)
        if parsed:
            return parsed
    if raw_date:
        parsed = parse_polish_date(raw_date)
        if parsed:
            return parsed
    return infer_announcement_date_from_text(text)


def build_snippet(body_text: str, search_snippet: Optional[str]) -> str:
    if not body_text and search_snippet:
        return search_snippet[:240]
    if not body_text:
        return ""
    clean = " ".join(body_text.split())
    lowered = clean.lower()
    key_tokens = (
        "program wspierania plynnosci",
        "zmiana systemu notowan",
    )
    for token in key_tokens:
        idx = lowered.find(token)
        if idx != -1:
            start = max(0, idx - 120)
            end = min(len(clean), idx + len(token) + 120)
            return clean[start:end]
    if search_snippet:
        return search_snippet[:240]
    return clean[:240]


def scrape_target(
    target: Target,
    *,
    mode: str,
    fixtures_dir: str,
    use_playwright: bool,
    headless: bool,
) -> List[ScrapeRecord]:
    results = search_company(
        target,
        mode=mode,
        fixtures_dir=fixtures_dir,
        use_playwright=use_playwright,
        headless=headless,
    )
    unique_keys: Set[Tuple[str, str, str, str]] = set()
    records: List[ScrapeRecord] = []
    for result in results:
        try:
            html = fetch_html(
                result.url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                fallback=result.fixture_hint,
                use_playwright=use_playwright,
                headless=headless,
            )
        except Exception as exc:
            logging.warning("Failed to fetch %s: %s", result.url, exc)
            continue
        soup = BeautifulSoup(html, "lxml")
        body_text = extract_body_text(soup)
        join_date, effective_date = extract_dates(body_text)
        announcement_date = extract_announcement_date(
            soup, body_text, result.raw_date
        )
        snippet = build_snippet(body_text, result.search_snippet)
        key = (
            target.company,
            result.url,
            join_date or "",
            effective_date or "",
        )
        if key in unique_keys:
            continue
        unique_keys.add(key)
        records.append(
            ScrapeRecord(
                company=target.company,
                ticker=target.ticker,
                isin=target.isin,
                announcement_url=result.url,
                announcement_date=announcement_date,
                join_date=join_date,
                effective_date=effective_date,
                snippet=snippet,
                source=result.source,
            )
        )
    return records


def scrape_discovered_results(
    results: Sequence[SearchResult],
    *,
    mode: str,
    fixtures_dir: str,
    use_playwright: bool,
    headless: bool,
) -> List[ScrapeRecord]:
    records: List[ScrapeRecord] = []
    seen_keys: Set[Tuple[str, str]] = set()
    for result in results:
        try:
            html = fetch_html(
                result.url,
                mode=mode,
                fixtures_dir=fixtures_dir,
                fallback=result.fixture_hint,
                use_playwright=use_playwright,
                headless=headless,
            )
        except Exception as exc:
            logging.warning("Failed to fetch %s: %s", result.url, exc)
            continue
        soup = BeautifulSoup(html, "lxml")
        body_text = extract_body_text(soup)
        join_date, effective_date = extract_dates(body_text)
        announcement_date = extract_announcement_date(
            soup, body_text, result.raw_date
        )
        snippet = build_snippet(body_text, result.search_snippet)
        company_name = infer_company_name(result, soup)
        key = (company_name, result.url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        records.append(
            ScrapeRecord(
                company=company_name,
                ticker="",
                isin="",
                announcement_url=result.url,
                announcement_date=announcement_date,
                join_date=join_date,
                effective_date=effective_date,
                snippet=snippet,
                source=result.source,
            )
        )
    return records


def scrape_targets(
    targets: Sequence[Target],
    *,
    mode: str,
    fixtures_dir: str,
    use_playwright: bool,
    headless: bool,
) -> List[ScrapeRecord]:
    iterator: Iterable[Target]
    if tqdm and len(targets) > 1:
        iterator = tqdm(targets, desc="Targets", unit="company")
    else:
        iterator = targets
    collected: List[ScrapeRecord] = []
    for target in iterator:
        logging.info("Processing %s (%s)", target.company, target.ticker)
        collected.extend(
            scrape_target(
                target,
                mode=mode,
                fixtures_dir=fixtures_dir,
                use_playwright=use_playwright,
                headless=headless,
            )
        )
    return collected


def write_results(
    main_path: str,
    windows_path: str,
    records: Iterable[ScrapeRecord],
) -> None:
    Path(main_path).parent.mkdir(parents=True, exist_ok=True)
    records_list = list(records)

    main_fieldnames = [
        "company",
        "ticker",
        "isin",
        "announcement_url",
        "announcement_date",
        "join_date",
        "effective_date",
        "snippet",
        "source",
    ]
    with open(main_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=main_fieldnames)
        writer.writeheader()
        for record in records_list:
            writer.writerow(
                {
                    "company": record.company,
                    "ticker": record.ticker,
                    "isin": record.isin,
                    "announcement_url": record.announcement_url,
                    "announcement_date": record.announcement_date or "",
                    "join_date": record.join_date or "",
                    "effective_date": record.effective_date or "",
                    "snippet": record.snippet,
                    "source": record.source,
                }
            )

    windows_fieldnames = [
        "company",
        "ticker",
        "isin",
        "announcement_url",
        "source",
        "t0_announcement",
        "t0_effective",
    ]
    with open(windows_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=windows_fieldnames)
        writer.writeheader()
        for record in records_list:
            writer.writerow(
                {
                    "company": record.company,
                    "ticker": record.ticker,
                    "isin": record.isin,
                    "announcement_url": record.announcement_url,
                    "source": record.source,
                    "t0_announcement": record.announcement_date or "",
                    "t0_effective": record.effective_date or "",
                }
            )


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level, format="%(asctime)s [%(levelname)s] %(message)s"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape GPW PWP announcements.")
    parser.add_argument(
        "--mode", choices=("offline", "online"), default="offline"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Discover PWP announcements automatically without targets.csv.",
    )
    parser.add_argument(
        "--targets",
        default=None,
        help="Path to CSV with company,ticker,isin columns.",
    )
    parser.add_argument(
        "--out",
        default="out/pwp_events.csv",
        help="Main output CSV path.",
    )
    parser.add_argument(
        "--windows-out",
        default="out/pwp_events_windows.csv",
        help="Event window CSV path (default: out/pwp_events_windows.csv).",
    )
    parser.add_argument(
        "--excel-out",
        default=None,
        help="Path to .xlsx; writes events & windows sheets",
    )
    parser.add_argument(
        "--fixtures",
        default="fixtures",
        help="Directory for offline HTML fixtures.",
    )
    parser.add_argument(
        "--no-playwright",
        action="store_true",
        help="Disable Playwright usage in online mode.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Playwright in headed mode (online only).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v, -vv).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)
    try:
        if args.auto:
            targets = []
        else:
            if not args.targets:
                logging.error("--targets is required unless --auto is set.")
                return 1
            targets = load_targets(args.targets)
            if not targets:
                logging.error("No valid targets found in %s", args.targets)
                return 1
    except Exception as exc:
        logging.error("Failed to load targets: %s", exc)
        return 1
    use_playwright = not args.no_playwright
    try:
        if args.auto:
            logging.info("Auto-discovering PWP announcements.")
            discovered = discover_pwp_announcements(
                mode=args.mode,
                fixtures_dir=args.fixtures,
                use_playwright=use_playwright,
                headless=not args.headed,
            )
            records = scrape_discovered_results(
                discovered,
                mode=args.mode,
                fixtures_dir=args.fixtures,
                use_playwright=use_playwright,
                headless=not args.headed,
            )
        else:
            records = scrape_targets(
                targets,
                mode=args.mode,
                fixtures_dir=args.fixtures,
                use_playwright=use_playwright,
                headless=not args.headed,
            )
        write_results(args.out, args.windows_out, records)
        if args.excel_out:
            import os

            df_events = pd.read_csv(args.out)
            win_path = args.windows_out if hasattr(args, "windows_out") else None
            if win_path and os.path.exists(win_path):
                df_win = pd.read_csv(win_path)
            else:
                df_win = pd.DataFrame(
                    columns=[
                        "company",
                        "ticker",
                        "isin",
                        "announcement_url",
                        "t0_announcement",
                        "t0_effective",
                    ]
                )
            with pd.ExcelWriter(args.excel_out) as writer:
                df_events.to_excel(writer, sheet_name="events", index=False)
                df_win.to_excel(writer, sheet_name="windows", index=False)
            print(f"Wrote Excel to {args.excel_out}")
    except KeyboardInterrupt:  # pragma: no cover
        logging.error("Interrupted by user.")
        return 1
    except Exception as exc:
        logging.error("Scraping failed: %s", exc)
        return 1
    finally:
        reset_connections()
    logging.info(
        "Wrote %s records to %s and %s",
        len(records),
        args.out,
        args.windows_out,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

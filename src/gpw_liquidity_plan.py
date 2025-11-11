"""
Scrape GPW liquidity program announcements and export company join dates to Excel.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.gpw.pl/"
AJAX_ENDPOINT = urljoin(BASE_URL, "ajaxindex.php")
CATEGORY_ID = "44"
PAGE_LIMIT = 10

# Normalized (ASCII, lowercase) Polish month names mapped to month numbers.
MONTH_LOOKUP = {
    "stycznia": 1,
    "lutego": 2,
    "marca": 3,
    "kwietnia": 4,
    "maja": 5,
    "czerwca": 6,
    "lipca": 7,
    "sierpnia": 8,
    "wrzesnia": 9,
    "pazdziernika": 10,
    "listopada": 11,
    "grudnia": 12,
}

# Matches phrases such as "z dniem 1 sierpnia 2025 r." or "w dniu 25 kwietnia 2023 r."
EFFECTIVE_DATE_PATTERN = re.compile(
    r"(?:z\s+dniem|w\s+dniu|od\s+dnia)\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})", re.IGNORECASE
)


@dataclass
class Announcement:
    company: str
    announcement_date: date
    effective_date: date
    title: str
    detail_url: str
    cmn_id: Optional[str]


def normalize_text(value: str) -> str:
    """Lowercase string stripped of diacritics for pattern matching."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_diacritics = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_diacritics.lower()


def clean_company_name(raw: str) -> str:
    """Trim whitespace and trailing punctuation from company names."""
    cleaned = " ".join(raw.replace("\xa0", " ").split())
    return cleaned.strip(",.; ")


def parse_effective_date(source_text: str) -> Optional[date]:
    """Extract the effective date from a paragraph describing programme entry."""
    normalized = normalize_text(source_text)
    match = EFFECTIVE_DATE_PATTERN.search(normalized)
    if not match:
        return None

    day_str, month_name, year_str = match.groups()
    month = MONTH_LOOKUP.get(month_name)
    if month is None:
        return None

    return date(int(year_str), month, int(day_str))


def extract_companies(join_paragraph: Tag, announcement_title: str) -> List[str]:
    """Determine which companies joined the programme within the announcement."""
    paragraph_text = " ".join(join_paragraph.stripped_strings)
    normalized = normalize_text(paragraph_text)

    companies: List[str] = []

    if "spolki:" in normalized:
        # Multi-company announcement: expect a bullet list right after the paragraph.
        list_block = join_paragraph.find_next("ul")
        if list_block:
            for li in list_block.find_all("li"):
                name = clean_company_name(li.get_text(" ", strip=True))
                if name:
                    companies.append(name)
        return companies

    # Attempt to capture the company name from the same paragraph.
    single_match = re.search(
        r"sp[óo]łk[ai]\s+([A-Z0-9][A-Z0-9\s\.\-&]*?)(?:\s*(?:,|\.|;|$))",
        paragraph_text,
        flags=re.UNICODE,
    )
    if single_match:
        captured = clean_company_name(single_match.group(1))
        if captured:
            companies.append(captured)
            return companies

    # Frequently the next paragraph contains the company name in bold.
    next_node = join_paragraph.next_sibling
    while next_node and (not isinstance(next_node, Tag) or not next_node.get_text(strip=True)):
        next_node = getattr(next_node, "next_sibling", None)

    if isinstance(next_node, Tag) and next_node.name == "p":
        strong = next_node.find("strong")
        if strong:
            captured = clean_company_name(strong.get_text(" ", strip=True))
            if captured:
                companies.append(captured)
                return companies

    fallback = clean_company_name(announcement_title.split("(")[0])
    if fallback:
        companies.append(fallback)
    return companies


def parse_detail_page(html: str, announcement_title: str) -> Optional[tuple[date, List[str]]]:
    """Extract effective date and company list from a detailed announcement page."""
    soup = BeautifulSoup(html, "html.parser")
    main_column = soup.select_one("div.col-md-8.col-lg-9.margin-bottom-20")
    if not main_column:
        main_column = soup.select_one("div.col-md-8")
    if not main_column:
        return None

    for paragraph in main_column.find_all("p"):
        paragraph_text = " ".join(paragraph.stripped_strings)
        normalized = normalize_text(paragraph_text)
        if "do programu wspierania plynnosci" in normalized and "przystap" in normalized:
            effective = parse_effective_date(paragraph_text)
            companies = extract_companies(paragraph, announcement_title)
            if not companies:
                return None
            return effective, companies
    return None


def parse_cmn_id(url: str) -> Optional[str]:
    """Extract cmn_id parameter from detail URL if present."""
    query_params = parse_qs(urlparse(url).query)
    values = query_params.get("cmn_id")
    return values[0] if values else None


def fetch_announcements(session: requests.Session) -> Iterable[Announcement]:
    """Iterate over all programme announcements and yield membership entries."""
    offset = 0

    while True:
        payload = {
            "action": "CMNews",
            "start": "ajaxList",
            "page_iterator_active": "true",
            "page": "komunikaty-i-uchwaly-gpw",
            "target": "main_01",
            "cmng_id": CATEGORY_ID,
            "limit": str(PAGE_LIMIT),
            "offset": str(offset),
        }
        response = session.post(AJAX_ENDPOINT, data=payload)
        response.raise_for_status()

        snippet_soup = BeautifulSoup(response.text, "html.parser")
        list_items = [
            item
            for item in snippet_soup.find_all("li")
            if item.find("span", class_="date")
        ]

        if not list_items:
            break

        for item in list_items:
            date_label = item.find("span", class_="date")
            title_link = item.find("a")
            if not date_label or not title_link:
                continue

            category_and_date = date_label.get_text(" ", strip=True)
            try:
                publication_date = datetime.strptime(
                    category_and_date.split("|")[-1].strip(), "%d-%m-%Y"
                ).date()
            except ValueError:
                continue

            detail_url = urljoin(BASE_URL, title_link["href"])
            title_text = title_link.get_text(strip=True)

            detail_response = session.get(detail_url)
            detail_response.raise_for_status()
            parsed = parse_detail_page(detail_response.text, title_text)
            if not parsed:
                continue

            effective_date, companies = parsed
            if not effective_date:
                # Fall back to publication date if effective date is missing.
                effective_date = publication_date

            cmn_id = parse_cmn_id(detail_url)
            for company in companies:
                yield Announcement(
                    company=company,
                    announcement_date=publication_date,
                    effective_date=effective_date,
                    title=title_text,
                    detail_url=detail_url,
                    cmn_id=cmn_id,
                )

        if len(list_items) < PAGE_LIMIT:
            break

        offset += PAGE_LIMIT


def export_to_excel(records: Iterable[Announcement], destination: Path) -> None:
    """Write gathered announcements to an Excel workbook."""
    rows = [
        {
            "Company": record.company,
            "Announcement Date": record.announcement_date,
            "Effective Date": record.effective_date,
            "Announcement Title": record.title,
            "Detail URL": record.detail_url,
            "cmn_id": record.cmn_id,
        }
        for record in records
    ]

    if not rows:
        raise RuntimeError("No liquidity programme join announcements were found.")

    dataframe = pd.DataFrame(rows)
    dataframe.sort_values(
        ["Announcement Date", "Company"], inplace=True, ignore_index=True
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_excel(destination, index=False)


def main() -> None:
    session = requests.Session()
    announcements = list(fetch_announcements(session))
    output_path = Path("out") / "gpw_liquidity_program_joinings.xlsx"
    export_to_excel(announcements, output_path)
    print(f"Saved {len(announcements)} records to {output_path}")


if __name__ == "__main__":
    main()

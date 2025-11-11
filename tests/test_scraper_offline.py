from src.fetcher import fetch_html, reset_connections
from src.parser import extract_dates
from src.scraper import (
    Target,
    discover_pwp_announcements,
    scrape_discovered_results,
    scrape_targets,
    search_company,
)


def test_search_company_offline_returns_fixture_links():
    target = Target(company="KRAKCHEMIA", ticker="KRC", isin="PLKRKCH00019")
    results = search_company(
        target,
        mode="offline",
        fixtures_dir="fixtures",
        use_playwright=False,
        headless=True,
    )
    assert results, "should find at least one announcement"
    assert results[0].source == "GPW"
    html = fetch_html(
        results[0].url,
        mode="offline",
        fixtures_dir="fixtures",
        fallback=results[0].fixture_hint,
    )
    from bs4 import BeautifulSoup  # local import for test speed

    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    join_date, effective_date = extract_dates(text)
    assert join_date == "2024-07-11"
    assert effective_date == "2024-07-16"
    reset_connections()


def test_scrape_targets_offline_pipeline():
    targets = [
        Target(company="KRAKCHEMIA", ticker="KRC", isin="PLKRKCH00019"),
        Target(company="PROTEKTOR", ticker="PRT", isin="PLPROTK00014"),
    ]
    records = scrape_targets(
        targets,
        mode="offline",
        fixtures_dir="fixtures",
        use_playwright=False,
        headless=True,
    )
    reset_connections()
    by_company = {record.company: record for record in records}
    assert "KRAKCHEMIA" in by_company
    assert by_company["KRAKCHEMIA"].join_date == "2024-07-11"
    assert "programu wspierania" in by_company["KRAKCHEMIA"].snippet.lower()
    assert by_company["KRAKCHEMIA"].source == "GPW"
    assert "PROTEKTOR" in by_company
    assert by_company["PROTEKTOR"].effective_date == "2025-08-06"


def test_auto_discovery_offline():
    discovered = discover_pwp_announcements(
        mode="offline",
        fixtures_dir="fixtures",
        use_playwright=False,
        headless=True,
    )
    assert discovered, "auto discovery should return results"
    records = scrape_discovered_results(
        discovered,
        mode="offline",
        fixtures_dir="fixtures",
        use_playwright=False,
        headless=True,
    )
    reset_connections()
    companies = {record.company for record in records}
    assert "Krakchemia S.A." in companies or "Krakchemia" in " ".join(companies)
    assert any(record.join_date == "2024-07-11" for record in records)

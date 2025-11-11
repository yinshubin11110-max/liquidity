# GPW PWP Announcement Scraper

Scrapes Warsaw Stock Exchange (GPW) announcements that mention the **Program Wspierania Płynności (PWP)**. It parses join/effective dates, supports offline fixtures for testing, and can auto-discover companies directly from GPW/PAP search results.

## Layout

```
requirements.txt   # dependencies
Makefile/make.cmd  # install/test/offline/online shortcuts
src/
  parser.py        # text parsing -> join/effective/announcement dates
  fetcher.py       # offline fixtures + online HTTP (requests/Playwright)
  scraper.py       # CLI orchestrator, PAP fallback, Excel export
fixtures/          # HTML fixtures for deterministic tests
tests/             # pytest suite (offline by default)
data/targets.csv   # optional manual company list
out/               # generated CSV/XLSX
```

## Installing & Testing

```bash
make install          # or: make.cmd install
make test             # runs pytest -q -m "not e2e"
```

Playwright will be installed automatically when available; otherwise use:

```bash
pip install playwright
python -m playwright install chromium
```

## Running the scraper

### Manual target list

Edit `data/targets.csv` with columns `company,ticker,isin` (one company per line), then:

```bash
make online           # fetch live data for listed companies
```

Outputs (overwritten each run):
* `out/pwp_events.csv`
* `out/pwp_events_windows.csv`
* `out/pwp_events.xlsx` (sheets: `events`, `windows`)

### Auto-discovery mode

To scan GPW/PAP for all visible PWP announcements without preparing a targets file:

```bash
python src/scraper.py --mode online --auto --out out/pwp_events.csv \
  --windows-out out/pwp_events_windows.csv --excel-out out/pwp_events.xlsx -v
```

The auto mode queries generic PWP keywords, parses search results, and extracts company names from announcement pages. Records that originate from PAP Biznes are marked with `source = PAP`.

### Offline fixtures

Use deterministic fixtures for CI or quick demonstrations:

```bash
make offline
```

This replays sample HTML (Krakchemia / Protektor) and produces the same CSV/XLSX outputs locally.

## Output schema

`out/pwp_events.csv` columns:

| column             | description |
|--------------------|-------------|
| company            | inferred company name |
| ticker / isin      | taken from targets list (manual mode) |
| announcement_url   | canonical page link |
| announcement_date  | publication date (meta tags → body text) |
| join_date          | “z dniem … przystąpiła do Programu Wspierania Płynności” |
| effective_date     | “od sesji w dniu …” (trading-system change) |
| snippet            | short excerpt around the PWP phrase |
| source             | `GPW` or `PAP` |

`out/pwp_events_windows.csv` contains `t0_announcement`/`t0_effective` for direct event-study alignment.

## Development tips

* `tests/test_parser_unit.py` covers textual vs numeric dates plus announcement-date inference.
* `tests/test_scraper_offline.py` checks manual and auto discovery against fixtures.
* New fixtures go under `fixtures/`; update tests if necessary and rerun `make test`.

Enjoy your scraping!

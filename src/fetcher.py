from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

try:  # pragma: no cover - optional dependency
    from playwright.sync_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright,
    )
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None  # type: ignore[assignment]
    PlaywrightError = TimeoutError  # type: ignore[assignment]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment]


USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.6422.112 Safari/537.36",
)

REQUEST_SESSION: Optional[requests.Session] = None
PLAYWRIGHT_CONTEXT = None
PLAYWRIGHT_BROWSER = None
PLAYWRIGHT_DRIVER = None


def _random_delay() -> float:
    return random.uniform(0.8, 2.5)


def _ensure_requests_session() -> requests.Session:
    global REQUEST_SESSION
    if REQUEST_SESSION is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "pl,en-US;q=0.9,en;q=0.8",
            }
        )
        REQUEST_SESSION = session
    return REQUEST_SESSION


def _ensure_playwright(headless: bool) -> bool:
    global PLAYWRIGHT_CONTEXT, PLAYWRIGHT_BROWSER, PLAYWRIGHT_DRIVER
    if sync_playwright is None:
        return False
    if PLAYWRIGHT_CONTEXT:
        return True
    try:
        PLAYWRIGHT_DRIVER = sync_playwright().start()
        PLAYWRIGHT_BROWSER = PLAYWRIGHT_DRIVER.chromium.launch(headless=headless)
    except PlaywrightError:  # pragma: no cover - requires network
        subprocess.run(
            ["python", "-m", "playwright", "install", "chromium"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        PLAYWRIGHT_DRIVER = sync_playwright().start()
        PLAYWRIGHT_BROWSER = PLAYWRIGHT_DRIVER.chromium.launch(headless=headless)
    PLAYWRIGHT_CONTEXT = PLAYWRIGHT_BROWSER.new_context(
        user_agent=random.choice(USER_AGENTS),
        locale="pl-PL",
    )
    return True


def _close_playwright() -> None:
    global PLAYWRIGHT_CONTEXT, PLAYWRIGHT_BROWSER, PLAYWRIGHT_DRIVER
    if PLAYWRIGHT_CONTEXT:
        try:
            PLAYWRIGHT_CONTEXT.close()
        except Exception:  # pragma: no cover
            pass
    if PLAYWRIGHT_BROWSER:
        try:
            PLAYWRIGHT_BROWSER.close()
        except Exception:  # pragma: no cover
            pass
    if PLAYWRIGHT_DRIVER:
        try:
            PLAYWRIGHT_DRIVER.stop()
        except Exception:  # pragma: no cover
            try:
                PLAYWRIGHT_DRIVER.close()
            except Exception:
                pass
    PLAYWRIGHT_CONTEXT = None
    PLAYWRIGHT_BROWSER = None
    PLAYWRIGHT_DRIVER = None


def _fixture_path(url: str, fixtures_dir: str, fallback: Optional[str]) -> Path:
    fixtures_root = Path(fixtures_dir)
    if fallback:
        return fixtures_root / fallback
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query_value = query.get("query", [""])[0]
    if query_value:
        if "|" in query_value:
            query_value = query_value.split("|", 1)[0]
        slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in query_value)
        slug = slug.strip("_") or "query"
        if "program" in slug and "wspierania" in slug:
            return fixtures_root / "search_pwp.html"
        return fixtures_root / f"search_{slug}.html"
    filename = Path(parsed.path).name or "index.html"
    if not filename.endswith(".html"):
        filename = f"{filename}.html"
    upper = filename.upper()
    if "KRAKCHEMIA" in upper:
        return fixtures_root / "krakchemia.html"
    if "PROTEKTOR" in upper:
        return fixtures_root / "protektor.html"
    return fixtures_root / filename


def fetch_html(
    url: str,
    mode: str = "offline",
    *,
    fixtures_dir: str = "fixtures",
    fallback: Optional[str] = None,
    retries: int = 3,
    use_playwright: bool = True,
    headless: bool = True,
) -> str:
    """
    Retrieve HTML content either from offline fixtures or via live network calls.
    """
    if mode not in {"offline", "online"}:
        raise ValueError("mode must be 'offline' or 'online'")

    if mode == "offline":
        path = _fixture_path(url, fixtures_dir, fallback)
        if not path.exists():
            raise FileNotFoundError(
                f"Offline fixture not found for {url} (expected {path})"
            )
        return path.read_text(encoding="utf-8")

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        if use_playwright and _ensure_playwright(headless=headless):
            try:
                page = PLAYWRIGHT_CONTEXT.new_page()  # type: ignore[union-attr]
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1200)
                html = page.content()
                page.close()
                time.sleep(_random_delay())
                return html
            except PlaywrightTimeoutError as exc:  # pragma: no cover - network
                last_error = exc
            except PlaywrightError as exc:  # pragma: no cover - network
                last_error = exc
        session = _ensure_requests_session()
        try:
            response = session.get(url, timeout=40)
            response.raise_for_status()
            time.sleep(_random_delay())
            return response.text
        except requests.RequestException as exc:  # pragma: no cover - network
            last_error = exc
            time.sleep(min(2, 0.5 * attempt))

    if last_error:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def reset_connections() -> None:
    """Close network clients (used at shutdown or in tests)."""
    global REQUEST_SESSION
    if REQUEST_SESSION:
        REQUEST_SESSION.close()
        REQUEST_SESSION = None
    _close_playwright()


__all__ = ["fetch_html", "reset_connections"]

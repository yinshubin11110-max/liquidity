from pathlib import Path
from playwright.sync_api import sync_playwright

search_term = 'PRT'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale='en-US')
    page = context.new_page()
    page.goto(f'https://www.investing.com/search/?q={search_term}', wait_until='networkidle')
    page.wait_for_timeout(2000)
    html = page.content()
    Path('search_prt.html').write_text(html, encoding='utf-8')
    print('saved html length', len(html))
    browser.close()

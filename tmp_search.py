import requests
from pathlib import Path
log = Path('tmp_search.log')
log.write_text('start\n')
headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'text/plain, */*; q=0.01',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://www.investing.com',
    'Referer': 'https://www.investing.com/',
    'Accept-Language': 'en-US,en;q=0.9,pl;q=0.8'
}
session = requests.Session()
session.headers.update({'User-Agent': headers['User-Agent'], 'Accept-Language': headers['Accept-Language']})
resp1 = session.get('https://www.investing.com/', timeout=30)
log.write_text(log.read_text() + f'landing {resp1.status_code}\n')
try:
    response=session.post('https://www.investing.com/instruments/SearchAjax', headers=headers, data={'search_text':'PRT'}, timeout=30)
    log.write_text(log.read_text() + f'status {response.status_code}\n')
    log.write_text(log.read_text() + response.text[:500])
except Exception as exc:
    log.write_text(log.read_text() + f'ERROR {type(exc).__name__} {exc}\n')

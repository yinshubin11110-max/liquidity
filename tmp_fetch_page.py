import requests
from pathlib import Path
url='https://www.investing.com/equities/protektor'
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36', 'Accept-Language':'en-US,en;q=0.9,pl;q=0.8'}
resp=requests.get(url, headers=headers, timeout=30)
print('status', resp.status_code)
print(resp.text[:500])
Path('protektor_page.html').write_text(resp.text)

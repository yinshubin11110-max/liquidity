PYTHON ?= python
PIP := $(PYTHON) -m pip

.PHONY: install test targets offline online clean

install:
	$(PIP) install -r requirements.txt
	$(PYTHON) - <<'PY'
import importlib.util
import subprocess
import sys

if importlib.util.find_spec("playwright") is None:
    sys.exit(0)

subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
PY

test: install
	$(PYTHON) -m pytest -q -m "not e2e"

targets: install
	$(PYTHON) -m src.universe --indices wig20,mwig40,swig80 --out data/targets.csv -v

offline: install
	$(PYTHON) src/scraper.py --mode offline --targets data/targets.csv --out out/pwp_events.csv --windows-out out/pwp_events_windows.csv --excel-out out/pwp_events.xlsx

online: install
	@[ -f data/targets.csv ] || $(MAKE) targets
	$(PYTHON) src/scraper.py --mode online --targets data/targets.csv --out out/pwp_events.csv --windows-out out/pwp_events_windows.csv --excel-out out/pwp_events.xlsx -vv

clean:
	$(PYTHON) - <<'PY'
import pathlib
import shutil

for path in pathlib.Path(".").rglob("__pycache__"):
    shutil.rmtree(path, ignore_errors=True)
PY

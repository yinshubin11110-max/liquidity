@echo off
set PYTHON_BIN=%PYTHON%
if "%PYTHON_BIN%"=="" set PYTHON_BIN=python
set TARGET=%1
if "%TARGET%"=="" goto usage
if "%TARGET%"=="install" goto install
if "%TARGET%"=="test" goto test
if "%TARGET%"=="targets" goto targets
if "%TARGET%"=="offline" goto offline
if "%TARGET%"=="online" goto online
if "%TARGET%"=="clean" goto clean
echo Unknown target: %TARGET%
exit /b 1

:install
"%PYTHON_BIN%" -m pip install -r requirements.txt
"%PYTHON_BIN%" -m playwright install chromium >nul 2>&1 || echo Skipping Playwright browser install.
exit /b 0

:test
call "%~f0" install
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_BIN%" -m pytest -q -m "not e2e"
exit /b %ERRORLEVEL%

:targets
call "%~f0" install
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_BIN%" -m src.universe --indices wig20,mwig40,swig80 --out data/targets.csv -v
exit /b %ERRORLEVEL%

:offline
call "%~f0" install
if errorlevel 1 exit /b %ERRORLEVEL%
"%PYTHON_BIN%" src/scraper.py --mode offline --targets data/targets.csv --out out/pwp_events.csv --windows-out out/pwp_events_windows.csv --excel-out out/pwp_events.xlsx
exit /b %ERRORLEVEL%

:online
call "%~f0" install
if errorlevel 1 exit /b %ERRORLEVEL%
if not exist data\targets.csv call "%~f0" targets
"%PYTHON_BIN%" src/scraper.py --mode online --targets data/targets.csv --out out/pwp_events.csv --windows-out out/pwp_events_windows.csv --excel-out out/pwp_events.xlsx -vv
exit /b %ERRORLEVEL%

:clean
"%PYTHON_BIN%" -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
exit /b %ERRORLEVEL%

:usage
echo Usage: make ^<install^|test^|targets^|offline^|online^|clean^>
exit /b 1

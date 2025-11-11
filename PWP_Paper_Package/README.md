# PWP Liquidity Study (Portable Package)

## Project layout
```
PWP_Paper_Package/
  ├─ src/                     # all analysis scripts
  ├─ data/
  │   ├─ clean_ohlcv/         # per-ticker cleaned dailies (if available)
  │   └─ pwp_monthly_panel.csv
  ├─ results/                 # figures / tables / notes (reproducible)
  └─ reports/                 # writeups (e.g., results_and_discussion.md)
```

## Quick start (Windows PowerShell / CMD)
```
cd PWP_Paper_Package
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# (可选) 若需从原始日频重建面板，先将原始 Investing CSV 放到 data/raw/，再运行：
# python src/pwp_clean_pipeline.py --data_dir data/raw --start 2014-09-01 --end 2025-10-31

# 使用已打包的面板直接再现核心结果到 results/
python run_all.py
```

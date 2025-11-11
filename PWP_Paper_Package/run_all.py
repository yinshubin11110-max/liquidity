\
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(exist_ok=True)

panel = DATA / "pwp_monthly_panel.csv"

steps = [
    # 事件研究主图
    [sys.executable, str(SRC / "pwp_event_amihud.py"), "--panel", str(panel), "--kmin", "-9", "--kmax", "9", "--baseline", "-1"],
    [sys.executable, str(SRC / "pwp_event_cs.py"), "--panel", str(panel), "--kmin", "-9", "--kmax", "9", "--baseline", "-1"],

    # 前后窗口对比
    [sys.executable, str(SRC / "pwp_prepost.py"), "--panel", str(panel), "--pre", "-3", "-1", "--post", "0", "3"],

    # 安慰剂
    [sys.executable, str(SRC / "pwp_placebo.py"), "--panel", str(panel), "--kmin", "-9", "--kmax", "9", "--baseline", "-1", "--shift", "1"],

    # wild-cluster （按需可注释掉某些）
    [sys.executable, str(SRC / "pwp_wildboot.py"), "--panel", str(panel), "--kmin", "-9", "--kmax", "9", "--baseline", "-1", "--B", "499", "--seed", "42"],
    [sys.executable, str(SRC / "pwp_collapse_wild.py"), "--panel", str(panel), "--kmin", "-8", "--kmax", "8", "--baseline", "-1", "--B", "1999", "--seed", "42"],

    # 中位数效应 + bootstrap CI
    [sys.executable, str(SRC / "pwp_primary_median_effect.py"), "--panel", str(panel), "--pre", "-3", "-1", "--post", "0", "3"],
    [sys.executable, str(SRC / "pwp_primary_median_boot.py"), "--panel", str(panel), "--pre", "-3", "-1", "--post", "0", "3", "--B", "10000", "--seed", "42"],
]

for cmd in steps:
    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

# 把当次运行的关键产物收集到 results/
import shutil

patterns = [
    "fig_*.png",
    "figure_data_*.csv",
    "table_prepost_*.csv",
    "delta_*_per_firm.csv",
    "wildboot_*.csv",
    "collapse_wild_*.csv",
    "primary_median_*.csv",
    "notes_*.txt",
]
for pat in patterns:
    for f in ROOT.glob(pat):
        shutil.copy2(f, RESULTS / f.name)

print("Done. See ./results")

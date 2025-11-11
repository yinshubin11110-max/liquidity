from __future__ import annotations

import argparse
import glob
import os
import shutil
import textwrap
from pathlib import Path


SCRIPT_LIST = [
    "pwp_clean_pipeline.py",
    "pwp_event_amihud.py",
    "pwp_event_cs.py",
    "pwp_prepost.py",
    "pwp_placebo.py",
    "pwp_wildboot.py",
    "pwp_collapse_wild.py",
    "pwp_cs_logit_wild.py",
    "pwp_primary_median_effect.py",
    "pwp_primary_median_boot.py",
]


RESULT_PATTERNS = [
    "fig_*.png",
    "figure_data_*.csv",
    "table_prepost_*.csv",
    "delta_*_per_firm.csv",
    "wildboot_*.csv",
    "collapse_wild_*.csv",
    "primary_median_*.csv",
    "notes_*.txt",
    "outputs/*.png",
    "outputs/*.csv",
    "outputs/*.xlsx",
]


def write_requirements(dest_root: Path) -> None:
    req = """\
    pandas>=2.0
    numpy>=1.24
    statsmodels>=0.14
    scipy>=1.11
    matplotlib>=3.7
    XlsxWriter>=3.1
    """
    (dest_root / "requirements.txt").write_text(
        textwrap.dedent(req).strip() + "\n",
        encoding="utf-8",
    )


def write_readme(dest_root: Path) -> None:
    md = f"""\
    # PWP Liquidity Study (Portable Package)

    ## Project layout
    ```
    {dest_root.name}/
      ├─ src/                     # all analysis scripts
      ├─ data/
      │   ├─ clean_ohlcv/         # per-ticker cleaned dailies (if available)
      │   └─ pwp_monthly_panel.csv
      ├─ results/                 # figures / tables / notes (reproducible)
      └─ reports/                 # writeups (e.g., results_and_discussion.md)
    ```

    ## Quick start (Windows PowerShell / CMD)
    ```
    cd {dest_root.name}
    py -m venv .venv
    .venv\\Scripts\\activate
    pip install -r requirements.txt

    # (可选) 若需从原始日频重建面板，先将原始 Investing CSV 放到 data/raw/，再运行：
    # python src/pwp_clean_pipeline.py --data_dir data/raw --start 2014-09-01 --end 2025-10-31

    # 使用已打包的面板直接再现核心结果到 results/
    python run_all.py
    ```
    """
    (dest_root / "README.md").write_text(
        textwrap.dedent(md),
        encoding="utf-8",
    )


def write_run_all(dest_root: Path) -> None:
    code = r"""\
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
"""
    (dest_root / "run_all.py").write_text(code, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True, help="Target folder for the portable package")
    args = parser.parse_args()

    cwd = Path.cwd()
    dest = Path(args.dest).resolve()
    if dest.exists():
        print(f"[INFO] Destination exists: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "src").mkdir(exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)
    (dest / "data" / "clean_ohlcv").mkdir(exist_ok=True)
    (dest / "results").mkdir(exist_ok=True)
    (dest / "reports").mkdir(exist_ok=True)

    panel_candidates = list(cwd.glob("pwp_monthly_panel.csv")) + list(cwd.glob("**/pwp_monthly_panel.csv"))
    if panel_candidates:
        shutil.copy2(panel_candidates[0], dest / "data" / "pwp_monthly_panel.csv")
        print(f"[OK] Copied panel: {panel_candidates[0]}")
    else:
        print("[WARN] pwp_monthly_panel.csv not found; you can place it under data/ manually.")

    src_clean = cwd / "clean_ohlcv"
    if src_clean.exists():
        copied = 0
        for f in src_clean.glob("*.csv"):
            shutil.copy2(f, dest / "data" / "clean_ohlcv" / f.name)
            copied += 1
        print(f"[OK] Copied cleaned dailies: {copied}")
    else:
        print("[INFO] No clean_ohlcv/ in current workspace.")

    src_dir = cwd / "src"
    for name in SCRIPT_LIST:
        src_file = src_dir / name if (src_dir / name).exists() else cwd / name
        if src_file.exists():
            shutil.copy2(src_file, dest / "src" / name)
        else:
            print(f"[WARN] Script not found: {name}")
    print("[OK] Copied scripts to package/src")

    report_candidates = [
        cwd / "reports" / "results_and_discussion.md",
        cwd / "results_and_discussion.md",
    ]
    for cand in report_candidates:
        if cand.exists():
            shutil.copy2(cand, dest / "reports" / "results_and_discussion.md")
            print(f"[OK] Copied report: {cand}")
            break

    moved = 0
    for pat in RESULT_PATTERNS:
        for f in cwd.glob(pat):
            target = dest / "results" / Path(f).name
            try:
                shutil.copy2(f, target)
                moved += 1
            except Exception as exc:
                print(f"[WARN] Could not copy {f}: {exc}")
    print(f"[OK] Collected existing results: {moved} files")

    write_requirements(dest)
    write_readme(dest)
    write_run_all(dest)

    print(f"\n[READY] Portable package written to: {dest}")
    print("Next:")
    print(f"  cd {dest.name}")
    print("  py -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt")
    print("  python run_all.py")


if __name__ == "__main__":
    main()

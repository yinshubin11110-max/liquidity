from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REQUIRED_COLS = ["month", "event_month", "ticker", "k", "cs_spread", "amihud", "turnover_value"]


def parse_dates(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, format="%b-%y", errors="coerce")
    if dt.isna().any():
        dt_alt = pd.to_datetime(series, errors="coerce")
        dt = dt.fillna(dt_alt)
    if dt.isna().any():
        raise ValueError("Failed to parse some dates.")
    return dt


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pwp_monthly_panel.csv")
    parser.add_argument("--panel", default="pwp_monthly_panel.csv")
    args = parser.parse_args()

    path = Path(args.panel)
    if not path.exists():
        raise FileNotFoundError(path)

    encs = ["utf-8-sig", "utf-8", "cp1250", "latin-1"]
    last_err: Exception | None = None
    for enc in encs:
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except Exception as err:  # noqa: BLE001
            last_err = err
    else:
        raise RuntimeError(f"Failed to read {path}") from last_err
    missing = [col for col in REQUIRED_COLS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df["month"] = parse_dates(df["month"])
    df["event_month"] = parse_dates(df["event_month"])
    df["k"] = pd.to_numeric(df["k"], errors="coerce")

    k_counts = df["k"].value_counts().sort_index()
    has_neg = (df["k"] < 0).any()
    has_pos = (df["k"] > 0).any()
    baseline_count = (df["k"] == -1).sum()
    nearest_baseline = None
    if baseline_count == 0:
        negatives = sorted(k_counts[k_counts.index < 0].index)
        nearest_baseline = negatives[-1] if negatives else None

    notes = [
        f"Rows: {len(df)}; Firms: {df['ticker'].nunique()}",
        f"k min={df['k'].min()}, max={df['k'].max()}",
        f"has negative k: {has_neg}, has positive k: {has_pos}",
        f"k=-1 count: {baseline_count}",
    ]
    if nearest_baseline is not None:
        notes.append(f"Suggested baseline: k={nearest_baseline}")

    Path("results").mkdir(exist_ok=True)
    (Path("results") / "notes_data_check.txt").write_text("\n".join(notes), encoding="utf-8")
    print("\n".join(notes))


if __name__ == "__main__":
    main()

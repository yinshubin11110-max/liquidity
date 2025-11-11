from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from pwp_stackeddid import read_panel, run_stacked_subset, plot_k


def split_tickers(df: pd.DataFrame, pre_range: tuple[int, int]) -> tuple[list[str], list[str]]:
    df = df.copy()
    df["k"] = pd.to_numeric(df["k"], errors="coerce")
    medians = (
        df[(df["k"] >= pre_range[0]) & (df["k"] <= pre_range[1])]
        .groupby("ticker")["cs_spread"]
        .median()
        .dropna()
    )
    threshold = medians.median()
    high = medians[medians >= threshold].index.tolist()
    low = medians[medians < threshold].index.tolist()
    return high, low, threshold


def main() -> None:
    ap = argparse.ArgumentParser(description="Stacked DID high/low pre-CS heterogeneity.")
    ap.add_argument("--panel", default="pwp_monthly_panel.csv")
    ap.add_argument("--kmin", type=int, default=-9)
    ap.add_argument("--kmax", type=int, default=9)
    ap.add_argument("--baseline", type=int, default=-1)
    ap.add_argument("--pre", nargs=2, type=int, default=(-3, -1))
    args = ap.parse_args()

    df = read_panel(args.panel)
    high, low, threshold = split_tickers(df, tuple(args.pre))
    print(f"Median pre-CS threshold: {threshold:.4f}")
    print(f"High group: {len(high)} tickers; Low group: {len(low)} tickers")

    out_dir = Path("results/appendix")
    out_dir.mkdir(parents=True, exist_ok=True)

    for group_name, tickers in [("High", high), ("Low", low)]:
        if not tickers:
            continue
        baseline, k_all, k_summ, p_all, p_summ = run_stacked_subset(
            args.panel, "cs_spread", args.kmin, args.kmax, args.baseline, tickers
        )
        prefix = f"stackeddid_cs_{group_name.lower()}"
        k_all.to_csv(out_dir / f"{prefix}_kpath_cohorts.csv", index=False)
        k_summ.to_csv(out_dir / f"{prefix}_kpath_summary.csv", index=False)
        p_all.to_csv(out_dir / f"{prefix}_post_cohorts.csv", index=False)
        p_summ.to_csv(out_dir / f"{prefix}_post_summary.csv", index=False)
        plot_k(k_summ, out_dir / f"fig_{prefix}_kpath.png", f"{group_name} group k-path")
        print(f"{group_name} baseline k={baseline}, cohorts={k_all['cohort'].nunique()}")


if __name__ == "__main__":
    main()

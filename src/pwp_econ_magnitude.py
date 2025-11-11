from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def read_panel(path: str | Path) -> pd.DataFrame:
    encs = ["utf-8-sig", "utf-8", "cp1250", "latin-1"]
    last_err: Exception | None = None
    for enc in encs:
        try:
            df = pd.read_csv(path, encoding=enc)
            return df
        except Exception as err:  # noqa: BLE001
            last_err = err
    raise RuntimeError(f"Failed to read {path}") from last_err


def compute_economic_effects(
    df: pd.DataFrame,
    pre_range: tuple[int, int],
    post_range: tuple[int, int],
) -> pd.DataFrame:
    required = {"ticker", "k", "cs_spread", "turnover_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    df = df.copy()
    df["k"] = pd.to_numeric(df["k"], errors="coerce")
    detail_rows: list[dict[str, float | str]] = []

    for ticker, group in df.groupby("ticker", observed=True):
        pre_mask = (group["k"] >= pre_range[0]) & (group["k"] <= pre_range[1])
        post_mask = (group["k"] >= post_range[0]) & (group["k"] <= post_range[1])
        pre_cs = group.loc[pre_mask, "cs_spread"].median()
        post_cs = group.loc[post_mask, "cs_spread"].median()
        pre_val = group.loc[pre_mask, "turnover_value"].median()
        post_val = group.loc[post_mask, "turnover_value"].median()
        if pd.isna(pre_cs) or pd.isna(post_cs):
            continue

        delta_cs = post_cs - pre_cs
        delta_bp = delta_cs * 10000.0
        cost_saving_per_mn = -delta_cs * 1_000_000.0  # PLN per 1mn turnover (single-sided)

        detail_rows.append(
            {
                "ticker": ticker,
                "cs_pre": pre_cs,
                "cs_post": post_cs,
                "delta_cs": delta_cs,
                "delta_bp": delta_bp,
                "turnover_pre": pre_val,
                "turnover_post": post_val,
                "bp_saving_per_mnPLN": cost_saving_per_mn,
            }
        )

    return pd.DataFrame(detail_rows)


def summarize(detail_df: pd.DataFrame) -> pd.DataFrame:
    if detail_df.empty:
        return pd.DataFrame()
    summary = {
        "median_delta_bp": detail_df["delta_bp"].median(),
        "median_cs_pre": detail_df["cs_pre"].median(),
        "median_turnover_pre": detail_df["turnover_pre"].median(),
        "median_turnover_post": detail_df["turnover_post"].median(),
        "median_saving_pln_per_mn": detail_df["bp_saving_per_mnPLN"].median(),
    }
    return pd.DataFrame([summary])


def main(args: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Economic magnitude of CS spread changes.")
    parser.add_argument("--panel", default="pwp_monthly_panel.csv")
    parser.add_argument("--pre", nargs=2, type=int, default=(-3, -1))
    parser.add_argument("--post", nargs=2, type=int, default=(0, 3))
    args = parser.parse_args(args=args)

    df = read_panel(args.panel)
    detail_df = compute_economic_effects(df, tuple(args.pre), tuple(args.post))
    detail_path = Path("results") / "econ_magnitude_cs.csv"
    detail_path.parent.mkdir(exist_ok=True)
    detail_df.to_csv(detail_path, index=False)

    summary_df = summarize(detail_df)
    summary_df.to_csv(Path("results") / "econ_magnitude_summary.csv", index=False)

    if not summary_df.empty:
        median_bp = summary_df["median_delta_bp"].iloc[0]
        median_saving = summary_df["median_saving_pln_per_mn"].iloc[0]
        print(
            f"Median firm: ΔCS = {median_bp:.2f} bp; approx {median_saving:,.0f} PLN saved per 1mn turnover."
        )
    else:
        print("No valid firms for economic magnitude calculation.")


if __name__ == "__main__":
    main()

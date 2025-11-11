from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURES: tuple[str, ...] = ("amihud", "cs_spread")


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute pre/post window deltas for liquidity measures.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--pre", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive pre-event k range.")
    parser.add_argument("--post", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive post-event k range.")
    return parser.parse_args(args)


def load_panel(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to load {path}; encoding attempts failed. Last error: {last_error}")  # pragma: no cover


def validate_ranges(pre_range: tuple[int, int], post_range: tuple[int, int]) -> None:
    pre_min, pre_max = pre_range
    post_min, post_max = post_range
    if pre_min > pre_max:
        raise ValueError("Pre-event range lower bound must be <= upper bound.")
    if post_min > post_max:
        raise ValueError("Post-event range lower bound must be <= upper bound.")
    if post_min < pre_max:
        raise ValueError("Post-event window must start after the pre-event window.")


def compute_firm_delta(df: pd.DataFrame, measure: str, pre_range: tuple[int, int], post_range: tuple[int, int]) -> pd.DataFrame:
    needed = {"ticker", "k", measure}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.dropna(subset=list(needed))
    if df.empty:
        raise ValueError(f"No valid observations for measure '{measure}'.")

    pre_mask = df["k"].between(pre_range[0], pre_range[1])
    post_mask = df["k"].between(post_range[0], post_range[1])

    grouped = []
    for mask, label in ((pre_mask, "pre"), (post_mask, "post")):
        window = (
            df.loc[mask]
            .groupby("ticker", observed=True)[measure]
            .mean()
            .rename(label)
        )
        grouped.append(window)

    window_df = pd.concat(grouped, axis=1)
    window_df = window_df.dropna()
    window_df["delta"] = window_df["post"] - window_df["pre"]
    window_df["measure"] = measure
    return window_df.reset_index()


def summarise_deltas(delta_df: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for measure, subset in delta_df.groupby("measure", observed=True):
        deltas = subset["delta"].to_numpy()
        if len(deltas) == 0:
            continue

        mean_delta = float(np.mean(deltas))
        median_delta = float(np.median(deltas))

        if len(deltas) > 1:
            t_stat, t_p = stats.ttest_1samp(deltas, popmean=0.0, nan_policy="omit")
            _, wilcoxon_p = stats.wilcoxon(deltas, zero_method="wilcox", correction=False, alternative="two-sided", mode="auto")
        else:
            t_stat, t_p, wilcoxon_p = np.nan, np.nan, np.nan

        records.append(
            {
                "measure": measure,
                "N_firms": int(len(deltas)),
                "mean_delta": mean_delta,
                "median_delta": median_delta,
                "t_stat": float(t_stat) if not np.isnan(t_stat) else np.nan,
                "t_p": float(t_p) if not np.isnan(t_p) else np.nan,
                "wilcoxon_p": float(wilcoxon_p) if not np.isnan(wilcoxon_p) else np.nan,
            }
        )
    return pd.DataFrame.from_records(records)


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    pre_range = (args.pre[0], args.pre[1])
    post_range = (args.post[0], args.post[1])
    validate_ranges(pre_range, post_range)

    panel_df = load_panel(panel_path)
    delta_frames = []
    for measure in MEASURES:
        firm_deltas = compute_firm_delta(panel_df, measure, pre_range, post_range)
        delta_frames.append(firm_deltas)

    combined = pd.concat(delta_frames, ignore_index=True)
    combined.to_csv("table_prepost_firm_deltas.csv", index=False)

    summary = summarise_deltas(combined)
    summary.to_csv("table_prepost_summary.csv", index=False)


if __name__ == "__main__":
    main()

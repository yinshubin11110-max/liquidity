from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats


ENCODING_CANDIDATES: Tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURES: Tuple[str, ...] = ("amihud", "cs_spread")


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Primary median effect (Wilcoxon + Hodges-Lehmann).")
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


def compute_ticker_deltas(df: pd.DataFrame, measure: str, pre_range: Tuple[int, int], post_range: Tuple[int, int]) -> np.ndarray:
    pre_min, pre_max = pre_range
    post_min, post_max = post_range
    deltas: List[float] = []

    for _, group in df.groupby("ticker", observed=True):
        k_vals = group["k"]
        pre_vals = group.loc[(k_vals >= pre_min) & (k_vals <= pre_max), measure]
        post_vals = group.loc[(k_vals >= post_min) & (k_vals <= post_max), measure]
        if not pre_vals.empty and not post_vals.empty:
            deltas.append(post_vals.median() - pre_vals.median())
    return np.array(deltas, dtype=float)


def wilcoxon_summary(deltas: np.ndarray) -> Dict[str, float]:
    deltas = deltas[np.isfinite(deltas)]
    if deltas.size == 0:
        return {"n": 0, "hl": np.nan, "wilcoxon_W": np.nan, "p_value": np.nan, "ci_low": np.nan, "ci_high": np.nan}

    wilcoxon_res = stats.wilcoxon(deltas, alternative="two-sided", zero_method="wilcox", correction=False, mode="auto")

    pairwise = []
    for i in range(deltas.size):
        for j in range(i, deltas.size):
            pairwise.append(0.5 * (deltas[i] + deltas[j]))
    pairwise_arr = np.sort(np.array(pairwise, dtype=float))
    hl = float(np.median(pairwise_arr))
    ci_low = float(np.percentile(pairwise_arr, 2.5))
    ci_high = float(np.percentile(pairwise_arr, 97.5))

    return {
        "n": float(deltas.size),
        "hl": float(hl),
        "wilcoxon_W": float(wilcoxon_res.statistic),
        "p_value": float(wilcoxon_res.pvalue),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
    }


def prepare_panel(df: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "k", "amihud", "cs_spread"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    df["ticker"] = df["ticker"].astype(str)
    df["k"] = df["k"].astype(int)
    return df


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    pre_range = (args.pre[0], args.pre[1])
    post_range = (args.post[0], args.post[1])
    if pre_range[0] > pre_range[1] or post_range[0] > post_range[1]:
        raise ValueError("Invalid pre or post range.")

    df = prepare_panel(load_panel(panel_path))

    rows = []
    for measure in MEASURES:
        deltas = compute_ticker_deltas(df, measure, pre_range, post_range)
        summary = wilcoxon_summary(deltas)
        summary["measure"] = measure
        rows.append(summary)

    results_df = pd.DataFrame(rows)
    results_df.to_csv("notes_primary.txt", index=False)


if __name__ == "__main__":
    main()

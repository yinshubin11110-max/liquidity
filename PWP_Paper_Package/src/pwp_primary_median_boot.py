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
    parser = argparse.ArgumentParser(description="Median effect with bootstrap HL confidence intervals.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--pre", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive pre-event k range.")
    parser.add_argument("--post", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive post-event k range.")
    parser.add_argument("--B", type=int, default=10000, help="Number of bootstrap resamples.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    return parser.parse_args(args)


def load_panel(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to load {path}; encoding attempts failed. Last error: {last_error}")  # pragma: no cover


def prepare_panel(df: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "k", "amihud", "cs_spread"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    df = df.copy()
    df["ticker"] = df["ticker"].astype(str)
    df["k"] = df["k"].astype(int)
    return df


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


def hodges_lehmann(deltas: np.ndarray) -> Tuple[float, float, float]:
    pairwise = []
    for i in range(deltas.size):
        for j in range(i, deltas.size):
            pairwise.append(0.5 * (deltas[i] + deltas[j]))
    pairwise_arr = np.sort(np.array(pairwise, dtype=float))
    hl = float(np.median(pairwise_arr))
    ci_low = float(np.percentile(pairwise_arr, 2.5))
    ci_high = float(np.percentile(pairwise_arr, 97.5))
    return hl, ci_low, ci_high


def bootstrap_hl(
    deltas: np.ndarray,
    B: int,
    rng: np.random.Generator,
) -> Tuple[float, float]:
    if deltas.size == 0:
        return np.nan, np.nan
    boot_vals = np.empty(B, dtype=float)
    for b in range(B):
        sample = rng.choice(deltas, size=deltas.size, replace=True)
        boot_vals[b], _, _ = hodges_lehmann(sample)
    return float(np.percentile(boot_vals, 2.5)), float(np.percentile(boot_vals, 97.5))


def summarize_measure(
    df: pd.DataFrame,
    measure: str,
    pre_range: Tuple[int, int],
    post_range: Tuple[int, int],
    B: int,
    rng: np.random.Generator,
) -> Dict[str, float]:
    deltas = compute_ticker_deltas(df, measure, pre_range, post_range)
    deltas = deltas[np.isfinite(deltas)]
    if deltas.size == 0:
        return {
            "measure": measure,
            "n": 0,
            "hl": np.nan,
            "hl_ci_low": np.nan,
            "hl_ci_high": np.nan,
            "hl_boot_ci_low": np.nan,
            "hl_boot_ci_high": np.nan,
            "wilcoxon_W": np.nan,
            "wilcoxon_p": np.nan,
        }

    wilcoxon_res = stats.wilcoxon(deltas, alternative="two-sided", zero_method="wilcox", correction=False, mode="auto")
    hl, ci_low, ci_high = hodges_lehmann(deltas)
    boot_ci_low, boot_ci_high = bootstrap_hl(deltas, B, rng)

    return {
        "measure": measure,
        "n": float(deltas.size),
        "hl": hl,
        "hl_ci_low": ci_low,
        "hl_ci_high": ci_high,
        "hl_boot_ci_low": boot_ci_low,
        "hl_boot_ci_high": boot_ci_high,
        "wilcoxon_W": float(wilcoxon_res.statistic),
        "wilcoxon_p": float(wilcoxon_res.pvalue),
    }


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    pre_range = (args.pre[0], args.pre[1])
    post_range = (args.post[0], args.post[1])
    if pre_range[0] > pre_range[1] or post_range[0] > post_range[1]:
        raise ValueError("Invalid pre or post range.")
    if args.B <= 0:
        raise ValueError("Number of bootstrap resamples must be positive.")

    df = prepare_panel(load_panel(panel_path))
    rng = np.random.default_rng(args.seed)

    rows = []
    for measure in MEASURES:
        rows.append(
            summarize_measure(
                df,
                measure,
                pre_range,
                post_range,
                args.B,
                rng,
            )
        )

    pd.DataFrame(rows).to_csv("notes_primary_boot.txt", index=False)


if __name__ == "__main__":
    main()

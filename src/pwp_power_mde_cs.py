from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp1250", "latin-1")


def read_panel(path: Path) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in ENCODING_CANDIDATES:
        try:
            df = pd.read_csv(path, encoding=enc)
            return df
        except Exception as err:  # noqa: BLE001
            last_err = err
    raise RuntimeError(f"Failed to read {path}") from last_err


def compute_diffs(df: pd.DataFrame, pre_range: tuple[int, int], post_range: tuple[int, int]) -> pd.DataFrame:
    pre_min, pre_max = pre_range
    post_min, post_max = post_range
    records: list[dict[str, float | str]] = []
    for ticker, group in df.groupby("ticker", observed=True):
        k_vals = group["k"]
        pre_vals = group.loc[(k_vals >= pre_min) & (k_vals <= pre_max), "cs_spread"]
        post_vals = group.loc[(k_vals >= post_min) & (k_vals <= post_max), "cs_spread"]
        if pre_vals.empty or post_vals.empty:
            continue
        records.append(
            {
                "ticker": ticker,
                "pre_mean": pre_vals.mean(),
                "post_mean": post_vals.mean(),
                "diff": post_vals.mean() - pre_vals.mean(),
            }
        )
    return pd.DataFrame(records)


def simulate_power(diffs: np.ndarray, delta: float, R: int, rng: np.random.Generator) -> float:
    n = len(diffs)
    if n == 0:
        return np.nan
    shifted = diffs + delta
    successes = 0
    for _ in range(R):
        sample = rng.choice(shifted, size=n, replace=True)
        mean = float(np.mean(sample))
        sd = float(np.std(sample, ddof=1))
        if sd == 0:
            continue
        t_stat = mean / (sd / np.sqrt(n))
        if abs(t_stat) >= 1.96:
            successes += 1
    return successes / R


def main(args: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Power and MDE for cs_spread mean effect")
    parser.add_argument("--panel", default="pwp_monthly_panel.csv")
    parser.add_argument("--pre", nargs=2, type=int, default=(-3, -1))
    parser.add_argument("--post", nargs=2, type=int, default=(0, 3))
    parser.add_argument("--min", type=float, default=-0.10)
    parser.add_argument("--max", type=float, default=0.0)
    parser.add_argument("--steps", type=int, default=21)
    parser.add_argument("--R", type=int, default=499)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(args=args)

    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(panel_path)

    df = read_panel(panel_path)
    if "cs_spread" not in df.columns or "k" not in df.columns or "ticker" not in df.columns:
        raise ValueError("Panel must contain cs_spread, k, ticker columns.")

    diffs_df = compute_diffs(df, tuple(args.pre), tuple(args.post))
    if diffs_df.empty:
        raise RuntimeError("No valid firms with both pre and post observations.")

    diffs = diffs_df["diff"].to_numpy()
    rng = np.random.default_rng(args.seed)

    deltas = np.linspace(args.min, args.max, args.steps)
    power_values = []
    for delta in deltas:
        power = simulate_power(diffs, delta, args.R, rng)
        power_values.append({"delta": delta, "power": power})

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    power_df = pd.DataFrame(power_values)
    power_df.to_csv(results_dir / "power_curve_cs.csv", index=False)

    mde_row = power_df.loc[power_df["power"] >= 0.8]
    if mde_row.empty:
        mde = np.nan
    else:
        mde = float(mde_row.iloc[0]["delta"])

    mde_df = pd.DataFrame([{"MDE_delta_at_80pct_power": mde}])
    mde_df.to_csv(results_dir / "power_mde_cs.csv", index=False)

    print(power_df)
    print(mde_df)


if __name__ == "__main__":
    main()

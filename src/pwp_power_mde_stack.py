from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm

from pwp_stackeddid import run_stacked


def power_curve(
    panel_path: str | Path,
    ycol: str,
    deltas: np.ndarray,
    kmin: int,
    kmax: int,
    baseline: int,
) -> tuple[pd.DataFrame, float, float]:
    _, _, _, _, p_summary = run_stacked(panel_path, ycol, kmin, kmax, baseline)
    if p_summary.empty:
        raise RuntimeError("Post-ATT summary is empty; run stacked DID first.")

    att = float(p_summary["att"].iloc[0])
    se = float(p_summary["se"].iloc[0])
    if se in (None, 0) or np.isnan(se):
        raise ValueError("Invalid standard error for Post-ATT.")

    zcrit = 1.96
    rows = []
    for delta in deltas:
        mu = att + delta
        z = mu / se
        power = 1 - norm.cdf(zcrit - z) + norm.cdf(-zcrit - z)
        rows.append({"delta": delta, "power": power})
        print(f"delta={delta:.4f} -> power={power:.3f}")

    power_df = pd.DataFrame(rows)
    mde_row = power_df.loc[power_df["power"] >= 0.8]
    if mde_row.empty:
        mde = np.nan
        max_power = float(power_df["power"].max())
    else:
        mde = float(mde_row.iloc[(mde_row["delta"].abs()).argsort()].iloc[0]["delta"])
        max_power = float(power_df["power"].max())

    return power_df, mde, max_power


def main(args: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Power & MDE using stacked-DID Post ATT.")
    parser.add_argument("--panel", default="pwp_monthly_panel.csv")
    parser.add_argument("--y", default="cs_spread")
    parser.add_argument("--min", type=float, default=-0.30)
    parser.add_argument("--max", type=float, default=0.0)
    parser.add_argument("--steps", type=int, default=31)
    parser.add_argument("--kmin", type=int, default=-9)
    parser.add_argument("--kmax", type=int, default=9)
    parser.add_argument("--baseline", type=int, default=-1)
    args = parser.parse_args(args=args)

    deltas = np.linspace(args.min, args.max, args.steps)
    power_df, mde, max_power = power_curve(
        args.panel, args.y, deltas, args.kmin, args.kmax, args.baseline
    )

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    power_df.to_csv(results_dir / "power_curve_cs_stack.csv", index=False)

    mde_data = {"MDE_delta_at_80pct_power": mde, "max_power_observed": max_power}
    if np.isnan(mde):
        print(f"Max power achieved: {max_power:.3f} (< 0.8)")
    else:
        print(f"MDE achieving >=80% power: {mde:.4f}")
    pd.DataFrame([mde_data]).to_csv(results_dir / "power_mde_cs_stack.csv", index=False)


if __name__ == "__main__":
    main()

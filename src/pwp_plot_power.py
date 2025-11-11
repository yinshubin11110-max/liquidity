from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="results/power_curve_cs.csv")
    ap.add_argument("--output", default="results/fig_power_curve_cs.png")
    ap.add_argument("--title", default="Power curve (cs_spread)")
    args = ap.parse_args()

    df = pd.read_csv(args.input)
    plt.figure(figsize=(6.2, 3.8))
    plt.plot(df["delta"], df["power"], marker="o")
    plt.axhline(0.8, ls="--", lw=1)
    plt.xlabel("Assumed post shift in CS spread (delta)")
    plt.ylabel("Power")
    plt.title(args.title)
    plt.tight_layout()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=200)
    plt.close()
    print(f"saved: {out}")


if __name__ == "__main__":
    main()

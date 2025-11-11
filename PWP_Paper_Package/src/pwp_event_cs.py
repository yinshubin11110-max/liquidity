from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURE_COLUMN = "cs_spread"
PLOT_TITLE = "Corwin–Schultz Spread Event Study"
YLABEL = "CS spread effect relative to baseline"


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corwin–Schultz spread event-study regression.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--kmin", type=int, default=-9, help="Lower bound for event window (inclusive).")
    parser.add_argument("--kmax", type=int, default=9, help="Upper bound for event window (inclusive).")
    parser.add_argument("--baseline", type=int, default=-1, help="Reference event month (default: -1).")
    parser.add_argument(
        "--basel",
        dest="baseline",
        action="store_const",
        const=-1,
        help="Alias for setting baseline to -1 (no argument required).",
    )
    return parser.parse_args(args=args)


def load_panel(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to load {path}; encoding attempts failed. Last error: {last_error}")  # pragma: no cover


def prepare_data(df: pd.DataFrame, k_min: int, k_max: int) -> pd.DataFrame:
    required = [MEASURE_COLUMN, "k", "ticker", "month"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df[df["k"].between(k_min, k_max)]
    df = df.dropna(subset=required)
    if df.empty:
        raise ValueError("No valid observations after filtering.")

    df = df.copy()
    df["k"] = df["k"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    return df


def fit_event_regression(df: pd.DataFrame, baseline: int, k_values: list[int]):
    df = df.copy()
    df["k_cat"] = pd.Categorical(df["k"], categories=k_values, ordered=True)
    treatment_term = f"C(k_cat, Treatment(reference={baseline}))"
    formula = f"{MEASURE_COLUMN} ~ {treatment_term} + C(ticker) + C(month)"
    model = smf.ols(formula, data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result, treatment_term


def build_coeff_table(result, treatment_term: str, k_values: list[int], baseline: int, counts: pd.Series) -> pd.DataFrame:
    conf_int = result.conf_int()
    rows: list[dict[str, float | int | None]] = []

    for k in k_values:
        if k == baseline:
            coef = 0.0
            std_err = 0.0
            ci_lower = 0.0
            ci_upper = 0.0
            p_value = np.nan
        else:
            param_name = f"{treatment_term}[T.{k}]"
            coef = float(result.params.get(param_name, np.nan))
            std_err = float(result.bse.get(param_name, np.nan))
            if param_name in conf_int.index:
                ci_lower = float(conf_int.loc[param_name, 0])
                ci_upper = float(conf_int.loc[param_name, 1])
            else:
                ci_lower = np.nan
                ci_upper = np.nan
            p_value = float(result.pvalues.get(param_name, np.nan))

        rows.append(
            {
                "k": k,
                "coef": coef,
                "std_err": std_err,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "p_value": p_value,
                "n_obs": int(counts.get(k, 0)),
            }
        )

    return pd.DataFrame(rows)


def generate_plot(coeff_df: pd.DataFrame, k_values: list[int], baseline: int, path: Path) -> None:
    plot_df = coeff_df.dropna(subset=["coef"])
    yerr = np.vstack(
        [
            plot_df["coef"] - plot_df["ci_lower"],
            plot_df["ci_upper"] - plot_df["coef"],
        ]
    )

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axhline(0.0, color="black", linewidth=1.0, linestyle="--")
    ax.axvline(0, color="grey", linewidth=1.0, linestyle=":")
    ax.errorbar(
        plot_df["k"],
        plot_df["coef"],
        yerr=yerr,
        fmt="-o",
        linewidth=1.6,
        markersize=5,
        capsize=4,
        color="#d62728",
    )
    ax.set_xlabel("Event month (k)")
    ax.set_ylabel(YLABEL + f" (baseline k = {baseline})")
    ax.set_title(PLOT_TITLE)
    ax.set_xticks(k_values)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def run_wald_test(result, treatment_term: str, k_values: list[int], baseline: int) -> tuple[float, float]:
    pre_terms = [
        f"{treatment_term}[T.{k}] = 0"
        for k in k_values
        if k < baseline
    ]
    if not pre_terms:
        return (np.nan, np.nan)

    joint_constraint = ", ".join(pre_terms)
    wald_res = result.wald_test(joint_constraint, use_f=True, scalar=True)
    statistic = float(np.squeeze(wald_res.statistic))
    p_value = float(np.squeeze(wald_res.pvalue))
    return statistic, p_value


def write_notes(path: Path, wald_f: float, wald_p: float, k_values: list[int], counts: pd.Series) -> None:
    with path.open("w", encoding="utf-8") as fp:
        fp.write(f"Parallel trend Wald F-statistic: {wald_f:.4f}\n")
        fp.write(f"p-value: {wald_p:.4g}\n")
        fp.write("Sample counts by k:\n")
        for k in k_values:
            fp.write(f"k={k:+d}: n={int(counts.get(k, 0))}\n")


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    if args.kmin > args.kmax:
        raise ValueError("kmin must be <= kmax.")
    if not (args.kmin <= args.baseline <= args.kmax):
        raise ValueError("Baseline must lie within [kmin, kmax].")

    panel_df = prepare_data(load_panel(panel_path), args.kmin, args.kmax)
    k_values = list(range(args.kmin, args.kmax + 1))
    counts = panel_df.groupby("k", observed=True).size()

    result, treatment_term = fit_event_regression(panel_df, args.baseline, k_values)
    coeff_df = build_coeff_table(result, treatment_term, k_values, args.baseline, counts)
    coeff_df.to_csv("figure_data_event_CS.csv", index=False)

    generate_plot(coeff_df, k_values, args.baseline, Path("fig_event_CS.png"))

    wald_f, wald_p = run_wald_test(result, treatment_term, k_values, args.baseline)
    write_notes(Path("notes_cs.txt"), wald_f, wald_p, k_values, counts)


if __name__ == "__main__":
    main()

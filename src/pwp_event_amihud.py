from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
K_VALUES: list[int] = list(range(-9, 10))
BASELINE_K = -1
TREATMENT_TERM = f"C(k_cat, Treatment(reference={BASELINE_K}))"


def load_panel(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to load {path}; encoding attempts failed. Last error: {last_error}")  # pragma: no cover


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    keep_cols = ["amihud", "k", "ticker", "month"]
    missing = [col for col in keep_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df[df["k"].between(K_VALUES[0], K_VALUES[-1])]
    df = df.dropna(subset=keep_cols)
    if df.empty:
        raise ValueError("No valid observations after filtering.")

    df = df.copy()
    df["k"] = df["k"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    df["k_cat"] = pd.Categorical(df["k"], categories=K_VALUES, ordered=True)
    return df


def fit_event_regression(df: pd.DataFrame):
    formula = f"amihud ~ {TREATMENT_TERM} + C(ticker) + C(month)"
    model = smf.ols(formula, data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result


def build_coeff_table(result, counts: pd.Series) -> pd.DataFrame:
    conf_int = result.conf_int()
    rows: list[dict[str, float | int | None]] = []

    for k in K_VALUES:
        if k == BASELINE_K:
            coef = 0.0
            std_err = 0.0
            ci_lower = 0.0
            ci_upper = 0.0
            p_value = np.nan
        else:
            param_name = f"{TREATMENT_TERM}[T.{k}]"
            coef = float(result.params.get(param_name, np.nan))
            std_err = float(result.bse.get(param_name, np.nan))
            ci_bounds = conf_int.loc[param_name] if param_name in conf_int.index else [np.nan, np.nan]
            ci_lower = float(ci_bounds[0])
            ci_upper = float(ci_bounds[1])
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

    coeff_df = pd.DataFrame(rows)
    return coeff_df


def generate_plot(coeff_df: pd.DataFrame, path: Path) -> None:
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
        color="#1f77b4",
    )
    ax.set_xlabel("Event month (k)")
    ax.set_ylabel("Amihud effect relative to k = -1")
    ax.set_title("Amihud Event Study")
    ax.set_xticks(K_VALUES)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def run_wald_test(result) -> tuple[float, float]:
    pre_terms = [
        f"{TREATMENT_TERM}[T.{k}] = 0"
        for k in K_VALUES
        if k < 0 and k != BASELINE_K
    ]
    if not pre_terms:
        return (np.nan, np.nan)

    joint_constraint = ", ".join(pre_terms)
    wald_res = result.wald_test(joint_constraint, use_f=True, scalar=True)
    statistic = float(np.squeeze(wald_res.statistic))
    p_value = float(np.squeeze(wald_res.pvalue))
    return statistic, p_value


def write_notes(path: Path, wald_f: float, wald_p: float, counts: pd.Series) -> None:
    with path.open("w", encoding="utf-8") as fp:
        fp.write(f"Parallel trend Wald F-statistic: {wald_f:.4f}\n")
        fp.write(f"p-value: {wald_p:.4g}\n")
        fp.write("Sample counts by k:\n")
        for k in K_VALUES:
            fp.write(f"k={k:+d}: n={int(counts.get(k, 0))}\n")


def main(args: Iterable[str] | None = None) -> None:  # noqa: ARG001
    panel_path = Path("pwp_monthly_panel.csv")
    if not panel_path.exists():
        raise FileNotFoundError("pwp_monthly_panel.csv not found.")

    df = prepare_data(load_panel(panel_path))
    counts = df.groupby("k", observed=True).size()

    result = fit_event_regression(df)
    coeff_df = build_coeff_table(result, counts)
    coeff_df.to_csv("figure_data_event_Amihud.csv", index=False)

    generate_plot(coeff_df, Path("fig_event_Amihud.png"))

    wald_f, wald_p = run_wald_test(result)
    write_notes(Path("notes_amihud.txt"), wald_f, wald_p, counts)


if __name__ == "__main__":
    main()

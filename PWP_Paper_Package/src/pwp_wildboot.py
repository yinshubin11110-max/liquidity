from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Dict, List

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURES: tuple[str, ...] = ("amihud", "cs_spread")


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wild cluster bootstrap (Rademacher) for event-study coefficients.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--kmin", type=int, default=-9, help="Lower bound for event window (inclusive).")
    parser.add_argument("--kmax", type=int, default=9, help="Upper bound for event window (inclusive).")
    parser.add_argument("--baseline", type=int, default=-1, help="Reference event month (default: -1).")
    parser.add_argument("--B", type=int, default=499, help="Number of bootstrap replications.")
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


def prepare_measure_data(
    panel: pd.DataFrame,
    measure: str,
    kmin: int,
    kmax: int,
) -> pd.DataFrame:
    required = {"k", "ticker", "month", measure}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"Missing required columns for {measure}: {missing}")

    df = panel.dropna(subset=list(required)).copy()
    df = df[df["k"].between(kmin, kmax)]
    if df.empty:
        raise ValueError(f"No observations for measure {measure} within the requested k window.")

    df["k"] = df["k"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    return df


def fit_event_model(df: pd.DataFrame, measure: str, baseline: int, k_values: List[int]):
    df = df.copy()
    df["k_cat"] = pd.Categorical(df["k"], categories=k_values, ordered=True)
    treatment_term = f"C(k_cat, Treatment(reference={baseline}))"
    formula = f"{measure} ~ {treatment_term} + C(ticker) + C(month)"
    model = smf.ols(formula, data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result, treatment_term


def wild_cluster_bootstrap(
    df: pd.DataFrame,
    measure: str,
    baseline: int,
    k_values: List[int],
    treatment_term: str,
    base_result,
    B: int,
    seed: int,
) -> Dict[int, List[float]]:
    rng = np.random.default_rng(seed)
    tickers = df["ticker"].to_numpy()
    unique_tickers = df["ticker"].unique()
    ticker_index = {ticker: idx for idx, ticker in enumerate(unique_tickers)}

    residuals = base_result.resid.to_numpy()
    fitted = base_result.fittedvalues.to_numpy()

    boot_t: Dict[int, List[float]] = {}
    param_names: Dict[int, str] = {}
    for k in k_values:
        if k == baseline:
            continue
        name = f"{treatment_term}[T.{k}]"
        if name in base_result.params.index:
            boot_t[k] = []
            param_names[k] = name

    if not boot_t:
        raise RuntimeError(f"No estimable event coefficients found for measure {measure}.")

    group_indices = np.vectorize(ticker_index.get)(tickers)

    for b in range(B):
        signs = rng.choice([-1.0, 1.0], size=len(unique_tickers))
        weights = signs[group_indices]
        y_star = fitted + residuals * weights

        df_boot = df.copy()
        df_boot[measure] = y_star
        df_boot["k_cat"] = pd.Categorical(df_boot["k"], categories=k_values, ordered=True)

        boot_model = smf.ols(
            f"{measure} ~ {treatment_term} + C(ticker) + C(month)",
            data=df_boot,
        )
        try:
            boot_result = boot_model.fit(cov_type="cluster", cov_kwds={"groups": df_boot["ticker"]})
        except Exception:
            continue

        for k, name in param_names.items():
            t_val = boot_result.tvalues.get(name)
            if t_val is not None and np.isfinite(t_val):
                boot_t[k].append(float(t_val))

    return boot_t


def assemble_results(
    measure: str,
    baseline: int,
    k_values: List[int],
    treatment_term: str,
    base_result,
    boot_t: Dict[int, List[float]],
    B: int,
) -> pd.DataFrame:
    records = []
    for k in k_values:
        if k == baseline:
            continue
        param_name = f"{treatment_term}[T.{k}]"
        if param_name not in base_result.params.index:
            continue

        coef = float(base_result.params[param_name])
        t_obs = float(base_result.tvalues[param_name])
        boot_vals = boot_t.get(k, [])
        valid = np.array(boot_vals, dtype=float)
        if valid.size == 0:
            p_wild = np.nan
            n_boot = 0
        else:
            numerator = np.sum(np.abs(valid) >= abs(t_obs)) + 1
            denominator = valid.size + 1
            p_wild = numerator / denominator
            n_boot = int(valid.size)

        records.append(
            {
                "measure": measure,
                "k": k,
                "coef": coef,
                "t_cluster": t_obs,
                "p_wild": p_wild,
                "n_boot": n_boot,
            }
        )

    return pd.DataFrame.from_records(records)


def write_notes(path: Path, summary: Dict[str, tuple[int, float]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for measure in MEASURES:
            max_k, min_p = summary.get(measure, (None, np.nan))
            if max_k is None:
                fp.write(f"{measure}: no estimable coefficients\n")
            else:
                fp.write(f"{measure}: min p_wild = {min_p:.4f} at k={max_k:+d}\n")


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    if args.kmin > args.kmax:
        raise ValueError("kmin must be <= kmax.")
    if not (args.kmin <= args.baseline <= args.kmax):
        raise ValueError("Baseline must lie within [kmin, kmax].")
    if args.B <= 0:
        raise ValueError("Number of bootstrap replications must be positive.")

    panel_df = load_panel(panel_path)
    k_values = list(range(args.kmin, args.kmax + 1))

    summary: Dict[str, tuple[int, float]] = {}

    for measure in MEASURES:
        df_measure = prepare_measure_data(panel_df, measure, args.kmin, args.kmax)
        base_result, treatment_term = fit_event_model(df_measure, measure, args.baseline, k_values)
        boot_t = wild_cluster_bootstrap(
            df_measure,
            measure,
            args.baseline,
            k_values,
            treatment_term,
            base_result,
            args.B,
            args.seed,
        )
        result_df = assemble_results(
            measure,
            args.baseline,
            k_values,
            treatment_term,
            base_result,
            boot_t,
            args.B,
        )
        csv_path = Path(f"wildboot_{measure}.csv")
        result_df.to_csv(csv_path, index=False)

        valid_rows = result_df.dropna(subset=["p_wild"])
        if not valid_rows.empty:
            min_row = valid_rows.loc[valid_rows["p_wild"].idxmin()]
            summary[measure] = (int(min_row["k"]), float(min_row["p_wild"]))
        else:
            summary[measure] = (None, np.nan)

    write_notes(Path("notes_wildboot.txt"), summary)


if __name__ == "__main__":
    main()

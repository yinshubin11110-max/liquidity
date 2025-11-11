from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: Tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURES: Tuple[str, ...] = ("amihud", "cs_spread")


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-period DiD with wild cluster bootstrap.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--pre", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive pre-event k range.")
    parser.add_argument("--post", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive post-event k range.")
    parser.add_argument("--B", type=int, default=1999, help="Number of bootstrap replications.")
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


def filter_panel(df: pd.DataFrame, measure: str, pre_range: Tuple[int, int], post_range: Tuple[int, int]) -> pd.DataFrame:
    required = {"k", "ticker", "month", measure}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns for {measure}: {missing}")

    k_min = min(pre_range[0], post_range[0])
    k_max = max(pre_range[1], post_range[1])
    df = df.dropna(subset=list(required)).copy()
    df = df[df["k"].between(k_min, k_max)]
    df["k"] = df["k"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    df["post_indicator"] = df["k"].between(post_range[0], post_range[1]).astype(int)
    return df


def collapse_mean(df: pd.DataFrame, measure: str, pre_range: Tuple[int, int], post_range: Tuple[int, int]) -> pd.DataFrame:
    records = []
    for ticker, ticker_df in df.groupby("ticker", observed=True):
        pre_values = ticker_df.loc[ticker_df["k"].between(*pre_range), measure]
        post_values = ticker_df.loc[ticker_df["k"].between(*post_range), measure]
        if pre_values.empty or post_values.empty:
            continue
        records.append(
            {
                "ticker": ticker,
                "pre_mean": pre_values.mean(),
                "post_mean": post_values.mean(),
            }
        )
    collapsed = pd.DataFrame(records)
    collapsed["diff"] = collapsed["post_mean"] - collapsed["pre_mean"]
    return collapsed


def fit_model(df: pd.DataFrame) -> Tuple:
    model = smf.ols("diff ~ 1", data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result


def wild_cluster_bootstrap(df: pd.DataFrame, base_result, B: int, seed: int) -> List[float]:
    rng = np.random.default_rng(seed)
    df = df.copy()
    tickers = df["ticker"].to_numpy()
    unique_tickers = df["ticker"].unique()
    ticker_index = {ticker: idx for idx, ticker in enumerate(unique_tickers)}
    group_indices = np.vectorize(ticker_index.get)(tickers)

    residuals = base_result.resid.to_numpy()
    fitted = base_result.fittedvalues.to_numpy()

    boot_vals: List[float] = []

    for _ in range(B):
        signs = rng.choice([-1.0, 1.0], size=len(unique_tickers))
        weights = signs[group_indices]
        y_star = fitted + residuals * weights

        df_boot = df.copy()
        df_boot["diff"] = y_star

        boot_model = smf.ols("diff ~ 1", data=df_boot)
        try:
            boot_result = boot_model.fit(cov_type="cluster", cov_kwds={"groups": df_boot["ticker"]})
        except Exception:
            continue

        coef = boot_result.params.get("Intercept")
        se = boot_result.bse.get("Intercept")
        if coef is None or se in (None, 0) or not np.isfinite(coef) or not np.isfinite(se):
            continue
        boot_vals.append(float(coef / se))

    return boot_vals


def assemble_output(measure: str, base_result, boot_vals: List[float]) -> Dict[str, object]:
    coef = float(base_result.params.get("Intercept", np.nan))
    t_obs = float(base_result.tvalues.get("Intercept", np.nan))
    boot_array = np.array([val for val in boot_vals if np.isfinite(val)], dtype=float)
    if boot_array.size > 0 and np.isfinite(t_obs):
        p_wild = (np.sum(np.abs(boot_array) >= abs(t_obs)) + 1) / (boot_array.size + 1)
        n_boot = int(boot_array.size)
    else:
        p_wild = np.nan
        n_boot = int(boot_array.size)
    return {
        "measure": measure,
        "coef": coef,
        "t_cluster": t_obs,
        "p_wild": p_wild,
        "n_boot": n_boot,
    }


def write_notes(path: Path, results: List[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for res in results:
            fp.write(
                f"{res['measure']}: coef={res['coef']:.6f}, p_wild={res['p_wild']:.4f}, n_boot={res['n_boot']}\n"
            )


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
        raise ValueError("Number of bootstrap replications must be positive.")

    panel_df = load_panel(panel_path)
    results_summary: List[Dict[str, object]] = []

    for measure in MEASURES:
        df_filtered = filter_panel(panel_df, measure, pre_range, post_range)
        if df_filtered.empty:
            raise RuntimeError(f"No valid observations for measure {measure} in specified ranges.")

        collapsed = collapse_mean(df_filtered, measure, pre_range, post_range)
        if collapsed.empty:
            raise RuntimeError(f"No tickers have both pre and post observations for {measure}.")

        base_result = fit_model(collapsed)
        boot_vals = wild_cluster_bootstrap(collapsed, base_result, args.B, args.seed)

        summary_row = assemble_output(measure, base_result, boot_vals)
        results_summary.append(summary_row)

    write_notes(Path("notes_two_period_did.txt"), results_summary)


if __name__ == "__main__":
    main()

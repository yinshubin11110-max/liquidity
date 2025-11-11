from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
POST_GROUPS: List[str] = ["post_0_3", "post_4_6", "post_7_9"]
GROUP_MAP: Dict[str, List[int]] = {
    "pre": list(range(-9, -3)),
    "post_0_3": list(range(0, 4)),
    "post_4_6": list(range(4, 7)),
    "post_7_9": list(range(7, 10)),
    "post_all": list(range(0, 10)),
}


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collapsed event-study with logit(cs_spread) and wild bootstrap.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--kmin", type=int, default=-9, help="Lower bound for event window (inclusive).")
    parser.add_argument("--kmax", type=int, default=9, help="Upper bound for event window (inclusive).")
    parser.add_argument("--baseline", type=int, default=-1, help="Reference event month (default: -1).")
    parser.add_argument("--B", type=int, default=999, help="Number of bootstrap replications.")
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


def filter_and_transform(df: pd.DataFrame, kmin: int, kmax: int) -> pd.DataFrame:
    required = {"k", "ticker", "month", "cs_spread"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.dropna(subset=list(required)).copy()
    df = df[df["k"].between(kmin, kmax)]
    if df.empty:
        raise ValueError("No cs_spread observations in the requested k window.")

    epsilon = 1e-6
    clipped = df["cs_spread"].clip(lower=epsilon, upper=1 - epsilon)
    df["cs_logit"] = np.log(clipped / (1 - clipped))
    df["k"] = df["k"].astype(int)
    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    return df


def build_design(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for group, values in GROUP_MAP.items():
        df[group] = df["k"].isin(values).astype(int)
    return df


def compute_weights(df: pd.DataFrame) -> Dict[str, float]:
    weights = {term: 0.0 for term in POST_GROUPS + ["pre"]}
    total = float(df[POST_GROUPS].sum().sum())
    if total <= 0:
        return weights
    for term in POST_GROUPS:
        weights[term] = float(df[term].sum()) / total
    weights["pre"] = 0.0
    return weights


def fit_model(df: pd.DataFrame) -> tuple:
    terms = ["pre"] + POST_GROUPS
    formula = f"cs_logit ~ {' + '.join(terms)} + C(ticker) + C(month)"
    model = smf.ols(formula, data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result, terms


def wild_bootstrap(
    df: pd.DataFrame,
    terms: List[str],
    base_result,
    B: int,
    seed: int,
    weights: Dict[str, float],
) -> tuple[Dict[str, List[float]], List[float]]:
    rng = np.random.default_rng(seed)
    df = df.copy()
    tickers = df["ticker"].to_numpy()
    unique_tickers = df["ticker"].unique()
    ticker_index = {ticker: idx for idx, ticker in enumerate(unique_tickers)}
    group_indices = np.vectorize(ticker_index.get)(tickers)

    residuals = base_result.resid.to_numpy()
    fitted = base_result.fittedvalues.to_numpy()

    boot_t: Dict[str, List[float]] = {term: [] for term in terms}
    post_all_t: List[float] = []
    weight_vec = np.array([weights.get(term, 0.0) for term in terms], dtype=float)

    for _ in range(B):
        signs = rng.choice([-1.0, 1.0], size=len(unique_tickers))
        weights_cluster = signs[group_indices]
        y_star = fitted + residuals * weights_cluster

        df_boot = df.copy()
        df_boot["cs_logit"] = y_star

        boot_model = smf.ols(
            f"cs_logit ~ {' + '.join(terms)} + C(ticker) + C(month)",
            data=df_boot,
        )
        try:
            boot_result = boot_model.fit(cov_type="cluster", cov_kwds={"groups": df_boot["ticker"]})
        except Exception:
            continue

        try:
            params_vec = np.array([boot_result.params[term] for term in terms], dtype=float)
            t_vec = np.array([boot_result.tvalues[term] for term in terms], dtype=float)
        except KeyError:
            continue
        if not (np.all(np.isfinite(params_vec)) and np.all(np.isfinite(t_vec))):
            continue

        for term, t_val in zip(terms, t_vec):
            boot_t[term].append(float(t_val))

        try:
            cov_sub = boot_result.cov_params().loc[terms, terms].values
        except KeyError:
            continue
        if not np.all(np.isfinite(cov_sub)):
            continue

        comb_var = float(weight_vec @ cov_sub @ weight_vec)
        if comb_var <= 0 or not np.isfinite(comb_var):
            continue
        comb_coef = float(np.dot(weight_vec, params_vec))
        comb_t = comb_coef / np.sqrt(comb_var)
        if np.isfinite(comb_t):
            post_all_t.append(comb_t)

    return boot_t, post_all_t


def assemble_results(base_result, terms: List[str], boot_t: Dict[str, List[float]]) -> pd.DataFrame:
    rows = []
    for term in terms:
        coef = float(base_result.params.get(term, np.nan))
        t_obs = float(base_result.tvalues.get(term, np.nan))
        boot_vals = np.array(boot_t.get(term, []), dtype=float)
        boot_vals = boot_vals[np.isfinite(boot_vals)]
        if boot_vals.size > 0 and np.isfinite(t_obs):
            p_wild = (np.sum(np.abs(boot_vals) >= abs(t_obs)) + 1) / (boot_vals.size + 1)
            n_boot = int(boot_vals.size)
        else:
            p_wild = np.nan
            n_boot = int(boot_vals.size)

        rows.append(
            {
                "term": term,
                "coef": coef,
                "t_cluster": t_obs,
                "p_wild": p_wild,
                "n_boot": n_boot,
            }
        )
    return pd.DataFrame(rows)


def compute_post_all_row(base_result, terms: List[str], weights: Dict[str, float], post_all_t: List[float]) -> Dict[str, object]:
    weight_vec = np.array([weights.get(term, 0.0) for term in terms], dtype=float)
    params_vec = np.array([base_result.params.get(term, np.nan) for term in terms], dtype=float)
    coef = float(np.dot(weight_vec, params_vec))
    try:
        cov_sub = base_result.cov_params().loc[terms, terms].values
        if np.all(np.isfinite(cov_sub)):
            se = float(np.sqrt(weight_vec @ cov_sub @ weight_vec))
        else:
            se = np.nan
    except KeyError:
        se = np.nan
    t_obs = coef / se if np.isfinite(se) and se != 0 else np.nan

    boot_vals = np.array([val for val in post_all_t if np.isfinite(val)], dtype=float)
    if boot_vals.size > 0 and np.isfinite(t_obs):
        p_wild = (np.sum(np.abs(boot_vals) >= abs(t_obs)) + 1) / (boot_vals.size + 1)
        n_boot = int(boot_vals.size)
    else:
        p_wild = np.nan
        n_boot = int(boot_vals.size)

    return {
        "term": "post_all",
        "coef": coef,
        "t_cluster": t_obs,
        "p_wild": p_wild,
        "n_boot": n_boot,
    }


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
    df = filter_and_transform(panel_df, args.kmin, args.kmax)
    df_design = build_design(df)
    weights = compute_weights(df_design)

    base_result, terms = fit_model(df_design)
    boot_t, post_all_t = wild_bootstrap(df_design, terms, base_result, args.B, args.seed, weights)

    results = assemble_results(base_result, terms, boot_t)
    post_all_row = compute_post_all_row(base_result, terms, weights, post_all_t)
    combined = pd.concat([results, pd.DataFrame([post_all_row])], ignore_index=True)
    combined.to_csv("collapse_wild_cs_logit.csv", index=False)


if __name__ == "__main__":
    main()

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
    parser = argparse.ArgumentParser(description="Permutation test for ATT with firm-level event-month shuffling.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--pre", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive pre-event k range.")
    parser.add_argument("--post", nargs=2, type=int, metavar=("K_MIN", "K_MAX"), required=True, help="Inclusive post-event k range.")
    parser.add_argument("--B", type=int, default=5000, help="Number of permutations.")
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


def compute_deltas(df: pd.DataFrame, measure: str, k_column: str, pre_range: Tuple[int, int], post_range: Tuple[int, int]) -> np.ndarray:
    pre_min, pre_max = pre_range
    post_min, post_max = post_range

    deltas: List[float] = []
    for _, group in df.groupby("ticker", observed=True):
        k_values = group[k_column]
        pre_vals = group.loc[(k_values >= pre_min) & (k_values <= pre_max), measure]
        post_vals = group.loc[(k_values >= post_min) & (k_values <= post_max), measure]
        if not pre_vals.empty and not post_vals.empty:
            deltas.append(post_vals.mean() - pre_vals.mean())
    return np.array(deltas, dtype=float)


def permute_event_months(
    df: pd.DataFrame,
    ticker_ids: np.ndarray,
    event_ordinals: np.ndarray,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    perm = rng.permutation(len(event_ordinals))
    perm_event_ord = event_ordinals[perm]
    k_perm = df["month_ord"].to_numpy() - perm_event_ord[ticker_ids]
    return k_perm, perm


def permutation_p_value(observed: float, samples: np.ndarray) -> float:
    samples = samples[np.isfinite(samples)]
    if samples.size == 0 or not np.isfinite(observed):
        return np.nan
    extreme = np.sum(np.abs(samples) >= abs(observed))
    return (extreme + 1) / (samples.size + 1)


def prepare_panel(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = {"ticker", "month", "event_month", "k", "amihud", "cs_spread"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.copy()
    df["ticker"] = df["ticker"].astype(str)
    df["month_period"] = pd.PeriodIndex(df["month"], freq="M")
    df["event_month_period"] = pd.PeriodIndex(df["event_month"], freq="M")
    df["month_ord"] = df["month_period"].astype("int64")
    df["event_month_ord"] = df["event_month_period"].astype("int64")
    df["k"] = df["k"].astype(int)
    return df


def build_permutation_results(
    df: pd.DataFrame,
    pre_range: Tuple[int, int],
    post_range: Tuple[int, int],
    B: int,
    seed: int,
) -> Tuple[Dict[str, float], Dict[str, np.ndarray], Dict[str, List[str]], Dict[str, np.ndarray]]:
    df = prepare_panel(df)
    rng = np.random.default_rng(seed)

    ticker_cat = df["ticker"].astype("category")
    df["ticker_id"] = ticker_cat.cat.codes
    ticker_list = list(ticker_cat.cat.categories)

    event_month_info = (
        df.drop_duplicates("ticker")[["ticker", "event_month_ord", "event_month_period"]]
        .set_index("ticker")
        .loc[ticker_list]
    )
    event_month_ord = event_month_info["event_month_ord"].to_numpy()
    event_month_periods = event_month_info["event_month_period"].to_numpy()

    observed_att: Dict[str, float] = {}
    perm_dists: Dict[str, np.ndarray] = {}

    for measure in MEASURES:
        deltas = compute_deltas(df, measure, "k", pre_range, post_range)
        if deltas.size == 0:
            raise RuntimeError(f"No valid ticker-level deltas for {measure}.")
        observed_att[measure] = float(np.mean(deltas))
        perm_dists[measure] = np.zeros(B, dtype=float)

    ticker_ids = df["ticker_id"].to_numpy()
    first_perm_mapping: Dict[str, List[str]] = {"ticker": ticker_list, "control_event_month": [], "control_source_ticker": []}
    first_perm_indices: np.ndarray | None = None

    for b in range(B):
        k_perm, perm_indices = permute_event_months(df, ticker_ids, event_month_ord, rng)
        df["k_perm"] = k_perm

        for measure in MEASURES:
            deltas_perm = compute_deltas(df, measure, "k_perm", pre_range, post_range)
            perm_dists[measure][b] = np.mean(deltas_perm) if deltas_perm.size else np.nan

        if b == 0:
            first_perm_indices = perm_indices
            assigned_event_periods = event_month_periods[perm_indices]
            control_event_months = [str(period) for period in assigned_event_periods]
            source_tickers = [ticker_list[idx] for idx in perm_indices]
            first_perm_mapping["control_event_month"] = control_event_months
            first_perm_mapping["control_source_ticker"] = source_tickers

    if first_perm_indices is None:
        raise RuntimeError("Permutation loop did not execute.")

    assigned_event_ord = event_month_ord[first_perm_indices]
    assigned_event_dict = {ticker_list[i]: assigned_event_ord[i] for i in range(len(ticker_list))}

    return observed_att, perm_dists, first_perm_mapping, {
        "assigned_event_ord": assigned_event_dict,
    }


def run_did_cs_post(
    df: pd.DataFrame,
    perm_info: Dict[str, np.ndarray],
) -> Tuple[float, float, float]:
    assigned_event_dict = perm_info["assigned_event_ord"]

    df = prepare_panel(df)
    df["post_all"] = (df["k"] >= 0).astype(int)
    treated_df = df[["ticker", "month", "cs_spread", "post_all"]].copy()
    treated_df["treated"] = 1

    assigned_event_ord_arr = df["ticker"].map(assigned_event_dict).to_numpy()
    post_all_perm = (df["month_ord"].to_numpy() - assigned_event_ord_arr >= 0).astype(int)

    control_df = df[["ticker", "month", "cs_spread"]].copy()
    control_df["post_all"] = post_all_perm
    control_df["treated"] = 0
    control_df["ticker"] = control_df["ticker"] + "_CTRL"

    analysis_df = pd.concat(
        [
            treated_df.rename(columns={"cs_spread": "value"}),
            control_df.rename(columns={"cs_spread": "value"}),
        ],
        ignore_index=True,
    )
    analysis_df = analysis_df.dropna(subset=["value", "treated", "post_all", "ticker", "month"])

    model = smf.ols("value ~ treated * post_all + C(ticker) + C(month)", data=analysis_df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": analysis_df["ticker"]})
    coef = float(result.params.get("treated:post_all", np.nan))
    t_value = float(result.tvalues.get("treated:post_all", np.nan))
    p_value = float(result.pvalues.get("treated:post_all", np.nan))
    return coef, t_value, p_value


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
        raise ValueError("Number of permutations must be positive.")

    panel_df = load_panel(panel_path)

    observed_att, perm_dists, first_perm_mapping, perm_info = build_permutation_results(
        panel_df,
        pre_range,
        post_range,
        args.B,
        args.seed,
    )

    permtest_rows = []
    for measure in MEASURES:
        obs = observed_att[measure]
        dist = perm_dists[measure]
        p_val = permutation_p_value(obs, dist)
        permtest_rows.append(
            {
                "measure": measure,
                "att_observed": obs,
                "perm_mean": float(np.nanmean(dist)),
                "perm_std": float(np.nanstd(dist, ddof=1)),
                "two_sided_p": p_val,
                "n_perm": int(np.isfinite(dist).sum()),
            }
        )
    pd.DataFrame(permtest_rows).to_csv("permtest_results.csv", index=False)

    controls_df = pd.DataFrame(
        {
            "ticker": first_perm_mapping["ticker"],
            "control_event_month": first_perm_mapping["control_event_month"],
            "control_source_ticker": first_perm_mapping["control_source_ticker"],
        }
    )
    controls_df.to_csv("controls_matches.csv", index=False)

    coef, t_value, p_value = run_did_cs_post(panel_df, perm_info)
    did_df = pd.DataFrame(
        [
            {
                "term": "treated:post_all",
                "beta": coef,
                "t_value": t_value,
                "p_value": p_value,
            }
        ]
    )
    did_df.to_csv("did_cs_postall.csv", index=False)


if __name__ == "__main__":
    main()

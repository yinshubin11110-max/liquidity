from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm


def parse_dates(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, format="%b-%y", errors="coerce")
    if dt.isna().any():
        dt_alt = pd.to_datetime(series, errors="coerce")
        dt = dt.fillna(dt_alt)
    if dt.isna().any():
        raise ValueError("Failed to parse dates in column.")
    return dt


def read_panel(path: str | Path) -> pd.DataFrame:
    encs = ["utf-8-sig", "utf-8", "cp1250", "latin-1"]
    last_err: Exception | None = None
    for enc in encs:
        try:
            df = pd.read_csv(path, encoding=enc)
            df["month"] = parse_dates(df["month"])
            df["event_month"] = parse_dates(df["event_month"])
            df["k"] = pd.to_numeric(df["k"], errors="coerce").astype("Int64")
            return df
        except Exception as err:  # noqa: BLE001
            last_err = err
    raise RuntimeError(f"Failed to read {path}") from last_err


def ensure_baseline(df: pd.DataFrame, baseline: int, kmin: int) -> int:
    counts = df["k"].value_counts(dropna=True)
    if counts.get(baseline, 0) == 0:
        negatives = sorted([k for k in counts.index if pd.notna(k) and k < 0])
        negatives = [k for k in negatives if k >= kmin]
        if not negatives:
            raise ValueError("No negative k available for baseline.")
        new_baseline = negatives[-1]
        print(f"[WARN] No observations at k={baseline}; using k={new_baseline} as baseline.")
        return new_baseline
    return baseline


def make_k(df: pd.DataFrame, g: pd.Timestamp) -> pd.Series:
    month_ord = df["month"].dt.to_period("M").astype("int64")
    g_ord = g.to_period("M").ordinal
    return month_ord - g_ord


def build_design(tmp: pd.DataFrame, ks: list[int]) -> pd.DataFrame:
    X = pd.get_dummies(tmp["ticker"], prefix="i", drop_first=True, dtype=float)
    krel = pd.get_dummies(tmp["k_g"], prefix="krel", drop_first=True, dtype=float)
    X = X.join(krel, how="left")
    for k in ks:
        X[f"Dg_k{k}"] = ((tmp["Tg"] == 1) & (tmp["k_g"] == k)).astype(float)
    return sm.add_constant(X, has_constant="add")


def stacked_one_cohort(
    df: pd.DataFrame,
    g: pd.Timestamp,
    kmin: int,
    kmax: int,
    ycol: str,
    baseline: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    tmp = df.copy()
    tmp["k_g"] = make_k(tmp, g).astype(int)
    tmp = tmp[(tmp["k_g"] >= kmin) & (tmp["k_g"] <= kmax)]
    tmp = tmp.dropna(subset=[ycol])
    tmp = tmp[~((tmp["event_month"] < g) & (tmp["k_g"] >= 0))]
    tmp["Tg"] = (tmp["event_month"] == g).astype(int)
    if tmp.empty:
        return pd.DataFrame(columns=["cohort", "k", "att", "se", "N", "treated_obs"]), {}

    ks = list(range(kmin, kmax + 1))
    if baseline in ks:
        ks.remove(baseline)

    X = build_design(tmp, ks)
    y = tmp[ycol].astype(float).values

    try:
        m = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": tmp["ticker"]})
    except np.linalg.LinAlgError:
        return pd.DataFrame(columns=["cohort", "k", "att", "se", "N", "treated_obs"]), {}

    rows = []
    for k in ks:
        treated_obs = int(((tmp["Tg"] == 1) & (tmp["k_g"] == k)).sum())
        coef_name = f"Dg_k{k}"
        if treated_obs == 0 or coef_name not in m.params:
            continue
        b = m.params.get(coef_name, np.nan)
        se = m.bse.get(coef_name, np.nan)
        rows.append(
            {
                "cohort": str(g.date()),
                "k": k,
                "att": b,
                "se": se,
                "N": len(tmp),
                "treated_obs": treated_obs,
            }
        )

    Dpost = ((tmp["Tg"] == 1) & (tmp["k_g"] >= 0)).astype(float).values
    Xpost = pd.get_dummies(tmp["ticker"], drop_first=True, dtype=float).join(
        pd.get_dummies(tmp["k_g"], prefix="krel", drop_first=True, dtype=float),
        how="left",
    )
    Xpost = sm.add_constant(Xpost, has_constant="add")
    Xpost["Post"] = Dpost
    try:
        m2 = sm.OLS(y, Xpost).fit(cov_type="cluster", cov_kwds={"groups": tmp["ticker"]})
        b2 = m2.params.get("Post", np.nan)
        se2 = m2.bse.get("Post", np.nan)
    except np.linalg.LinAlgError:
        post_row = {}
    else:
        if pd.notna(b2) and pd.notna(se2):
            treated_obs_post = int(((tmp["Tg"] == 1) & (tmp["k_g"] >= 0)).sum())
            post_row = {
                "cohort": str(g.date()),
                "att_post": b2,
                "se_post": se2,
                "N": len(tmp),
                "treated_obs": treated_obs_post,
            }
        else:
            post_row = {}

    return pd.DataFrame(rows), post_row


def weight_avg(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["w"] = df["N"] / df["N"].sum()

    rows = []
    if keys:
        iterator = df.groupby(keys, sort=True)
    else:
        iterator = [((), df)]

    for key_vals, group in iterator:
        if not isinstance(key_vals, tuple):
            key_vals = (key_vals,)
        att = np.average(group["att"], weights=group["w"])
        se = np.sqrt(np.average(group["se"] ** 2, weights=group["w"] ** 2))
        row = {key: val for key, val in zip(keys, key_vals)}
        row.update(
            {
                "att": att,
                "se": se,
                "t": att / se if se not in (None, 0) else np.nan,
                "n_cohorts": group["cohort"].nunique(),
                "treated_obs": group["treated_obs"].sum() if "treated_obs" in group else np.nan,
                "total_N": group["N"].sum(),
            }
        )
        rows.append(row)

    return pd.DataFrame(rows)


def plot_k(summ: pd.DataFrame, outpng: Path, title: str) -> None:
    summ = (
        summ.replace([np.inf, -np.inf], np.nan)
        .dropna(subset=["k", "att", "se"])
        .sort_values("k")
    )
    if summ.empty:
        print("WARN: no k-path points to plot.")
        return

    ci = 1.96 * summ["se"]
    plt.figure(figsize=(7, 4.2))
    plt.errorbar(summ["k"], summ["att"], yerr=ci, fmt="o-", capsize=3)
    plt.axhline(0, ls="--", lw=1)
    plt.axvline(0, ls=":", lw=1)
    plt.title(title)
    plt.xlabel("Event time k (months)")
    plt.ylabel("ATT")
    plt.tight_layout()
    plt.savefig(outpng, dpi=200)


def run_stacked(
    panel_path: str | Path,
    ycol: str,
    kmin: int,
    kmax: int,
    baseline: int,
) -> tuple[int, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return run_stacked_subset(panel_path, ycol, kmin, kmax, baseline, None)


def run_stacked_subset(
    panel_path: str | Path,
    ycol: str,
    kmin: int,
    kmax: int,
    baseline: int,
    tickers: list[str] | None,
) -> tuple[int, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = read_panel(panel_path)
    if tickers:
        df = df[df["ticker"].isin(tickers)].copy()
        if df.empty:
            raise ValueError("Ticker subset is empty after filtering.")
    actual_baseline = ensure_baseline(df, baseline, kmin)
    cohorts = df[["ticker", "event_month"]].drop_duplicates().rename(columns={"event_month": "g"})

    kp_list: list[pd.DataFrame] = []
    post_list: list[dict[str, object]] = []

    for g, _ in cohorts.groupby("g"):
        kdf, post = stacked_one_cohort(df, g, kmin, kmax, ycol, actual_baseline)
        if not kdf.empty:
            kp_list.append(kdf)
        if post:
            post_list.append(post)

    if not kp_list:
        raise RuntimeError("No cohort regressions succeeded; check data window.")

    k_all = pd.concat(kp_list, ignore_index=True)
    p_all = pd.DataFrame(post_list).rename(columns={"att_post": "att", "se_post": "se"})
    k_summ = weight_avg(k_all, ["k"])
    p_summ = weight_avg(p_all, [])

    return actual_baseline, k_all, k_summ, p_all, p_summ


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="pwp_monthly_panel.csv")
    ap.add_argument("--y", default="cs_spread", choices=["cs_spread", "amihud"])
    ap.add_argument("--kmin", type=int, default=-9)
    ap.add_argument("--kmax", type=int, default=9)
    ap.add_argument("--baseline", type=int, default=-1)
    args = ap.parse_args()

    Path("results").mkdir(exist_ok=True)
    baseline, k_all, k_summ, p_all, p_summ = run_stacked(
        args.panel, args.y, args.kmin, args.kmax, args.baseline
    )

    k_all.to_csv(f"results/stackeddid_{args.y}_kpath_cohorts.csv", index=False)
    k_summ.to_csv(f"results/stackeddid_{args.y}_kpath_summary.csv", index=False)
    p_all.to_csv(f"results/stackeddid_{args.y}_post_cohorts.csv", index=False)
    p_summ.to_csv(f"results/stackeddid_{args.y}_post_summary.csv", index=False)

    plot_k(k_summ, Path(f"results/fig_stackeddid_{args.y}_kpath.png"), f"Stacked DID k-path ({args.y})")

    k_counts = k_all.groupby("k")["treated_obs"].sum().sort_index()
    print(f"Baseline used: k={baseline}")
    print("Treated obs per k within window:")
    print(k_counts)


if __name__ == "__main__":
    main()

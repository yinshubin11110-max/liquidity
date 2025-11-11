"""
Comprehensive liquidity risk premium analysis toolkit.

This module implements the empirical workflow described in the proposal:

1. Load daily and monthly stock-level data from Excel files.
2. Construct Pastor-Stambaugh, Quoted Spread, and Amihud liquidity measures.
3. Build liquidity-sorted portfolios (overall and by size segment) and compute returns.
4. Derive a principal component liquidity factor and optional composite factor.
5. Estimate augmented Fama-French three-factor regressions with liquidity factors.
6. Run fixed-effects panel regressions with two-way clustered standard errors.
7. Execute the rolling-window Fama-MacBeth cross-sectional pricing tests.
8. Provide predictive regressions to evaluate out-of-sample liquidity forecasting power.

The code assumes the researcher already exported the required daily observations
into Excel files. Carefully review the expected column names in `EXPECTED_COLUMNS`
and adjust the mappings if the raw data differs.

Usage example (run from terminal):
-----------------------------------------------------------------------
python liquidity_analysis_pipeline.py ^
    --daily-path data/daily_ticks.xlsx ^
    --monthly-path data/monthly_characteristics.xlsx ^
    --ff-path data/ff_factors.xlsx ^
    --output-dir results
-----------------------------------------------------------------------

The pipeline creates intermediate parquet/csv files inside `output_dir` so the
researcher can inspect each step before moving forward.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
from linearmodels.panel import PanelOLS
from sklearn.decomposition import PCA
from statsmodels.api import OLS, add_constant

# --------------------------- configuration --------------------------------- #

EXPECTED_COLUMNS = {
    "date": "date",  # Trading date (daily frequency)
    "ticker": "ticker",  # Stock identifier
    "return": "return",  # Daily simple return already in decimal form
    "market_return": "market_return",  # Daily market return (e.g., WIG20)
    "rf": "rf",  # Daily (or interpolated) risk-free rate
    "bid": "bid",  # Closing bid quote
    "ask": "ask",  # Closing ask quote
    "midpoint": "midpoint",  # Mid-price; if absent it will be imputed
    "dollar_volume": "dollar_volume",  # Price * volume, in base currency
    "volume": "volume",  # Raw volume (number of shares)
    "segment": "segment",  # Size segment label: WIG20 / mWIG40 / sWIG80
    "market_cap": "market_cap",  # End-of-month market capitalisation
    "book_to_market": "book_to_market",  # Book-to-market ratio
}


@dataclass
class LiquidityAnalysisConfig:
    """Centralised configuration for the analysis pipeline."""

    daily_path: Path
    monthly_path: Optional[Path] = None
    ff_factors_path: Optional[Path] = None
    sheet_name: Optional[str] = None
    rolling_beta_window: int = 36  # months for time-series beta estimation
    liquidity_quantiles: int = 5
    pca_components: int = 1
    output_dir: Path = Path("results")
    write_intermediate: bool = True

    def ensure_output_dir(self) -> None:
        if self.write_intermediate:
            self.output_dir.mkdir(parents=True, exist_ok=True)


# ----------------------------- I/O helpers ---------------------------------- #

def load_excel(path: Path, sheet: Optional[str] = None) -> pd.DataFrame:
    """Load an Excel file and enforce datetime ordering."""

    logging.info("Loading Excel file: %s", path)
    df = pd.read_excel(path, sheet_name=sheet)
    if "date" not in df.columns:
        raise ValueError("Input data must contain a 'date' column.")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Fill midpoint if absent
    if "midpoint" not in df.columns and {"bid", "ask"} <= set(df.columns):
        df["midpoint"] = (df["bid"] + df["ask"]) / 2

    return df


def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to the expected internal keywords."""

    column_map = {v: k for k, v in EXPECTED_COLUMNS.items() if v in df.columns}
    df = df.rename(columns=column_map)
    missing = [key for key in ("date", "ticker", "return", "market_return", "rf") if key not in df.columns]
    if missing:
        raise ValueError(f"Missing critical columns: {missing}")
    return df


# -------------------------- Liquidity measures ------------------------------ #

def compute_intraday_liquidity_measures(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily Quoted Spread (QS) and Amihud (AMH) measures.

    QS_i,t = mean_t [(Ask - Bid) / Midpoint]
    AMH_i,t = mean_t [ |r_i,t| / dollar_volume_i,t ]
    """

    df = df.copy()
    if {"ask", "bid"} <= set(df.columns):
        df["quoted_spread"] = np.abs(df["ask"] - df["bid"]) / df["midpoint"]
    else:
        raise ValueError("Quoted spread requires 'ask' and 'bid' columns.")

    if "dollar_volume" not in df.columns:
        if {"midpoint", "volume"} <= set(df.columns):
            df["dollar_volume"] = df["midpoint"] * df["volume"]
        else:
            raise ValueError("Amihud measure requires 'dollar_volume' or (midpoint & volume).")

    df["amihud"] = df["return"].abs() / df["dollar_volume"].replace(0, np.nan)
    return df


def estimate_pastor_stambaugh_gamma(df: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate the Pastor-Stambaugh (2003) liquidity innovation gamma for each stock-month.

    r_{i,d+1} - r_{m,d+1} = α_i + β_i (r_{i,d} - r_{m,d}) + γ_i sign(r_{i,d}) Δvol_{i,d} + ε_{i,d}.
    """

    df = df.copy()
    df["ret_excess"] = df["return"] - df["market_return"]
    df["ret_excess_lead"] = df.groupby("ticker")["ret_excess"].shift(-1)
    df["ret_excess_lag"] = df.groupby("ticker")["ret_excess"].shift(1)
    df["volume_diff"] = df.groupby("ticker")["volume"].diff()
    df["sign_term"] = np.sign(df["ret_excess"])
    df["interaction"] = df["sign_term"] * df["volume_diff"]
    df["month"] = df["date"].dt.to_period("M")

    records = []
    for (ticker, month), panel in df.groupby(["ticker", "month"], observed=True):
        panel = panel.dropna(subset=["ret_excess_lead", "ret_excess_lag", "interaction"])
        if len(panel) < 10:
            continue

        y = panel["ret_excess_lead"]
        X = add_constant(
            pd.DataFrame(
                {
                    "ret_excess_lag": panel["ret_excess_lag"],
                    "interaction": panel["interaction"],
                }
            )
        )
        try:
            model = OLS(y, X, missing="drop").fit()
            records.append(
                {
                    "ticker": ticker,
                    "month": month,
                    "pastor_stambaugh_gamma": model.params.get("interaction", np.nan),
                }
            )
        except np.linalg.LinAlgError:
            continue

    gamma_df = pd.DataFrame.from_records(records)
    if gamma_df.empty:
        raise RuntimeError("No valid Pastor-Stambaugh estimates produced. Check input data.")

    return gamma_df


def aggregate_liquidity_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily liquidity measures to monthly averages."""

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    monthly = (
        df.groupby(["ticker", "month"], observed=True)[["quoted_spread", "amihud"]]
        .mean()
        .reset_index()
    )
    return monthly


def compute_monthly_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert daily returns into monthly simple returns."""

    df = df.copy()
    df["month"] = df["date"].dt.to_period("M")
    agg = (
        df.groupby(["ticker", "month"], observed=True)
        .apply(lambda x: np.prod(1 + x["return"]) - 1)
        .reset_index(name="monthly_return")
    )

    market = (
        df.groupby("month", observed=True)
        .apply(lambda x: np.prod(1 + x["market_return"]) - 1)
        .rename("market_return")
    )
    rf = (
        df.groupby("month", observed=True)
        .apply(lambda x: np.prod(1 + x["rf"]) - 1)
        .rename("rf_monthly")
    )
    agg = agg.merge(market, on="month")
    agg = agg.merge(rf, on="month")

    return agg


# --------------------------- Portfolio sorting ------------------------------ #

def assign_liquidity_quantiles(
    liquidity_df: pd.DataFrame,
    measure: str,
    quantiles: int,
) -> pd.DataFrame:
    """Assign each stock-month to a liquidity quantile portfolio."""

    liquidity_df = liquidity_df.copy()
    liquidity_df["portfolio"] = (
        liquidity_df.groupby("month", observed=True)[measure]
        .apply(lambda s: pd.qcut(s.rank(method="first"), quantiles, labels=False) + 1)
    )
    liquidity_df["measure"] = measure
    return liquidity_df


def build_liquidity_portfolios(
    monthly_returns: pd.DataFrame,
    liquidity_measures: pd.DataFrame,
    quantiles: int,
    segment_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Construct equal-weighted liquidity-sorted portfolio returns.

    When `segment_col` is provided, portfolios are formed separately by segment.
    """

    merged = monthly_returns.merge(liquidity_measures, on=["ticker", "month"], how="inner")
    if segment_col and segment_col in monthly_returns.columns:
        merged_segment = merged.copy()
        merged_segment["segment"] = merged_segment[segment_col]
        grouping_cols = ["segment", "measure", "month", "portfolio"]
    else:
        merged_segment = merged
        grouping_cols = ["measure", "month", "portfolio"]

    portfolio_returns = (
        merged_segment.groupby(grouping_cols, observed=True)["monthly_return"]
        .mean()
        .rename("portfolio_return")
        .reset_index()
    )

    return portfolio_returns


# --------------------------- Fama-French factors ---------------------------- #

def compute_ff_factors(
    monthly_df: pd.DataFrame,
    size_column: str = "market_cap",
    value_column: str = "book_to_market",
) -> pd.DataFrame:
    """
    Compute SMB and HML factors following Fama-French (1993).

    `monthly_df` must include monthly returns plus size and book-to-market.
    """

    required = {"ticker", "month", "monthly_return", size_column, value_column}
    missing = required.difference(monthly_df.columns)
    if missing:
        raise ValueError(f"Missing columns for Fama-French factors: {missing}")

    factors = []
    for month, group in monthly_df.groupby("month", observed=True):
        group = group.dropna(subset=[size_column, value_column, "monthly_return"])
        if len(group) < 30:
            continue

        size_cut = group[size_column].median()
        value_low = group[value_column].quantile(0.3)
        value_high = group[value_column].quantile(0.7)

        big = group[group[size_column] >= size_cut]
        small = group[group[size_column] < size_cut]
        high = group[group[value_column] >= value_high]
        low = group[group[value_column] <= value_low]
        mid = group[(group[value_column] > value_low) & (group[value_column] < value_high)]

        smb = (
            small["monthly_return"].mean() - big["monthly_return"].mean()
        )
        hml = (
            high["monthly_return"].mean() - low["monthly_return"].mean()
        )

        factors.append({"month": month, "SMB": smb, "HML": hml})

    return pd.DataFrame(factors)


def derive_liquidity_factor(
    liquidity_df: pd.DataFrame,
    columns: Iterable[str],
    n_components: int = 1,
) -> pd.DataFrame:
    """Construct a composite liquidity factor via PCA."""

    liquidity_df = liquidity_df.copy()
    features = liquidity_df[list(columns)].dropna()
    if features.empty:
        raise ValueError("No valid observations for PCA.")

    features_standardised = (features - features.mean()) / features.std(ddof=0)
    pca = PCA(n_components=n_components)
    principal_components = pca.fit_transform(features_standardised)

    result = liquidity_df.loc[features.index, ["ticker", "month"]].copy()
    result["LIQ"] = principal_components[:, 0]
    return result


# ----------------------- Regression specifications -------------------------- #

def run_three_factor_regression(
    portfolios: pd.DataFrame,
    factor_returns: pd.DataFrame,
    rf_column: str = "rf_monthly",
) -> pd.DataFrame:
    """
    Estimate augmented Fama-French regressions for each liquidity portfolio.

    Ri,t - Rf,t = α + βMKT (RM_t - Rf_t) + βSMB SMB_t + βHML HML_t + βLIQ LIQ_t + ε_t
    """

    merged = portfolios.merge(factor_returns, on="month", how="inner")
    if merged.empty:
        raise RuntimeError("No overlap between portfolios and factor returns.")

    outputs = []
    for key, sub in merged.groupby(["measure", "portfolio"], observed=True):
        y = sub["portfolio_return"] - sub[rf_column]
        X = add_constant(sub[["MKT", "SMB", "HML", "LIQ"]])
        model = OLS(y, X, missing="drop").fit()
        coefs = model.params
        tstats = model.tvalues
        outputs.append(
            {
                "measure": key[0],
                "portfolio": key[1],
                "alpha": coefs.get("const"),
                "beta_MKT": coefs.get("MKT"),
                "beta_SMB": coefs.get("SMB"),
                "beta_HML": coefs.get("HML"),
                "beta_LIQ": coefs.get("LIQ"),
                "alpha_t": tstats.get("const"),
                "beta_MKT_t": tstats.get("MKT"),
                "beta_SMB_t": tstats.get("SMB"),
                "beta_HML_t": tstats.get("HML"),
                "beta_LIQ_t": tstats.get("LIQ"),
                "r_squared": model.rsquared,
            }
        )
    return pd.DataFrame(outputs)


def run_fixed_effects_panel(
    monthly_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
) -> PanelOLS:
    """
    Run stock-level fixed effects panel regression with two-way clustered SEs.

    Ri,t - Rf,t = α + βMKT (RM_t - Rf_t) + βSMB SMB_t + βHML HML_t + βLIQ LIQ_t + μ_i + η_t + ε_i,t
    """

    df = monthly_returns.merge(factor_returns, on="month", how="inner")
    df["excess_return"] = df["monthly_return"] - df["rf_monthly"]
    df = df.set_index(["ticker", "month"])

    exog = add_constant(df[["MKT", "SMB", "HML", "LIQ"]])
    model = PanelOLS(
        df["excess_return"],
        exog,
        entity_effects=True,
        time_effects=False,
    )
    results = model.fit(cov_type="clustered", cluster_entity=True, cluster_time=True)
    return results


# --------------------------- Fama-MacBeth test ------------------------------ #

def _run_time_series_beta(
    returns: pd.DataFrame,
    factors: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """Estimate rolling betas for each ticker using a rolling window."""

    betas = []
    returns = returns.set_index(["ticker", "month"]).sort_index()
    factors = factors.set_index("month").sort_index()
    aligned_months = returns.index.get_level_values("month").unique()

    for current_month in aligned_months:
        window_start = current_month - window + 1
        window_months = [m for m in aligned_months if window_start <= m <= current_month]
        if len(window_months) < window:
            continue

        window_returns = returns.loc[(slice(None), window_months), :]
        window_factors = factors.loc[window_months]

        for ticker in window_returns.index.get_level_values(0).unique():
            r = window_returns.xs(ticker, level=0, drop_level=False).droplevel(0)
            merged = r.join(window_factors, how="inner")
            merged = merged.dropna()
            if merged.empty:
                continue

            y = merged["excess_return"]
            X = add_constant(merged[["MKT", "SMB", "HML", "LIQ"]])
            try:
                beta = OLS(y, X).fit().params
            except np.linalg.LinAlgError:
                continue

            betas.append(
                {
                    "ticker": ticker,
                    "month": current_month + 1,  # betas used for next month's cross-section
                    "beta_MKT": beta.get("MKT"),
                    "beta_SMB": beta.get("SMB"),
                    "beta_HML": beta.get("HML"),
                    "beta_LIQ": beta.get("LIQ"),
                }
            )

    return pd.DataFrame(betas)


def fama_macbeth_regression(
    monthly_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """Execute Fama-MacBeth two-pass regression and report lambdas with t-stats."""

    excess_returns = monthly_returns.copy()
    excess_returns["excess_return"] = excess_returns["monthly_return"] - excess_returns["rf_monthly"]

    betas = _run_time_series_beta(excess_returns, factor_returns, window=window)
    merged = monthly_returns.merge(betas, on=["ticker", "month"], how="inner")
    merged["excess_return"] = merged["monthly_return"] - merged["rf_monthly"]

    lambda_series = []
    for month, group in merged.groupby("month", observed=True):
        group = group.dropna(subset=["beta_MKT", "beta_SMB", "beta_HML", "beta_LIQ"])
        if len(group) < 10:
            continue

        y = group["excess_return"]
        X = add_constant(group[["beta_MKT", "beta_SMB", "beta_HML", "beta_LIQ"]])
        model = OLS(y, X).fit()
        lambda_series.append({"month": month, **model.params.to_dict()})

    lambda_df = pd.DataFrame(lambda_series)
    if lambda_df.empty:
        raise RuntimeError("Fama-MacBeth cross-sectional regressions produced no results.")

    avg_lambda = lambda_df.mean(numeric_only=True)
    std_lambda = lambda_df.std(numeric_only=True, ddof=1)
    t_stats = avg_lambda / (std_lambda / np.sqrt(len(lambda_df)))

    summary = pd.DataFrame(
        {
            "lambda": avg_lambda,
            "std_error": std_lambda,
            "t_stat": t_stats,
        }
    )
    summary.index.name = "factor"
    summary = summary.reset_index()
    return summary


# ------------------------ Predictive regressions ---------------------------- #

def predictive_liquidity_regression(
    monthly_returns: pd.DataFrame,
    liquidity_proxy: pd.DataFrame,
) -> pd.DataFrame:
    """
    Run Ri,t+1 = α + γ LIQi,t + δ X_i,t + u_i,t+1 with clustered SEs.

    Here X_i,t can be extended; this function uses market beta as baseline.
    """

    merged = monthly_returns.merge(liquidity_proxy, on=["ticker", "month"], how="inner")
    merged = merged.sort_values(["ticker", "month"])
    merged["future_return"] = merged.groupby("ticker")["monthly_return"].shift(-1)

    merged["excess_future_return"] = merged["future_return"] - merged["rf_monthly"]
    merged = merged.dropna(subset=["excess_future_return", "LIQ"])

    # Use the current period market excess return as control variable (δ X_i,t).
    merged["market_excess"] = merged["market_return"] - merged["rf_monthly"]
    X = add_constant(merged[["LIQ", "market_excess"]])
    y = merged["excess_future_return"]

    model = PanelOLS(
        y,
        X,
        entity_effects=True,
        time_effects=False,
    )
    results = model.fit(cov_type="clustered", cluster_entity=True, cluster_time=True)
    return pd.DataFrame(
        {
            "parameter": results.params.index,
            "coefficient": results.params.values,
            "t_stat": results.tstats.values,
        }
    )


# ------------------------------ Orchestration ------------------------------- #

def build_factor_dataframe(
    ff_factors: pd.DataFrame,
    liquidity_factor: pd.DataFrame,
    market_returns: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble merged factor returns."""

    factor_df = market_returns[["month", "market_return", "rf_monthly"]].drop_duplicates()
    factor_df["MKT"] = factor_df["market_return"] - factor_df["rf_monthly"]
    if "SMB" in ff_factors.columns and "HML" in ff_factors.columns:
        factor_df = factor_df.merge(ff_factors[["month", "SMB", "HML"]], on="month", how="left")
    else:
        raise ValueError("Fama-French factor data must contain SMB and HML.")

    factor_df = factor_df.merge(liquidity_factor[["month", "LIQ"]].drop_duplicates(), on="month", how="left")
    factor_df = factor_df.dropna(subset=["MKT", "SMB", "HML", "LIQ"])
    return factor_df


def run_full_pipeline(config: LiquidityAnalysisConfig) -> None:
    """Execute the entire workflow end-to-end."""

    config.ensure_output_dir()
    raw_daily = load_excel(config.daily_path, sheet=config.sheet_name)
    daily = standardise_columns(raw_daily)

    logging.info("Computing daily liquidity measures.")
    daily_liquidity = compute_intraday_liquidity_measures(daily)
    gamma_monthly = estimate_pastor_stambaugh_gamma(daily_liquidity)
    monthly_liquidity = aggregate_liquidity_monthly(daily_liquidity)

    monthly_returns = compute_monthly_returns(daily)
    monthly_returns = monthly_returns.merge(gamma_monthly, on=["ticker", "month"], how="left")
    liquidity_combined = monthly_liquidity.merge(gamma_monthly, on=["ticker", "month"], how="left")

    if config.monthly_path:
        logging.info("Loading monthly characteristics from %s", config.monthly_path)
        monthly_chars = load_excel(config.monthly_path)
        monthly_chars = standardise_columns(monthly_chars)
        monthly_returns = monthly_returns.merge(
            monthly_chars[
                [
                    "ticker",
                    "month",
                    "segment",
                    "market_cap",
                    "book_to_market",
                ]
            ],
            on=["ticker", "month"],
            how="left",
        )
        liquidity_combined = liquidity_combined.merge(
            monthly_chars[["ticker", "month", "segment"]], on=["ticker", "month"], how="left"
        )

    if config.write_intermediate:
        daily_liquidity.to_parquet(config.output_dir / "daily_liquidity.parquet")
        liquidity_combined.to_parquet(config.output_dir / "monthly_liquidity.parquet")

    liquidity_measures = liquidity_combined[
        ["ticker", "month", "quoted_spread", "amihud", "pastor_stambaugh_gamma"]
    ].dropna()

    logging.info("Constructing PCA-based composite liquidity factor.")
    liquidity_factor = derive_liquidity_factor(
        liquidity_measures,
        columns=["quoted_spread", "amihud", "pastor_stambaugh_gamma"],
        n_components=config.pca_components,
    )

    ff_factors_df: pd.DataFrame
    if config.ff_factors_path:
        ff_raw = load_excel(config.ff_factors_path)
        ff_raw["month"] = pd.to_datetime(ff_raw["month"]).dt.to_period("M")
        ff_factors_df = ff_raw[["month", "SMB", "HML"]]
    else:
        logging.info("No external Fama-French factors provided; computing from sample.")
        ff_factors_df = compute_ff_factors(monthly_returns)

    factor_dataframe = build_factor_dataframe(ff_factors_df, liquidity_factor, monthly_returns)

    logging.info("Forming liquidity-sorted portfolios.")
    portfolio_frames = []
    for measure in ["quoted_spread", "amihud", "pastor_stambaugh_gamma", "LIQ"]:
        if measure == "LIQ":
            measure_df = liquidity_factor.rename(columns={"LIQ": measure})
        else:
            measure_df = liquidity_measures[["ticker", "month", measure]].dropna()

        quantile_assignments = assign_liquidity_quantiles(
            measure_df, measure=measure, quantiles=config.liquidity_quantiles
        )
        portfolios = build_liquidity_portfolios(
            monthly_returns,
            quantile_assignments[["ticker", "month", "portfolio", "measure"]],
            quantiles=config.liquidity_quantiles,
            segment_col="segment" if "segment" in monthly_returns.columns else None,
        )
        portfolio_frames.append(portfolios)

    liquidity_portfolios = pd.concat(portfolio_frames, ignore_index=True)

    if config.write_intermediate:
        liquidity_portfolios.to_parquet(config.output_dir / "liquidity_portfolios.parquet")

    logging.info("Estimating augmented factor regressions.")
    regression_results = run_three_factor_regression(liquidity_portfolios, factor_dataframe)
    if config.write_intermediate:
        regression_results.to_csv(config.output_dir / "three_factor_results.csv", index=False)

    logging.info("Running fixed-effects panel regression with clustered SEs.")
    panel_results = run_fixed_effects_panel(monthly_returns, factor_dataframe)
    if config.write_intermediate:
        (config.output_dir / "panel_results.txt").write_text(str(panel_results.summary))

    logging.info("Executing Fama-MacBeth cross-sectional pricing test.")
    fama_macbeth_summary = fama_macbeth_regression(
        monthly_returns, factor_dataframe, window=config.rolling_beta_window
    )
    if config.write_intermediate:
        fama_macbeth_summary.to_csv(config.output_dir / "fama_macbeth_summary.csv", index=False)

    logging.info("Running predictive regression for liquidity factor.")
    predictive_results = predictive_liquidity_regression(monthly_returns, liquidity_factor)
    if config.write_intermediate:
        predictive_results.to_csv(config.output_dir / "predictive_regression.csv", index=False)

    logging.info("Pipeline completed successfully.")


# ------------------------------ CLI interface ------------------------------- #

def parse_args() -> LiquidityAnalysisConfig:
    parser = argparse.ArgumentParser(description="Liquidity risk premium empirical pipeline.")
    parser.add_argument("--daily-path", type=Path, required=True, help="Excel file with daily stock data.")
    parser.add_argument("--monthly-path", type=Path, help="Optional Excel file with monthly characteristics.")
    parser.add_argument("--ff-path", type=Path, help="Optional Excel file with external Fama-French factors.")
    parser.add_argument("--sheet-name", type=str, help="Sheet name for Excel inputs.")
    parser.add_argument("--rolling-window", type=int, default=36, help="Rolling window (months) for beta estimation.")
    parser.add_argument("--quantiles", type=int, default=5, help="Number of liquidity portfolios.")
    parser.add_argument("--output-dir", type=Path, default=Path("results"), help="Output directory for artefacts.")
    parser.add_argument("--no-write", action="store_true", help="Disable writing intermediate outputs.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    return LiquidityAnalysisConfig(
        daily_path=args.daily_path,
        monthly_path=args.monthly_path,
        ff_factors_path=args.ff_path,
        sheet_name=args.sheet_name,
        rolling_beta_window=args.rolling_window,
        liquidity_quantiles=args.quantiles,
        output_dir=args.output_dir,
        write_intermediate=not args.no_write,
    )


def main() -> None:
    config = parse_args()
    run_full_pipeline(config)


if __name__ == "__main__":
    main()

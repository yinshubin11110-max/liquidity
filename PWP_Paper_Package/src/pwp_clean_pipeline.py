from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DATE_LOWER = pd.Timestamp("2014-09-01")
DATE_UPPER = pd.Timestamp("2025-10-31")
VOLUME_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
K2 = 3 - 2 * np.sqrt(2)  # Corwin-Schultz constant


@dataclass
class CleanResult:
    filename: str
    company_from_name: str | None
    ticker: str | None
    matched_company: str | None
    matched_ticker: str | None
    status: str
    message: str | None = None


def extract_company_and_ticker(filename: str) -> tuple[str | None, str | None]:
    match = re.match(r"^(.*?)\s*\(([^()]+)\)", filename)
    if match:
        company = match.group(1).strip().strip('"')
        ticker = match.group(2).strip()
        return company, ticker
    return None, None


def to_float(value: object) -> float | np.nan:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "—"}:
        return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def parse_volume(value: object) -> float | np.nan:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    if text in {"", "-", "—"}:
        return np.nan

    suffix = text[-1:]
    if suffix.upper() in VOLUME_MULTIPLIERS:
        number_part = text[:-1]
        try:
            base = float(number_part)
        except ValueError:
            return np.nan
        return base * VOLUME_MULTIPLIERS[suffix.upper()]

    try:
        return float(text)
    except ValueError:
        return np.nan


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    high = high.astype(float)
    low = low.astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_hl = np.log(high / low)
    beta = (log_hl ** 2).rolling(window=2).sum()

    shifted_high = high.shift(1)
    shifted_low = low.shift(1)
    with np.errstate(divide="ignore", invalid="ignore"):
        gamma = np.log(np.maximum(high, shifted_high) / np.minimum(low, shifted_low)) ** 2

    beta_minus_gamma = beta - gamma
    beta_minus_gamma = beta_minus_gamma.where(beta_minus_gamma > 0)

    with np.errstate(invalid="ignore"):
        alpha = (np.sqrt(beta) - np.sqrt(beta_minus_gamma)) / K2

    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    spread = spread.where((alpha.notna()) & np.isfinite(spread))
    return spread


def winsorise(series: pd.Series, lower: float, upper: float) -> pd.Series:
    quantiles = series.quantile([lower, upper]).dropna()
    if quantiles.empty or len(quantiles) < 2:
        return series
    low, high = quantiles.iloc[0], quantiles.iloc[-1]
    return series.clip(lower=low, upper=high)


def load_treatment(path: Path) -> pd.DataFrame:
    treatment = pd.read_excel(path)
    treatment = treatment.rename(
        columns={
            "Company Name": "company",
            "Ticker": "ticker",
            "Effective Date": "effective_date",
        }
    )
    treatment["company"] = treatment["company"].astype(str).str.strip()
    treatment["ticker"] = treatment["ticker"].astype(str).str.strip()
    treatment["effective_date"] = pd.to_datetime(treatment["effective_date"])
    treatment["event_month"] = treatment["effective_date"].dt.to_period("M")
    return treatment


def standardise_daily(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "Price": "Close",
        "Last": "Close",
        "Vol.": "Volume",
        "Volume": "Volume",
    }
    df = df.rename(columns=rename_map)

    required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"缺少必要列: {missing}")

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col].map(to_float)
    df["Volume"] = df["Volume"].map(parse_volume)

    df = df.dropna(subset=["Date", "Close"])
    df = df[(df["Date"] >= DATE_LOWER) & (df["Date"] <= DATE_UPPER)]
    df = df.sort_values("Date").reset_index(drop=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def compute_daily_metrics(daily: pd.DataFrame, ticker: str, company: str) -> pd.DataFrame:
    daily = daily.copy()
    daily["ticker"] = ticker
    daily["company"] = company
    daily["ret"] = daily["Close"].pct_change()
    daily["turnover_value"] = daily["Close"] * daily["Volume"]
    daily["amihud"] = daily["ret"].abs() / (daily["turnover_value"].replace(0, np.nan))
    daily["cs_spread"] = corwin_schultz_spread(daily["High"], daily["Low"])
    return daily


def aggregate_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()
    daily["month"] = daily["Date"].dt.to_period("M")
    grouped = (
        daily.groupby(["ticker", "company", "month"], observed=True)
        .agg(
            amihud=("amihud", "median"),
            cs_spread=("cs_spread", "median"),
            turnover_value=("turnover_value", "sum"),
            ret_std=("ret", "std"),
        )
        .reset_index()
    )
    return grouped


def process_files(
    raw_dir: Path, clean_dir: Path, treatment: pd.DataFrame
) -> tuple[pd.DataFrame, list[CleanResult]]:
    clean_dir.mkdir(parents=True, exist_ok=True)
    daily_records: list[pd.DataFrame] = []
    logs: list[CleanResult] = []

    for path in sorted(raw_dir.glob("*.csv")):
        if path.name.lower() == "clean_log.csv":
            continue
        company_name, ticker = extract_company_and_ticker(path.name)
        matched = treatment.loc[treatment["ticker"] == ticker] if ticker else pd.DataFrame()
        matched_company = matched["company"].iat[0] if not matched.empty else None
        matched_ticker = matched["ticker"].iat[0] if not matched.empty else None

        try:
            df_raw = pd.read_csv(path)
            daily = standardise_daily(df_raw)
            if daily.empty:
                raise ValueError("清洗后无数据")

            output_path = clean_dir / f"{ticker or path.stem}.csv"
            daily.to_csv(output_path, index=False, date_format="%Y-%m-%d")

            if ticker and matched.empty:
                status = "success_no_treatment_match"
                message = "已清洗，但未在treatment中找到匹配"
            else:
                status = "success"
                message = None

            if ticker and matched_company:
                company_for_metrics = matched_company
            else:
                company_for_metrics = company_name or matched_company or ""

            daily_metrics = compute_daily_metrics(daily, ticker or "", company_for_metrics)
            if not matched.empty:
                daily_metrics["company"] = matched_company
                daily_metrics["ticker"] = matched_ticker
            daily_records.append(daily_metrics)
        except Exception as exc:  # noqa: BLE001
            logs.append(
                CleanResult(
                    filename=path.name,
                    company_from_name=company_name,
                    ticker=ticker,
                    matched_company=matched_company,
                    matched_ticker=matched_ticker,
                    status="failed",
                    message=str(exc),
                )
            )
            continue

        logs.append(
            CleanResult(
                filename=path.name,
                company_from_name=company_name,
                ticker=ticker,
                matched_company=matched_company,
                matched_ticker=matched_ticker,
                status=status,
                message=message,
            )
        )

    if daily_records:
        daily_df = pd.concat(daily_records, ignore_index=True)
    else:
        daily_df = pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume", "ticker", "company"])

    return daily_df, logs


def build_outputs(raw_dir: Path) -> None:
    treatment_path = raw_dir / "treatment_list.xlsx"
    treatment = load_treatment(treatment_path)

    clean_dir = Path("clean_ohlcv")
    daily_df, logs = process_files(raw_dir, clean_dir, treatment)

    log_df = pd.DataFrame(
        [
            {
                "filename": log.filename,
                "company_from_filename": log.company_from_name,
                "ticker_from_filename": log.ticker,
                "matched_company": log.matched_company,
                "matched_ticker": log.matched_ticker,
                "status": log.status,
                "message": log.message,
            }
            for log in logs
        ]
    )
    log_df.to_csv("clean_log.csv", index=False)

    if daily_df.empty:
        raise RuntimeError("所有文件清洗失败或无有效数据。")

    daily_df["amihud"] = winsorise(daily_df["amihud"], 0.01, 0.99)

    monthly_df = aggregate_monthly(daily_df)
    monthly_df = monthly_df.merge(
        treatment[["ticker", "company", "event_month"]],
        on="ticker",
        how="inner",
        suffixes=("", "_treat"),
    )
    monthly_df["company"] = monthly_df["company_treat"]
    monthly_df = monthly_df.drop(columns=["company_treat"])

    monthly_df["month"] = monthly_df["month"].astype("period[M]")
    monthly_df["event_month"] = monthly_df["event_month"].astype("period[M]")
    monthly_df["k"] = monthly_df["month"].astype("int64") - monthly_df["event_month"].astype("int64")
    monthly_df["event_month"] = monthly_df["event_month"].astype(str)
    monthly_df["month"] = monthly_df["month"].astype(str)
    monthly_df = monthly_df.sort_values(["ticker", "month"]).reset_index(drop=True)

    panel_columns = [
        "month",
        "amihud",
        "cs_spread",
        "turnover_value",
        "ret_std",
        "ticker",
        "company",
        "event_month",
        "k",
    ]
    monthly_df[panel_columns].to_csv("pwp_monthly_panel.csv", index=False)

    success_tickers: set[str] = {
        log.matched_ticker or (log.ticker or "")
        for log in logs
        if log.status.startswith("success")
    }
    success_tickers.discard("")

    unique_panel_tickers = monthly_df["ticker"].nunique()
    preview = monthly_df[panel_columns].head(10).to_string(index=False)

    print(f"成功清洗的股票数: {len(success_tickers)}")
    print(f"面板中 ticker 去重数: {unique_panel_tickers}")
    print("预览前 10 行:")
    print(preview)


def main(args: Iterable[str] | None = None) -> None:
    raw_dir = Path("shuoshiyanjiu")
    if not raw_dir.exists():
        raise FileNotFoundError("未找到原始数据目录 'shuoshiyanjiu'")
    build_outputs(raw_dir)


if __name__ == "__main__":
    main()

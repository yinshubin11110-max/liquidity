from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "utf-8-sig", "cp1250", "cp1252", "latin1")
MEASURES: tuple[str, ...] = ("amihud", "cs_spread")


def parse_args(args: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Placebo event-study with shifted event months.")
    parser.add_argument("--panel", required=True, help="Path to monthly panel CSV.")
    parser.add_argument("--kmin", type=int, default=-9, help="Minimum k to include (inclusive).")
    parser.add_argument("--kmax", type=int, default=9, help="Maximum k to include (inclusive).")
    parser.add_argument("--baseline", type=int, default=-1, help="Baseline k for treatment coding.")
    parser.add_argument("--shift", type=int, required=True, help="Shift to apply to k (e.g., +1 for placebo).")
    return parser.parse_args(args)


def load_panel(path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"Unable to load {path}; encoding attempts failed. Last error: {last_error}")  # pragma: no cover


def prepare_data(df: pd.DataFrame, measure: str, kmin: int, kmax: int, shift: int) -> pd.DataFrame:
    required = {"k", "ticker", "month", measure}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = df.dropna(subset=list(required)).copy()
    df["k_shifted"] = df["k"] + shift
    df = df[df["k_shifted"].between(kmin, kmax)]
    if df.empty:
        raise ValueError("No observations remain after applying shift and filtering.")

    df["ticker"] = df["ticker"].astype(str)
    df["month"] = df["month"].astype(str)
    return df


def fit_shifted_regression(df: pd.DataFrame, measure: str, k_values: list[int], baseline: int):
    df = df.copy()
    df["k_cat"] = pd.Categorical(df["k_shifted"], categories=k_values, ordered=True)
    treatment_term = f"C(k_cat, Treatment(reference={baseline}))"
    formula = f"{measure} ~ {treatment_term} + C(ticker) + C(month)"
    model = smf.ols(formula, data=df)
    result = model.fit(cov_type="cluster", cov_kwds={"groups": df["ticker"]})
    return result, treatment_term


def collect_max_t(result, treatment_term: str, k_values: list[int], baseline: int) -> float:
    max_abs_t = 0.0
    for k in k_values:
        if k == baseline:
            continue
        param_name = f"{treatment_term}[T.{k}]"
        if param_name in result.tvalues:
            t_val = float(result.tvalues[param_name])
            max_abs_t = max(max_abs_t, abs(t_val))
    return max_abs_t


def write_notes(path: Path, stats_dict: dict[str, float]) -> None:
    with path.open("w", encoding="utf-8") as fp:
        for measure in MEASURES:
            value = stats_dict.get(measure, np.nan)
            fp.write(f"{measure}: max |t| = {value:.4f}\n")


def main(cli_args: Iterable[str] | None = None) -> None:
    args = parse_args(cli_args)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise FileNotFoundError(f"Panel file not found: {panel_path}")

    if args.kmin > args.kmax:
        raise ValueError("kmin must be <= kmax.")
    if not (args.kmin <= args.baseline <= args.kmax):
        raise ValueError("Baseline must lie within [kmin, kmax].")

    panel_df = load_panel(panel_path)
    k_values = list(range(args.kmin, args.kmax + 1))

    stats_dict: dict[str, float] = {}
    for measure in MEASURES:
        prepared = prepare_data(panel_df, measure, args.kmin, args.kmax, args.shift)
        result, treatment_term = fit_shifted_regression(prepared, measure, k_values, args.baseline)
        stats_dict[measure] = collect_max_t(result, treatment_term, k_values, args.baseline)

    write_notes(Path("notes_placebo.txt"), stats_dict)


if __name__ == "__main__":
    main()

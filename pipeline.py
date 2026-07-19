"""Milk quality screening analysis library.

Parses one monthly workbook, computes compact monthly society stats, derives
historical baselines from prior monthly stats, detects anomalies for societies
with enough history, and builds one canonical analysis bundle used by both the
human PDF report and Supabase persistence.
"""
import argparse
import datetime as _dt
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "input"
DB = ROOT / "data" / "screening.db"
SUMMER = {4, 5, 6, 7, 8, 9}
MIN_TOTAL_PRIOR_MONTHS = 3
MIN_SAME_SEASON_PRIOR_MONTHS = 2

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

COLMAP_A = {
    "S.NO.": "serial_no",
    "VCH.": "vehicle",
    "DATE": "date",
    "SHIFT.": "shift",
    "DCS": "dcs",
    "SOCIETY NAME": "society_name",
    "QTY": "qty",
    "Fat %": "fat_pct",
    "Snf %": "snf_pct",
    "CLR": "clr",
    "Kg, Fat": "kg_fat",
    "Kg. Snf": "kg_snf",
    "Rate": "rate",
    "Amount": "amount",
}

COLMAP_B = {
    "Sl No": "serial_no",
    "Veh No.": "vehicle",
    "Date": "date",
    "Shift": "shift",
    "DCS No.": "dcs",
    "Society Name": "society_name",
    "Qty": "qty",
    "Fat %": "fat_pct",
    "Snf %": "snf_pct",
    "Clr": "clr",
    "Kg. Fat": "kg_fat",
    "Kg. Snf": "kg_snf",
    "Rate": "rate",
    "Amount": "amount",
}

KEEP = [
    "serial_no",
    "vehicle",
    "date",
    "shift",
    "dcs",
    "society_name",
    "qty",
    "fat_pct",
    "snf_pct",
    "clr",
    "kg_fat",
    "kg_snf",
    "rate",
    "amount",
]

METRICS = ["fat_pct", "snf_pct", "clr", "qty"]
METHODOLOGY_VERSION = "screening-v1-safety"
SCREENING_DISCLAIMER = (
    "This system prioritizes records for review and confirmatory testing. "
    "It does not identify an adulterant, establish intent, or prove fraud."
)


class InputValidationError(ValueError):
    """Raised when a workbook does not meet the public input contract."""
FLAG_COLUMNS = [
    "facility",
    "serial_no",
    "dcs",
    "society_name",
    "date",
    "shift",
    "vehicle",
    "qty",
    "fat_pct",
    "snf_pct",
    "clr",
    "z_fat",
    "z_snf",
    "z_clr",
    "z_qty",
    "R1_snf_drop",
    "R2_snf_spike",
    "R3_fat_drop",
    "R4_ratio_break",
    "R5_clr_spike",
    "R6_dilution",
    "R7_clr_drop",
    "R8_repeated_spike",
    "low_seasonal_data",
    "file_month",
    "file_year",
    "b_fat",
    "b_snf",
    "b_clr",
    "b_qty",
    "season",
    "direction",
    "num_dir",
    "total_active",
    "pct_flagged",
    "seasonal_likely",
    "diagnosis",
    "confidence",
    "case",
    "explanation",
    "confidence_base",
    "confidence_note",
]
REVIEW_CASE_COLUMNS = [
    "case_id",
    "facility",
    "dcs",
    "society_name",
    "file_year",
    "file_month",
    "screening_date",
    "shift",
    "screening_category",
    "priority",
    "status",
    "recommended_next_step",
    "disposition",
    "confirmation_reference",
]


def season_for_month(month):
    return "summer" if int(month) in SUMMER else "winter"


def parse_filename(fn):
    base = Path(fn).name
    facility = base.split()[0]
    match = re.search(r"month of\s+([A-Za-z]+)\s+(\d{4})", base, re.I)
    if not match:
        return None
    return facility, MONTH_MAP[match.group(1).lower()], int(match.group(2))


def _schema_fingerprint(columns):
    """Return a stable, non-sensitive identifier for a workbook header layout."""
    normalized = [str(column).strip() for column in columns]
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:16]


def _select_column_mapping(columns):
    available = {str(column).strip() for column in columns}
    for name, mapping in (("layout_a", COLMAP_A), ("layout_b", COLMAP_B)):
        required_source_columns = {source for source, target in mapping.items() if target in {"serial_no", "date", "shift", "dcs", "society_name", "qty", "fat_pct", "snf_pct", "clr"}}
        if required_source_columns.issubset(available):
            return name, mapping
    return None, None


def inspect_collection_frame(df, facility, month, year, preview_rows=20):
    """Validate a supported workbook and return accepted rows plus diagnostics.

    No data row is silently discarded: callers receive row-level rejection reasons
    and can save the result before deciding whether to correct the source workbook.
    """
    layout, cmap = _select_column_mapping(df.columns)
    fingerprint = _schema_fingerprint(df.columns)
    if cmap is None:
        raise InputValidationError(
            f"Unsupported workbook schema (fingerprint {fingerprint}). "
            "Use one of the documented layouts or add a versioned adapter."
        )
    normalized = df.rename(columns=cmap)
    columns = [column for column in KEEP if column in normalized.columns]
    normalized = normalized[columns].copy()
    required = {"serial_no", "date", "shift", "dcs", "society_name", "qty", "fat_pct", "snf_pct", "clr"}
    missing = required - set(normalized.columns)
    if missing:
        raise InputValidationError(f"Missing required columns after normalization: {sorted(missing)}")

    source_row = pd.Series(range(2, len(normalized) + 2), index=normalized.index, dtype="int64")
    record_evidence_columns = [column for column in KEEP if column != "serial_no" and column in normalized.columns]
    has_record_evidence = normalized[record_evidence_columns].apply(
        lambda column: column.notna() & column.astype(str).str.strip().ne("")
    ).any(axis=1)
    society_label = normalized["society_name"].fillna("").astype(str).str.strip().str.upper()
    is_summary_row = normalized["serial_no"].isna() & society_label.isin({"TOTAL", "GRAND TOTAL", "SUBTOTAL"})
    data_rows = normalized[(normalized["serial_no"].notna() | has_record_evidence) & ~is_summary_row].copy()
    source_row = source_row.loc[data_rows.index]
    numeric_columns = ["qty", "fat_pct", "snf_pct", "clr", "kg_fat", "kg_snf", "rate", "amount", "dcs"]
    for column in numeric_columns:
        if column in data_rows.columns:
            data_rows[column] = pd.to_numeric(data_rows[column], errors="coerce")

    reasons = pd.Series("", index=data_rows.index, dtype="object")
    missing_serial = data_rows["serial_no"].isna() | data_rows["serial_no"].astype(str).str.strip().eq("")
    reasons.loc[missing_serial] = "missing_serial_no"
    date_text = data_rows["date"].astype(str).str.strip()
    iso_dates = date_text.str.match(r"^\d{4}-\d{1,2}-\d{1,2}(?:\s|$)")
    parsed_dates = pd.Series(pd.NaT, index=data_rows.index, dtype="datetime64[ns]")
    parsed_dates.loc[iso_dates] = pd.to_datetime(data_rows.loc[iso_dates, "date"], errors="coerce")
    parsed_dates.loc[~iso_dates] = pd.to_datetime(
        data_rows.loc[~iso_dates, "date"], format="mixed", dayfirst=True, errors="coerce"
    )
    invalid_date = parsed_dates.isna()
    reasons.loc[invalid_date] = reasons.loc[invalid_date].map(
        lambda current: f"{current}; missing_or_invalid_date".strip("; ")
    )
    for column in ["dcs", "fat_pct", "snf_pct", "clr", "qty"]:
        invalid = data_rows[column].isna() | ~np.isfinite(data_rows[column])
        reasons.loc[invalid] = reasons.loc[invalid].map(
            lambda current, column=column: f"{current}; missing_or_invalid_{column}".strip("; ")
        )
    shift_labels = data_rows["shift"].fillna("").astype(str).str.strip().str.upper()
    canonical_shifts = shift_labels.map({"M": "M", "MORNING": "M", "E": "E", "EVENING": "E"})
    invalid_shift = canonical_shifts.isna()
    reasons.loc[invalid_shift] = reasons.loc[invalid_shift].map(
        lambda current: f"{current}; missing_or_invalid_shift".strip("; ")
    )
    invalid_society = data_rows["society_name"].isna() | data_rows["society_name"].astype(str).str.strip().eq("")
    reasons.loc[invalid_society] = reasons.loc[invalid_society].map(
        lambda current: f"{current}; missing_society_name".strip("; ")
    )

    rejected = data_rows[reasons.ne("")].copy()
    rejected.insert(0, "source_row", source_row.loc[rejected.index])
    rejected["rejection_reason"] = reasons.loc[rejected.index]
    accepted = data_rows[reasons.eq("")].copy()
    accepted["date"] = parsed_dates.loc[accepted.index].dt.strftime("%d-%m-%Y")
    accepted["society_name"] = accepted["society_name"].astype(str).str.strip()
    accepted["shift"] = canonical_shifts.loc[accepted.index]
    accepted["vehicle"] = accepted["vehicle"].astype(str).str.strip()
    accepted["facility"] = facility
    accepted["file_month"] = int(month)
    accepted["file_year"] = int(year)
    accepted["season"] = season_for_month(month)
    diagnostics = {
        "contract_version": "collection-workbook-v1",
        "schema_layout": layout,
        "schema_fingerprint": fingerprint,
        "rows_seen": int(len(df)),
        "data_rows_seen": int(len(data_rows)),
        "accepted_rows": int(len(accepted)),
        "rejected_rows": int(len(rejected)),
        "rejection_counts": rejected["rejection_reason"].value_counts().to_dict() if len(rejected) else {},
        "accepted_preview": accepted.head(preview_rows).to_dict("records"),
        "rejected_preview": rejected.head(preview_rows).to_dict("records"),
    }
    return accepted, rejected, diagnostics


def normalize_collection_frame(df, facility, month, year):
    accepted, rejected, diagnostics = inspect_collection_frame(df, facility, month, year)
    if len(rejected):
        raise InputValidationError(
            f"Workbook contains {len(rejected)} rejected data row(s); correct the source and run "
            f"milk-quality-validate for details (schema {diagnostics['schema_fingerprint']})."
        )
    if not len(accepted):
        raise InputValidationError("Workbook has no usable data rows after validation.")
    return accepted


def inspect_workbook(path, preview_rows=20):
    """Read one workbook and return a JSON-safe validation report without persistence."""
    parsed = parse_filename(path)
    if parsed is None:
        raise InputValidationError("Filename must include 'month of <Month> <Year>'.")
    facility, month, year = parsed
    engine = "openpyxl" if Path(path).suffix.lower() == ".xlsx" else "xlrd"
    frame = pd.read_excel(path, engine=engine)
    _, _, diagnostics = inspect_collection_frame(frame, facility, month, year, preview_rows=preview_rows)
    return _jsonable({
        "source_file": Path(path).name,
        "facility": facility,
        "file_year": year,
        "file_month": month,
        **diagnostics,
    })


def load_file(path):
    parsed = parse_filename(path)
    if parsed is None:
        return None
    facility, month, year = parsed
    engine = "openpyxl" if Path(path).suffix.lower() == ".xlsx" else "xlrd"
    frame = pd.read_excel(path, engine=engine)
    return normalize_collection_frame(frame, facility, month, year)


def load_all(source_dir=SRC):
    frames = []
    paths = [*Path(source_dir).rglob("*.xls"), *Path(source_dir).rglob("*.xlsx")]
    for path in sorted(paths):
        frame = load_file(path)
        if frame is not None and len(frame):
            frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"No readable .xls or .xlsx files found in {source_dir}")
    return pd.concat(frames, ignore_index=True)


def _safe_std(values):
    if len(values) <= 1:
        return 0.0
    std = values.std()
    return 0.0 if pd.isna(std) else float(std)


def _metric_summary(values):
    values = values.dropna()
    if not len(values):
        return {name: None for name in ["mean", "std", "median", "q1", "q3", "p90", "p10", "min", "max"]}
    return {
        "mean": float(values.mean()),
        "std": _safe_std(values),
        "median": float(values.median()),
        "q1": float(values.quantile(0.25)),
        "q3": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "p10": float(values.quantile(0.10)),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def compute_society_month_stats(df, source_name="", parser_warning_count=0):
    rows = []
    processed_at = pd.Timestamp.now(tz="UTC").isoformat()
    for (facility, dcs, file_year, file_month), group in df.groupby(["facility", "dcs", "file_year", "file_month"]):
        row = {
            "facility": facility,
            "dcs": dcs,
            "society_name": group["society_name"].mode().iloc[0],
            "file_year": int(file_year),
            "file_month": int(file_month),
            "season": group["season"].iloc[0],
            "record_count": int(len(group)),
            "morning_count": int((group["shift"] == "M").sum()),
            "evening_count": int((group["shift"] == "E").sum()),
            "low_qty_count": int((group["qty"] < 10).sum()),
            "filename": Path(source_name).name if source_name else "",
            "processed_at": processed_at,
            "parser_warning_count": int(parser_warning_count),
        }
        snf_p90 = group["snf_pct"].quantile(0.90) if len(group) else None
        row["high_snf_spike_count"] = int((group["snf_pct"] > snf_p90).sum()) if snf_p90 is not None else 0
        for metric in METRICS:
            summary = _metric_summary(group[metric])
            for suffix, value in summary.items():
                row[f"{metric}_{suffix}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _pooled_std(means, stds, counts):
    total = int(counts.sum())
    if total <= 1:
        return 0.0
    weighted_mean = float(np.average(means, weights=counts))
    numerator = 0.0
    for mean, std, count in zip(means, stds, counts):
        variance = 0.0 if pd.isna(std) else float(std) ** 2
        numerator += max(int(count) - 1, 0) * variance
        numerator += int(count) * (float(mean) - weighted_mean) ** 2
    return float(np.sqrt(numerator / max(total - 1, 1)))


def _baseline_from_month_groups(facility, dcs, season, group, total_prior_months, same_season_prior_months):
    total_records = int(group["record_count"].sum())
    row = {
        "facility": facility,
        "dcs": dcs,
        "society_name": group["society_name"].mode().iloc[0],
        "season": season,
        "record_count": total_records,
        "prior_month_count": int(total_prior_months),
        "same_season_prior_month_count": int(same_season_prior_months),
        "eligible": int(total_prior_months >= MIN_TOTAL_PRIOR_MONTHS and (season == "all" or same_season_prior_months >= MIN_SAME_SEASON_PRIOR_MONTHS)),
    }
    counts = group["record_count"].astype(float)
    for metric in METRICS:
        means = group[f"{metric}_mean"].astype(float)
        stds = group[f"{metric}_std"].fillna(0).astype(float)
        row[f"{metric}_mean"] = float(np.average(means, weights=counts)) if len(group) else None
        row[f"{metric}_std"] = _pooled_std(means, stds, counts)
        row[f"{metric}_median"] = float(group[f"{metric}_median"].median())
        row[f"{metric}_q1"] = float(group[f"{metric}_q1"].median())
        row[f"{metric}_q3"] = float(group[f"{metric}_q3"].median())
        row[f"{metric}_p90"] = float(group[f"{metric}_p90"].mean())
        row[f"{metric}_p10"] = float(group[f"{metric}_p10"].mean())
        if metric == "snf_pct" and row["snf_pct_std"] and row["snf_pct_std"] > 0.5:
            trimmed = group[
                (group["snf_pct_mean"] >= group["snf_pct_q1"]) &
                (group["snf_pct_mean"] <= group["snf_pct_q3"])
            ]
            if len(trimmed) >= 2:
                trim_counts = trimmed["record_count"].astype(float)
                row["snf_pct_mean"] = float(np.average(trimmed["snf_pct_mean"].astype(float), weights=trim_counts))
                row["snf_pct_std"] = _pooled_std(
                    trimmed["snf_pct_mean"].astype(float),
                    trimmed["snf_pct_std"].fillna(0).astype(float),
                    trim_counts,
                )
    return row


def build_baselines_from_month_stats(month_stats_df, target_year, target_month):
    if month_stats_df is None or not len(month_stats_df):
        return pd.DataFrame()
    stats = month_stats_df.copy()
    stats["ym"] = stats["file_year"].astype(int) * 100 + stats["file_month"].astype(int)
    target_ym = int(target_year) * 100 + int(target_month)
    prior = stats[stats["ym"] < target_ym].copy()
    if not len(prior):
        return pd.DataFrame()
    rows = []
    for (facility, dcs), all_group in prior.groupby(["facility", "dcs"]):
        total_prior_months = len(all_group)
        rows.append(_baseline_from_month_groups(facility, dcs, "all", all_group, total_prior_months, len(all_group[all_group["season"] == season_for_month(target_month)])))
        for season, season_group in all_group.groupby("season"):
            rows.append(_baseline_from_month_groups(facility, dcs, season, season_group, total_prior_months, len(season_group)))
    return pd.DataFrame(rows)


def build_baselines(df):
    rows = []
    for (facility, dcs, season), group in df.groupby(["facility", "dcs", "season"]):
        if len(group) < 10:
            continue
        rows.append(_legacy_baseline_row(facility, dcs, season, group))
    for (facility, dcs), group in df.groupby(["facility", "dcs"]):
        if len(group) < 10:
            continue
        rows.append(_legacy_baseline_row(facility, dcs, "all", group))
    return pd.DataFrame(rows)


def _legacy_baseline_row(facility, dcs, season, group):
    row = {"facility": facility, "dcs": dcs, "society_name": group["society_name"].mode().iloc[0], "season": season, "record_count": len(group), "eligible": 1}
    for metric in METRICS:
        summary = _metric_summary(group[metric])
        for suffix, value in summary.items():
            row[f"{metric}_{suffix}"] = value
        if metric == "snf_pct" and row["snf_pct_std"] and row["snf_pct_std"] > 0.5:
            trimmed = group[(group["snf_pct"] >= row["snf_pct_q1"]) & (group["snf_pct"] <= row["snf_pct_q3"])]["snf_pct"]
            if len(trimmed) >= 5:
                row["snf_pct_mean"] = float(trimmed.mean())
                row["snf_pct_std"] = _safe_std(trimmed)
    return row


def _empty_flagged_frame():
    return pd.DataFrame(columns=FLAG_COLUMNS)


def zscore(value, mean, std):
    return 0.0 if std in (None, 0) or pd.isna(std) else (value - mean) / std


def apply_rules(df, baselines):
    if baselines is None or not len(baselines):
        return _empty_flagged_frame()
    lookup = {(row["facility"], row["dcs"], row["season"]): row for _, row in baselines.iterrows()}
    flagged_rows = []
    for record in df.itertuples(index=False):
        baseline = lookup.get((record.facility, record.dcs, record.season))
        low_seasonal = 0
        if baseline is None or int(baseline.get("eligible", 1)) == 0 or baseline["record_count"] < 15:
            fallback = lookup.get((record.facility, record.dcs, "all"))
            if fallback is None or int(fallback.get("eligible", 1)) == 0 or fallback["record_count"] < 30:
                continue
            baseline = fallback
            low_seasonal = 1
        thin = baseline["record_count"] < 30
        z_fat = zscore(record.fat_pct, baseline["fat_pct_mean"], baseline["fat_pct_std"])
        z_snf = zscore(record.snf_pct, baseline["snf_pct_mean"], baseline["snf_pct_std"])
        z_clr = zscore(record.clr, baseline["clr_mean"], baseline["clr_std"])
        z_qty = zscore(record.qty, baseline["qty_mean"], baseline["qty_std"])

        r1 = int(z_snf < -2.0 and record.snf_pct < 8.0)
        r2 = int(z_snf > 2.0 and record.snf_pct > 9.2)
        r3 = int(z_fat < -2.5 and record.fat_pct < (baseline["fat_pct_mean"] - 2.0))
        r4 = int(z_snf > 1.5 and z_fat < -0.5 and record.snf_pct > 9.0)
        r5 = int(z_clr > 2.0 and record.clr >= 29)
        r6 = int(z_qty > 2.0 and (z_fat < -1.5 or z_snf < -1.5))
        r7 = int(z_clr < -2.0 and record.clr < 25)

        if thin:
            keep_any = any([z_snf < -3.5, z_snf > 3.5, z_fat < -3.5, z_fat > 3.5, z_clr < -3.5, z_clr > 3.5])
            if not keep_any:
                r1 = r2 = r3 = r4 = r5 = r6 = r7 = 0

        if any([r1, r2, r3, r4, r5, r6, r7]):
            flagged_rows.append({
                "facility": record.facility,
                "serial_no": getattr(record, "serial_no", None),
                "dcs": record.dcs,
                "society_name": record.society_name,
                "date": record.date,
                "shift": record.shift,
                "vehicle": record.vehicle,
                "qty": record.qty,
                "fat_pct": record.fat_pct,
                "snf_pct": record.snf_pct,
                "clr": record.clr,
                "z_fat": z_fat,
                "z_snf": z_snf,
                "z_clr": z_clr,
                "z_qty": z_qty,
                "R1_snf_drop": r1,
                "R2_snf_spike": r2,
                "R3_fat_drop": r3,
                "R4_ratio_break": r4,
                "R5_clr_spike": r5,
                "R6_dilution": r6,
                "R7_clr_drop": r7,
                "R8_repeated_spike": 0,
                "low_seasonal_data": low_seasonal,
                "file_month": record.file_month,
                "file_year": record.file_year,
                "b_fat": baseline["fat_pct_mean"],
                "b_snf": baseline["snf_pct_mean"],
                "b_clr": baseline["clr_mean"],
                "b_qty": baseline["qty_mean"],
                "season": record.season,
            })
    flagged = pd.DataFrame(flagged_rows) if flagged_rows else _empty_flagged_frame()

    # R8 is intentionally disabled. A fixed count above p90 has a high null
    # probability for societies with many collections and is not exposure-aware.
    # The column remains in the compatibility schema and is always zero.
    return flagged if len(flagged) else _empty_flagged_frame()


def diagnose(row):
    if row.get("R6_dilution", 0) == 1:
        return ("VOLUME_COMPOSITION_SHIFT", "RESAMPLE", "S6")
    if row.get("R1_snf_drop", 0) == 1 and row.get("R7_clr_drop", 0) == 1:
        return ("LOW_DENSITY_COMPOSITION_SCREEN", "RESAMPLE", "S1_7")
    if row.get("R2_snf_spike", 0) == 1 and row.get("R5_clr_spike", 0) == 1:
        return ("HIGH_DENSITY_COMPOSITION_SCREEN", "RESAMPLE", "S2_5")
    rules = (
        ("R7_clr_drop", "LOW_DENSITY_SCREEN", "S7"),
        ("R5_clr_spike", "HIGH_DENSITY_SCREEN", "S5"),
        ("R3_fat_drop", "LOW_FAT_SCREEN", "S3"),
        ("R1_snf_drop", "LOW_SOLIDS_SCREEN", "S1"),
        ("R2_snf_spike", "HIGH_SOLIDS_SCREEN", "S2"),
        ("R4_ratio_break", "COMPOSITION_RELATIONSHIP_SCREEN", "S4"),
    )
    for rule, category, case in rules:
        if row.get(rule, 0) == 1:
            return (category, "REVIEW", case)
    if row.get("R8_repeated_spike", 0) == 1:
        return ("LEGACY_RULE_DISABLED", "MONITOR", "S_LEGACY")
    return ("UNCLASSIFIED_SCREENING_SIGNAL", "MONITOR", "S0")


def explain(row, diagnosis):
    return (
        f"SNF {row['snf_pct']:.2f}% (base {row['b_snf']:.2f}, z={row['z_snf']:+.1f}); "
        f"Fat {row['fat_pct']:.2f}% (base {row['b_fat']:.2f}, z={row['z_fat']:+.1f}); "
        f"CLR {row['clr']:.1f} (base {row['b_clr']:.1f}, z={row['z_clr']:+.1f}); "
        f"QTY {row['qty']:.1f} (base {row['b_qty']:.1f}, z={row['z_qty']:+.1f}). "
        f"Screening category: {diagnosis}. Confirmatory testing is required."
    )


def downgrade_confidence(confidence):
    order = ["MONITOR", "REVIEW", "RESAMPLE"]
    if confidence not in order:
        return confidence
    return order[max(0, order.index(confidence) - 1)]


def apply_confidence_adjustments(flagged):
    if not len(flagged):
        return flagged
    adjusted = flagged.copy()
    adjusted["confidence_base"] = adjusted["confidence"]
    notes = []
    for idx, row in adjusted.iterrows():
        confidence = row["confidence"]
        row_notes = []
        if pd.notna(row.get("qty")) and row.get("qty") < 10:
            confidence = downgrade_confidence(confidence)
            row_notes.append("screening priority reduced for QTY < 10L")
        if row.get("low_seasonal_data", 0) == 1 and confidence == "RESAMPLE":
            confidence = "REVIEW"
            row_notes.append("screening priority capped because same-season history is thin")
        adjusted.at[idx, "confidence"] = confidence
        notes.append("; ".join(row_notes))
    adjusted["confidence_note"] = notes
    needs_note = adjusted["confidence_note"].astype(str).str.len() > 0
    adjusted.loc[needs_note, "explanation"] = adjusted.loc[needs_note, "explanation"] + " Note: " + adjusted.loc[needs_note, "confidence_note"] + "."
    return adjusted


def seasonal_filter(flagged, all_records):
    if not len(flagged):
        flagged["seasonal_likely"] = 0
        flagged["pct_flagged"] = 0.0
        return flagged
    active = all_records.groupby(["facility", "date", "shift"])["dcs"].nunique().rename("total_active").reset_index()
    flagged["direction"] = np.where(
        (flagged["z_snf"] < -1) | (flagged["z_fat"] < -1) | (flagged["z_clr"] < -1),
        "down",
        np.where((flagged["z_snf"] > 1) | (flagged["z_clr"] > 1), "up", "mixed"),
    )
    counts = flagged.groupby(["facility", "date", "shift", "direction"])["dcs"].nunique().rename("num_dir").reset_index()
    flagged = flagged.merge(counts, on=["facility", "date", "shift", "direction"], how="left")
    flagged = flagged.merge(active, on=["facility", "date", "shift"], how="left")
    flagged["pct_flagged"] = flagged["num_dir"] / flagged["total_active"] * 100
    flagged["seasonal_likely"] = (flagged["pct_flagged"] > 30).astype(int)
    return flagged


def build_daily_summary(flagged, all_records):
    active = all_records.groupby(["facility", "date", "shift"])["dcs"].nunique().rename("total_active").reset_index()
    if len(flagged):
        counts = flagged.groupby(["facility", "date", "shift"])["dcs"].nunique().rename("num_flagged").reset_index()
        daily = active.merge(counts, on=["facility", "date", "shift"], how="left")
    else:
        daily = active.copy()
        daily["num_flagged"] = 0
    daily["num_flagged"] = daily["num_flagged"].fillna(0).astype(int)
    daily["pct_flagged"] = daily["num_flagged"] / daily["total_active"] * 100
    daily["seasonal_event"] = (daily["pct_flagged"] > 30).astype(int)
    return daily


def build_severity(report):
    if not len(report):
        return pd.DataFrame(
            columns=["facility", "dcs", "society_name", "file_year", "file_month", "flags", "severity", "primary_diagnosis"]
        )
    ym = report["file_year"] * 100 + report["file_month"]
    cutoff = sorted(ym.unique())[-6] if len(ym.unique()) >= 6 else ym.min()
    recent = report[ym >= cutoff]
    group_keys = ["facility", "dcs", "society_name", "file_year", "file_month"]
    severity = recent.groupby(group_keys).size().rename("flags").reset_index()
    def level(count):
        if count >= 30:
            return "VERY_FREQUENT"
        if count >= 15:
            return "FREQUENT"
        if count >= 8:
            return "RECURRING"
        return "ISOLATED"
    severity["severity"] = severity["flags"].apply(level)
    primary = (
        recent.groupby(group_keys)["diagnosis"]
        .agg(lambda s: s.mode().iloc[0] if len(s.mode()) else s.iloc[0])
        .rename("primary_diagnosis")
        .reset_index()
    )
    return severity.merge(primary, on=group_keys, how="left")


def build_month_summaries(df, flagged, report, mode="detection"):
    rows = []
    for (facility, year, month), group in df.groupby(["facility", "file_year", "file_month"]):
        if len(flagged) and "facility" in flagged.columns:
            all_month = flagged[(flagged["facility"] == facility) & (flagged["file_year"] == year) & (flagged["file_month"] == month)]
        else:
            all_month = pd.DataFrame()
        if len(report) and "facility" in report.columns:
            final_month = report[(report["facility"] == facility) & (report["file_year"] == year) & (report["file_month"] == month)]
        else:
            final_month = pd.DataFrame()
        rows.append({
            "facility": facility,
            "file_month": int(month),
            "file_year": int(year),
            "records_processed": int(len(group)),
            "societies_active": int(group["dcs"].nunique()),
            "initial_flags": int(len(all_month)),
            "seasonal_suppressed": int(all_month["seasonal_likely"].sum()) if len(all_month) else 0,
            "final_flags": int(len(final_month)),
            "high_confidence_flags": int((final_month["confidence"] == "RESAMPLE").sum()) if len(final_month) else 0,
            "priority_resample_flags": int((final_month["confidence"] == "RESAMPLE").sum()) if len(final_month) else 0,
            "top_diagnosis": final_month["diagnosis"].mode().iloc[0] if len(final_month) else "",
            "top_screening_category": final_month["diagnosis"].mode().iloc[0] if len(final_month) else "",
            "top_flagged_societies": (
                final_month.groupby(["dcs", "society_name"])
                .agg(flags=("diagnosis", "size"), primary_diagnosis=("diagnosis", lambda s: s.mode().iloc[0]))
                .sort_values("flags", ascending=False)
                .head(5)
                .reset_index()
                .to_dict("records")
                if len(final_month)
                else []
            ),
            "notes": "Calibration / insufficient history" if mode != "detection" else "",
            "mode": mode,
        })
    return pd.DataFrame(rows)


def build_audit_trail(df, flagged, report, mode="detection"):
    return pd.DataFrame(
        [
            {"facility": "ALL", "file_month": None, "file_year": None, "metric": "records_processed", "value": int(len(df)), "mode": mode},
            {"facility": "ALL", "file_month": None, "file_year": None, "metric": "societies_active", "value": int(df.groupby(["facility", "dcs"]).ngroups), "mode": mode},
            {"facility": "ALL", "file_month": None, "file_year": None, "metric": "initial_flags", "value": int(len(flagged)), "mode": mode},
            {"facility": "ALL", "file_month": None, "file_year": None, "metric": "seasonal_suppressed", "value": int(flagged["seasonal_likely"].sum()) if len(flagged) else 0, "mode": mode},
            {"facility": "ALL", "file_month": None, "file_year": None, "metric": "final_flags", "value": int(len(report)), "mode": mode},
        ]
    )


def build_calibration_watchlist(month_stats):
    if not len(month_stats):
        return []
    rows = []
    facility_summary = month_stats.groupby("facility").agg(
        fat_mean=("fat_pct_mean", "mean"),
        fat_std=("fat_pct_mean", lambda s: 0.0 if len(s) <= 1 else float(s.std())),
        snf_mean=("snf_pct_mean", "mean"),
        snf_std=("snf_pct_mean", lambda s: 0.0 if len(s) <= 1 else float(s.std())),
        clr_mean=("clr_mean", "mean"),
        clr_std=("clr_mean", lambda s: 0.0 if len(s) <= 1 else float(s.std())),
    ).reset_index()
    for _, row in month_stats.iterrows():
        fac = facility_summary[facility_summary["facility"] == row["facility"]].iloc[0]
        z_fat = zscore(row["fat_pct_mean"], fac["fat_mean"], fac["fat_std"])
        z_snf = zscore(row["snf_pct_mean"], fac["snf_mean"], fac["snf_std"])
        z_clr = zscore(row["clr_mean"], fac["clr_mean"], fac["clr_std"])
        score = abs(z_fat) + abs(z_snf) + abs(z_clr)
        rows.append({
            "facility": row["facility"],
            "dcs": row["dcs"],
            "society_name": row["society_name"],
            "record_count": int(row["record_count"]),
            "fat_mean": row["fat_pct_mean"],
            "snf_mean": row["snf_pct_mean"],
            "clr_mean": row["clr_mean"],
            "deviation_score": round(float(score), 2),
        })
    rows.sort(key=lambda item: item["deviation_score"], reverse=True)
    return rows[:15]


def _jsonable(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if pd.isna(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def build_analysis_bundle(
    month_df,
    month_stats,
    historical_month_stats,
    baselines,
    flagged,
    report,
    daily,
    severity,
    source_name="",
    mode="detection",
):
    facilities = sorted(month_df["facility"].dropna().unique().tolist())
    facility = facilities[0] if len(facilities) == 1 else "ALL"
    file_year = int(month_df["file_year"].iloc[0])
    file_month = int(month_df["file_month"].iloc[0])
    sections = {}
    diagnosis_counts = report["diagnosis"].value_counts().to_dict() if len(report) else {}
    severity_rows = severity.to_dict("records") if len(severity) else []
    recurring_patterns = build_recurring_signal_indicators(report)
    watchlist = build_calibration_watchlist(month_stats)
    baseline_snapshot = baselines[["facility", "dcs", "society_name", "season", "record_count", "prior_month_count", "same_season_prior_month_count", "eligible"]].to_dict("records") if len(baselines) else []
    sections["executive_summary"] = {
        "title": "Executive Summary",
        "mode": mode,
        "summary": (
            f"Calibration report for {facility} {file_year}-{file_month:02d}; history is not yet sufficient for record-level screening."
            if mode != "detection"
            else f"Prioritized {len(report)} records for review for {facility} {file_year}-{file_month:02d}."
        ),
        "top_findings": severity_rows[:8] if len(severity_rows) else watchlist[:8],
    }
    sections["audit_trail"] = {
        "title": "Audit Trail",
        "initial_flags": int(len(flagged)),
        "seasonal_suppressed": int(flagged["seasonal_likely"].sum()) if len(flagged) else 0,
        "final_flags": int(len(report)),
        "mode": mode,
    }
    sections["facility_overview"] = {
        "title": "Facility Overview",
        "facility_metrics": month_df.groupby("facility").agg(
            records=("qty", "size"),
            societies=("dcs", "nunique"),
            avg_fat=("fat_pct", "mean"),
            avg_snf=("snf_pct", "mean"),
            avg_clr=("clr", "mean"),
        ).round(2).reset_index().to_dict("records"),
    }
    sections["diagnosis_distribution"] = {
        "title": "Screening Category Distribution",
        "counts": diagnosis_counts,
        "confidence_counts": report["confidence"].value_counts().to_dict() if len(report) else {},
    }
    sections["recurring_signal_indicators"] = {
        "title": "Recurring Screening Signal Indicators",
        "interpretation": (
            "Repeated screening signals can prioritize investigation, but do not identify an adulterant, "
            "establish intent, or prove fraud."
        ),
        "rows": recurring_patterns,
    }
    sections["screening_distribution"] = sections["diagnosis_distribution"]
    sections["top_offenders"] = {
        "title": "Top Screening Signals by Society",
        "rows": (
            report.groupby(["facility", "dcs", "society_name", "diagnosis"]).size().rename("count").reset_index().sort_values("count", ascending=False).head(15).to_dict("records")
            if len(report)
            else []
        ),
    }
    details = report.copy()
    if len(details):
        details = details[~((details["diagnosis"] == "UNCLASSIFIED_SCREENING_SIGNAL") & (details["confidence"] == "MONITOR") & (details["z_snf"].abs() <= 1.5) & (details["z_fat"].abs() <= 1.5) & (details["z_clr"].abs() <= 1.5))]
    sections["detail_logs"] = {"title": "Detail Logs", "rows": details.to_dict("records") if len(details) else []}
    sections["action_plan"] = {
        "title": "Action Plan",
        "actions": [
            {"diagnosis": "LOW_DENSITY_COMPOSITION_SCREEN", "action": "Collect a controlled resample; verify temperature-corrected CLR and reference fat/SNF measurements."},
            {"diagnosis": "HIGH_DENSITY_COMPOSITION_SCREEN", "action": "Collect a controlled resample and select a confirmatory laboratory panel based on chain-of-custody evidence."},
            {"diagnosis": "LOW_FAT_SCREEN", "action": "Repeat the fat measurement with a reference method and verify milk class and sampling procedure."},
            {"diagnosis": "VOLUME_COMPOSITION_SHIFT", "action": "Verify collection records, route context, and sampling integrity before controlled resampling."},
            {"diagnosis": "COMPOSITION_RELATIONSHIP_SCREEN", "action": "Review instrument calibration, formula use, and measurement provenance."},
        ],
    }
    sections["methodology"] = {
        "title": "Methodology Summary",
        "rules": [
            {"id": "R1", "trigger": "z_snf < -2.0 and SNF < 8.0"},
            {"id": "R2", "trigger": "z_snf > 2.0 and SNF > 9.2"},
            {"id": "R3", "trigger": "z_fat < -2.5 and Fat < baseline - 2.0"},
            {"id": "R4", "trigger": "z_snf > 1.5 and z_fat < -0.5 and SNF > 9.0"},
            {"id": "R5", "trigger": "z_clr > 2.0 and CLR >= 29"},
            {"id": "R6", "trigger": "z_qty > 2.0 and (z_fat < -1.5 or z_snf < -1.5)"},
            {"id": "R7", "trigger": "z_clr < -2.0 and CLR < 25"},
        ],
        "disabled_rules": [{"id": "R8", "reason": "Fixed exceedance count is not exposure-aware and has an unacceptably high null probability."}],
        "intended_use": SCREENING_DISCLAIMER,
        "baseline_policy": {
            "minimum_total_prior_months": MIN_TOTAL_PRIOR_MONTHS,
            "minimum_same_season_prior_months": MIN_SAME_SEASON_PRIOR_MONTHS,
            "mode": mode,
        },
    }
    sections["calibration"] = {
        "title": "Calibration / Insufficient History",
        "watchlist": watchlist,
        "eligible_societies": int(sum(item.get("eligible", 0) for item in baseline_snapshot)),
        "baseline_snapshot": baseline_snapshot,
    }

    bundle = {
        "methodology_version": METHODOLOGY_VERSION,
        "disclaimer": SCREENING_DISCLAIMER,
        "legacy_schema": {
            "diagnosis": "Deprecated compatibility field containing screening_category.",
            "confidence": "Deprecated compatibility field containing screening_priority.",
            "severity": "Deprecated compatibility field containing screening frequency.",
        },
        "file_identity": {
            "facility": facility,
            "facilities": facilities,
            "file_year": file_year,
            "file_month": file_month,
            "season": month_df["season"].iloc[0],
            "filename": Path(source_name).name if source_name else "",
        },
        "processing_metrics": {
            "records_processed": int(len(month_df)),
            "societies_active": int(month_df["dcs"].nunique()),
            "facility_count": int(len(facilities)),
            "duplicates_removed": 0,
            "parse_warnings": 0,
            "mode": mode,
        },
        "current_month_stats": month_stats.to_dict("records"),
        "historical_baselines": baseline_snapshot,
        "anomaly_records": flagged.to_dict("records") if len(flagged) else [],
        "report_records": report.to_dict("records") if len(report) else [],
        "daily_summary": daily.to_dict("records") if len(daily) else [],
        "severity": severity_rows,
        "recurring_signal_indicators": recurring_patterns,
        "sections": sections,
        "retrieval": {
            "summary_text": sections["executive_summary"]["summary"],
            "top_diagnoses": diagnosis_counts,
            "top_screening_categories": diagnosis_counts,
            "mode": mode,
        },
        "history_inputs": {
            "historical_month_stats_count": int(len(historical_month_stats)) if historical_month_stats is not None else 0,
        },
    }
    return _jsonable(bundle)


def build_recurring_signal_indicators(report, minimum_signals=2):
    """Summarize repeated signals within a processed period without cause attribution."""
    if report.empty:
        return []
    grouped = (
        report.groupby(["facility", "dcs", "society_name", "diagnosis"], dropna=False)
        .agg(
            screening_signal_count=("date", "size"),
            first_signal_date=("date", "min"),
            last_signal_date=("date", "max"),
            highest_priority=(
                "confidence",
                lambda values: next(
                    (priority for priority in ("RESAMPLE", "REVIEW", "MONITOR") if priority in set(values)),
                    "MONITOR",
                ),
            ),
        )
        .reset_index()
    )
    repeated = grouped[grouped["screening_signal_count"] >= minimum_signals].copy()
    if repeated.empty:
        return []
    repeated["indicator"] = "RECURRING_SCREENING_PATTERN"
    repeated["interpretation"] = (
        "Repeat source-integrity checks and controlled resampling; confirmation is required before any causal conclusion."
    )
    return repeated.sort_values(["screening_signal_count", "facility", "dcs"], ascending=[False, True, True]).to_dict("records")


def analyze_month(month_df, historical_month_stats=None, source_name=""):
    historical_month_stats = historical_month_stats if historical_month_stats is not None else pd.DataFrame()
    month_stats = compute_society_month_stats(month_df, source_name=source_name)
    baselines = build_baselines_from_month_stats(historical_month_stats, month_df["file_year"].iloc[0], month_df["file_month"].iloc[0])
    flagged = apply_rules(month_df, baselines)
    if len(flagged):
        flagged = seasonal_filter(flagged, month_df)
        diagnoses = flagged.apply(diagnose, axis=1, result_type="expand")
        diagnoses.columns = ["diagnosis", "confidence", "case"]
        flagged = pd.concat([flagged, diagnoses], axis=1)
        flagged["explanation"] = flagged.apply(lambda row: explain(row, row["diagnosis"]), axis=1)
        flagged = apply_confidence_adjustments(flagged)
    else:
        flagged = _empty_flagged_frame()
    report = flagged[flagged["seasonal_likely"] == 0].copy() if len(flagged) else flagged.copy()
    daily = build_daily_summary(flagged, month_df)
    severity = build_severity(report)
    mode = "detection" if len(report) else "seed_only"
    bundle = build_analysis_bundle(month_df, month_stats, historical_month_stats, baselines, flagged, report, daily, severity, source_name=source_name, mode=mode)
    month_summaries = build_month_summaries(month_df, flagged, report, mode=mode)
    audit_trail = build_audit_trail(month_df, flagged, report, mode=mode)
    return {
        "month_df": month_df,
        "month_stats": month_stats,
        "baselines": baselines,
        "flagged": flagged,
        "report": report,
        "daily_summary": daily,
        "severity": severity,
        "month_summaries": month_summaries,
        "audit_trail": audit_trail,
        "report_bundle": bundle,
        "mode": mode,
    }


def _concat_run_frames(runs, key):
    frames = [run[key] for run in runs if key in run and len(run[key])]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _sqlite_ready(frame):
    """Encode structured values that SQLite drivers cannot bind directly."""
    ready = frame.copy()
    for column in ready.columns:
        if ready[column].map(lambda value: isinstance(value, (dict, list))).any():
            ready[column] = ready[column].map(
                lambda value: json.dumps(_jsonable(value)) if isinstance(value, (dict, list)) else value
            )
    return ready


def _read_sqlite_table(connection, table_name):
    try:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
    except (pd.errors.DatabaseError, sqlite3.OperationalError):
        return pd.DataFrame()


def _merge_derived_rows(existing, new, keys, preserve_existing=False):
    """Merge derived state deterministically instead of discarding prior periods."""
    if existing.empty:
        return new.copy()
    if new.empty:
        return existing.copy()
    combined = pd.concat([new, existing] if preserve_existing else [existing, new], ignore_index=True)
    available_keys = [key for key in keys if key in combined.columns]
    return combined.drop_duplicates(subset=available_keys, keep="last").reset_index(drop=True)


def _review_case_rows(report):
    """Create neutral, stable review cases; screening results never imply cause."""
    rows = []
    for _, row in report.iterrows():
        identity = "|".join(
            str(row.get(key, ""))
            for key in ("facility", "serial_no", "dcs", "date", "shift", "file_year", "file_month", "diagnosis")
        )
        rows.append(
            {
                "case_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
                "facility": row["facility"],
                "dcs": row["dcs"],
                "society_name": row["society_name"],
                "file_year": row["file_year"],
                "file_month": row["file_month"],
                "screening_date": row["date"],
                "shift": row["shift"],
                "screening_category": row["diagnosis"],
                "priority": row["confidence"],
                "status": "OPEN",
                "recommended_next_step": "Review source integrity and collect a controlled resample before confirmation.",
                "disposition": None,
                "confirmation_reference": None,
            }
        )
    return pd.DataFrame(rows, columns=REVIEW_CASE_COLUMNS)


def _completed_period_keys(report_bundles):
    if report_bundles.empty:
        return set()
    required = {"facility", "file_year", "file_month"}
    if not required.issubset(report_bundles.columns):
        return set()
    return {
        (str(row.facility), int(row.file_year), int(row.file_month))
        for row in report_bundles[list(required)].dropna().itertuples(index=False)
    }


def _legacy_all_periods(report_bundles):
    if report_bundles.empty:
        return set()
    required = {"facility", "file_year", "file_month"}
    if not required.issubset(report_bundles.columns):
        return set()
    legacy = report_bundles[report_bundles["facility"].eq("ALL")]
    return {(int(row.file_year), int(row.file_month)) for row in legacy.dropna().itertuples(index=False)}


def run_pipeline(source_dir=SRC, db_path=DB, output_dir=ROOT):
    """Analyze each reporting month in order and persist derived results.

    A target month can use only monthly statistics created by earlier periods.
    Grouping all input files before analysis would leak period identity and leave
    the local CLI permanently without an eligible historical baseline.
    """
    del output_dir  # Reserved for a future local report-output adapter.
    records = load_all(source_dir)
    records = records.sort_values(["file_year", "file_month", "facility", "date"]).reset_index(drop=True)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        existing = {
            "month_stats": _read_sqlite_table(connection, "society_month_stats"),
            "baselines": _read_sqlite_table(connection, "society_baselines"),
            "flagged": _read_sqlite_table(connection, "flagged_anomalies"),
            "daily_summary": _read_sqlite_table(connection, "daily_summary"),
            "severity": _read_sqlite_table(connection, "severity"),
            "month_summaries": _read_sqlite_table(connection, "month_summaries"),
            "audit_trail": _read_sqlite_table(connection, "audit_trail"),
            "report_bundles": _read_sqlite_table(connection, "report_bundles"),
            "review_cases": _read_sqlite_table(connection, "review_cases"),
        }
    historical_month_stats = existing["month_stats"].copy()
    completed_periods = _completed_period_keys(existing["report_bundles"])
    legacy_all_periods = _legacy_all_periods(existing["report_bundles"])
    runs = []
    skipped_periods = []

    for (year, month, facility), month_df in records.groupby(["file_year", "file_month", "facility"], sort=True):
        period_key = (str(facility), int(year), int(month))
        if period_key in completed_periods or (int(year), int(month)) in legacy_all_periods:
            skipped_periods.append(period_key)
            continue
        result = analyze_month(
            month_df.reset_index(drop=True),
            historical_month_stats=historical_month_stats,
            source_name=str(source_dir),
        )
        runs.append(result)
        historical_month_stats = pd.concat(
            [historical_month_stats, result["month_stats"]],
            ignore_index=True,
        )

    for result in runs:
        identity = result["report_bundle"]["file_identity"]
        result["audit_trail"] = result["audit_trail"].assign(
            facility=identity["facility"],
            file_year=identity["file_year"],
            file_month=identity["file_month"],
        )

    if not runs:
        raise ValueError("No new reporting periods were available; existing periods were left unchanged.")

    aggregated = {
        key: _concat_run_frames(runs, key)
        for key in [
            "month_stats",
            "baselines",
            "flagged",
            "report",
            "daily_summary",
            "severity",
            "month_summaries",
            "audit_trail",
        ]
    }
    bundle_rows = [
        {
            "facility": run["report_bundle"]["file_identity"]["facility"],
            "file_year": run["report_bundle"]["file_identity"]["file_year"],
            "file_month": run["report_bundle"]["file_identity"]["file_month"],
            "bundle_json": json.dumps(run["report_bundle"]),
        }
        for run in runs
    ]

    table_keys = {
        "month_stats": ["facility", "dcs", "file_year", "file_month"],
        "baselines": ["facility", "dcs", "season"],
        "flagged": ["facility", "serial_no", "dcs", "date", "shift", "file_year", "file_month", "diagnosis"],
        "daily_summary": ["facility", "date", "shift"],
        "severity": ["facility", "dcs", "file_year", "file_month"],
        "month_summaries": ["facility", "file_year", "file_month"],
    }
    persisted = {
        key: _merge_derived_rows(existing[key], aggregated[key], table_keys[key])
        for key in table_keys
    }
    persisted["audit_trail"] = pd.concat([existing["audit_trail"], aggregated["audit_trail"]], ignore_index=True)
    persisted["report_bundles"] = _merge_derived_rows(
        existing["report_bundles"],
        pd.DataFrame(bundle_rows),
        ["facility", "file_year", "file_month"],
    )
    new_cases = _review_case_rows(aggregated["report"])
    persisted["review_cases"] = _merge_derived_rows(
        existing["review_cases"], new_cases, ["case_id"], preserve_existing=True
    )
    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            table_map = {
                "month_stats": "society_month_stats",
                "baselines": "society_baselines",
                "flagged": "flagged_anomalies",
                "daily_summary": "daily_summary",
                "severity": "severity",
                "month_summaries": "month_summaries",
                "audit_trail": "audit_trail",
            }
            for key, table_name in table_map.items():
                if len(persisted[key]):
                    _sqlite_ready(persisted[key]).to_sql(table_name, connection, if_exists="replace", index=False)
            _sqlite_ready(persisted["report_bundles"]).to_sql("report_bundles", connection, if_exists="replace", index=False)
            _sqlite_ready(persisted["review_cases"]).to_sql("review_cases", connection, if_exists="replace", index=False)

    latest = {**runs[-1], **aggregated}
    latest["runs"] = runs
    latest["report_bundles"] = [run["report_bundle"] for run in runs]
    latest["records_processed"] = int(len(records))
    latest["skipped_periods"] = ["%s:%04d-%02d" % key for key in skipped_periods]
    return latest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run milk quality screening on local files.")
    parser.add_argument("--source-dir", default=str(SRC), help="Directory containing .xls files")
    parser.add_argument("--db", default=str(DB), help="SQLite database path")
    args = parser.parse_args(argv)
    result = run_pipeline(Path(args.source_dir), Path(args.db))
    print(
        json.dumps(
            {
                "periods_processed": len(result["runs"]),
                "records_processed": result["records_processed"],
                "latest_period": {
                    "facility": result["report_bundle"]["file_identity"]["facility"],
                    "file_month": result["report_bundle"]["file_identity"]["file_month"],
                    "file_year": result["report_bundle"]["file_identity"]["file_year"],
                    "mode": result["mode"],
                },
            },
            indent=2,
        )
    )


def validation_main(argv=None):
    parser = argparse.ArgumentParser(description="Validate a milk collection workbook before screening.")
    parser.add_argument("workbook", help="Path to one .xls or .xlsx workbook")
    parser.add_argument("--output", help="Optional path for the JSON validation report")
    parser.add_argument("--preview-rows", type=int, default=20, help="Accepted and rejected rows to preview")
    args = parser.parse_args(argv)
    report = inspect_workbook(Path(args.workbook), preview_rows=args.preview_rows)
    serialized = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    if report["rejected_rows"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

"""Supabase persistence runner for milk quality screening analysis."""
import argparse
import json
import os
from pathlib import Path
from urllib import parse, request

import pandas as pd

import build_report
import pipeline


MONTH_STATS_COLUMNS = [
    "facility", "dcs", "society_name", "file_year", "file_month", "season",
    "record_count", "morning_count", "evening_count", "low_qty_count",
    "high_snf_spike_count", "fat_pct_mean", "fat_pct_std", "fat_pct_median",
    "fat_pct_q1", "fat_pct_q3", "fat_pct_p90", "fat_pct_p10", "fat_pct_min",
    "fat_pct_max", "snf_pct_mean", "snf_pct_std", "snf_pct_median",
    "snf_pct_q1", "snf_pct_q3", "snf_pct_p90", "snf_pct_p10", "snf_pct_min",
    "snf_pct_max", "clr_mean", "clr_std", "clr_median", "clr_q1", "clr_q3",
    "clr_p90", "clr_p10", "clr_min", "clr_max", "qty_mean", "qty_std",
    "qty_median", "qty_q1", "qty_q3", "qty_p90", "qty_p10", "qty_min",
    "qty_max", "filename", "processed_at", "parser_warning_count",
]

BASELINE_COLUMNS = [
    "facility", "dcs", "society_name", "season", "record_count",
    "prior_month_count", "same_season_prior_month_count", "eligible",
    "fat_pct_mean", "fat_pct_std", "fat_pct_median", "fat_pct_q1",
    "fat_pct_q3", "fat_pct_p90", "fat_pct_p10", "snf_pct_mean", "snf_pct_std",
    "snf_pct_median", "snf_pct_q1", "snf_pct_q3", "snf_pct_p90",
    "snf_pct_p10", "clr_mean", "clr_std", "clr_median", "clr_q1", "clr_q3",
    "clr_p90", "clr_p10", "qty_mean", "qty_std", "qty_median", "qty_q1",
    "qty_q3", "qty_p90", "qty_p10",
]

RULE_COLUMNS = [
    ("R1", "R1_snf_drop"),
    ("R2", "R2_snf_spike"),
    ("R3", "R3_fat_drop"),
    ("R4", "R4_ratio_break"),
    ("R5", "R5_clr_spike"),
    ("R6", "R6_dilution"),
    ("R7", "R7_clr_drop"),
    ("R8", "R8_repeated_spike"),
]


class SupabaseRestClient:
    def __init__(self, url=None, key=None):
        self.url = (url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
        if not self.url or not self.key:
            raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY before running.")

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(self, method, path, params=None, payload=None, prefer=None):
        query = f"?{parse.urlencode(params)}" if params else ""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(f"{self.url}/rest/v1/{path}{query}", data=data, method=method, headers=self._headers(prefer))
        with request.urlopen(req, timeout=60) as response:
            body = response.read().decode("utf-8")
            return [] if not body else json.loads(body)

    def select(self, table, params=None):
        return self._request("GET", table, params=params)

    def insert(self, table, rows):
        if not rows:
            return []
        return self._request("POST", table, payload=rows, prefer="return=minimal")

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return []
        return self._request(
            "POST",
            table,
            params={"on_conflict": on_conflict},
            payload=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )


def _clean_records(frame):
    if isinstance(frame, list):
        return frame
    clean = frame.where(pd.notna(frame), None)
    return clean.to_dict("records")


def _select_all(client, table, columns="*"):
    rows = []
    offset = 0
    page_size = 10000
    while True:
        page = client.select(table, {"select": columns, "limit": page_size, "offset": offset, "order": "id.asc"})
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def _duplicate_count(client, facility, month, year):
    rows = client.select(
        "report_bundles",
        {
            "select": "id",
            "facility": f"eq.{facility}",
            "file_month": f"eq.{month}",
            "file_year": f"eq.{year}",
            "limit": 1,
        },
    )
    return len(rows)


def _rules_fired(row):
    return ",".join(name for name, column in RULE_COLUMNS if int(row.get(column, 0)) == 1)


def _flag_rows_for_supabase(flagged):
    if not len(flagged):
        return []
    rows = []
    for _, row in flagged.iterrows():
        rows.append({
            "facility": row["facility"],
            "dcs": row["dcs"],
            "society_name": row["society_name"],
            "date": row["date"],
            "shift": row["shift"],
            "vehicle": row.get("vehicle"),
            "qty": row.get("qty"),
            "fat_pct": row.get("fat_pct"),
            "snf_pct": row.get("snf_pct"),
            "clr": row.get("clr"),
            "z_snf": row.get("z_snf"),
            "z_fat": row.get("z_fat"),
            "z_clr": row.get("z_clr"),
            "z_qty": row.get("z_qty"),
            "rules_fired": _rules_fired(row),
            "diagnosis": row["diagnosis"],
            "confidence": row["confidence"],
            "explanation": row["explanation"],
            "seasonal_suppressed": bool(row.get("seasonal_likely", 0)),
            "file_month": int(row["file_month"]),
            "file_year": int(row["file_year"]),
        })
    return rows


def _month_summary_rows(month_summaries):
    if not len(month_summaries):
        return []
    rows = []
    for _, row in month_summaries.iterrows():
        rows.append({
            "facility": row["facility"],
            "file_month": int(row["file_month"]),
            "file_year": int(row["file_year"]),
            "records_processed": int(row["records_processed"]),
            "societies_active": int(row["societies_active"]),
            "initial_flags": int(row["initial_flags"]),
            "seasonal_suppressed": int(row["seasonal_suppressed"]),
            "final_flags": int(row["final_flags"]),
            "high_confidence_flags": int(row["high_confidence_flags"]),
            "top_diagnosis": row["top_diagnosis"],
            "top_flagged_societies": row["top_flagged_societies"],
            "notes": row.get("notes", ""),
            "mode": row.get("mode", ""),
        })
    return rows


def _audit_rows(facility, month, year, audit_trail):
    rows = []
    for _, row in audit_trail.iterrows():
        rows.append({
            "facility": facility,
            "file_month": int(month),
            "file_year": int(year),
            "metric": row["metric"],
            "value": int(row["value"]),
            "mode": row.get("mode", ""),
        })
    return rows


def _report_bundle_row(bundle, report_pdf_path):
    identity = bundle["file_identity"]
    return [{
        "facility": identity["facility"],
        "file_month": int(identity["file_month"]),
        "file_year": int(identity["file_year"]),
        "mode": bundle["processing_metrics"]["mode"],
        "report_pdf_path": str(report_pdf_path),
        "bundle_json": bundle,
    }]


def process_file_to_supabase(file_path, client=None, force=False, report_output_dir=None):
    client = client or SupabaseRestClient()
    month_df = pipeline.load_file(file_path)
    if month_df is None or not len(month_df):
        raise ValueError(f"No usable rows parsed from {file_path}")
    facility = month_df["facility"].iloc[0]
    month = int(month_df["file_month"].iloc[0])
    year = int(month_df["file_year"].iloc[0])
    if _duplicate_count(client, facility, month, year) and not force:
        raise RuntimeError(f"{facility} {year}-{month:02d} is already present in report_bundles. Use --force only after cleanup.")

    history_rows = _select_all(client, "society_month_stats", ",".join(MONTH_STATS_COLUMNS))
    history_df = pd.DataFrame(history_rows) if history_rows else pd.DataFrame(columns=MONTH_STATS_COLUMNS)

    result = pipeline.analyze_month(month_df, historical_month_stats=history_df, source_name=str(file_path))
    report_output_dir = Path(report_output_dir or pipeline.ROOT)
    report_pdf_path = build_report.render_report_bundle(
        result["report_bundle"],
        report_output_dir / f"milk_quality_screening_{facility}_{year}_{month:02d}.pdf",
    )

    client.insert("society_month_stats", _clean_records(result["month_stats"][MONTH_STATS_COLUMNS]))
    if len(result["baselines"]):
        client.upsert("society_baselines", _clean_records(result["baselines"][BASELINE_COLUMNS]), "facility,dcs,season")
    if len(result["flagged"]):
        client.insert("flagged_anomalies", _flag_rows_for_supabase(result["flagged"]))
    client.upsert("month_summaries", _month_summary_rows(result["month_summaries"]), "facility,file_month,file_year")
    client.insert("audit_trail", _audit_rows(facility, month, year, result["audit_trail"]))
    client.upsert("report_bundles", _report_bundle_row(result["report_bundle"], report_pdf_path), "facility,file_month,file_year")

    return {
        "facility": facility,
        "file_month": month,
        "file_year": year,
        "mode": result["mode"],
        "records_processed": int(len(month_df)),
        "initial_flags": int(len(result["flagged"])),
        "seasonal_suppressed": int(result["flagged"]["seasonal_likely"].sum()) if len(result["flagged"]) else 0,
        "final_flags": int(len(result["report"])),
        "report_pdf_path": str(report_pdf_path),
    }


def _load_batch_files(file_paths):
    frames = []
    identities = []
    for file_path in file_paths:
        frame = pipeline.load_file(file_path)
        if frame is None or not len(frame):
            raise ValueError(f"No usable rows parsed from {file_path}")
        frames.append(frame)
        identities.append((frame["facility"].iloc[0], int(frame["file_month"].iloc[0]), int(frame["file_year"].iloc[0])))
    months = {month for _, month, _ in identities}
    years = {year for _, _, year in identities}
    if len(months) != 1 or len(years) != 1:
        raise ValueError("All batch files must belong to the same file_month and file_year.")
    return pd.concat(frames, ignore_index=True)


def process_month_files_to_supabase(file_paths, client=None, force=False, report_output_dir=None):
    client = client or SupabaseRestClient()
    file_paths = [Path(path) for path in file_paths]
    if not file_paths:
        raise ValueError("At least one monthly workbook is required.")
    month_df = _load_batch_files(file_paths)
    month = int(month_df["file_month"].iloc[0])
    year = int(month_df["file_year"].iloc[0])
    facility = "ALL"
    if _duplicate_count(client, facility, month, year) and not force:
        raise RuntimeError(f"Consolidated {year}-{month:02d} report is already present in report_bundles. Use --force only after cleanup.")

    history_rows = _select_all(client, "society_month_stats", ",".join(MONTH_STATS_COLUMNS))
    history_df = pd.DataFrame(history_rows) if history_rows else pd.DataFrame(columns=MONTH_STATS_COLUMNS)
    source_name = ", ".join(path.name for path in file_paths)
    result = pipeline.analyze_month(month_df, historical_month_stats=history_df, source_name=source_name)
    report_output_dir = Path(report_output_dir or pipeline.ROOT)
    report_pdf_path = build_report.render_report_bundle(
        result["report_bundle"],
        report_output_dir / f"milk_quality_screening_all_{year}_{month:02d}.pdf",
    )

    client.insert("society_month_stats", _clean_records(result["month_stats"][MONTH_STATS_COLUMNS]))
    if len(result["baselines"]):
        client.upsert("society_baselines", _clean_records(result["baselines"][BASELINE_COLUMNS]), "facility,dcs,season")
    if len(result["flagged"]):
        client.insert("flagged_anomalies", _flag_rows_for_supabase(result["flagged"]))
    client.upsert("month_summaries", _month_summary_rows(result["month_summaries"]), "facility,file_month,file_year")
    client.insert("audit_trail", _audit_rows(facility, month, year, result["audit_trail"]))
    client.upsert("report_bundles", _report_bundle_row(result["report_bundle"], report_pdf_path), "facility,file_month,file_year")

    return {
        "facility": facility,
        "facilities": sorted(month_df["facility"].unique().tolist()),
        "file_month": month,
        "file_year": year,
        "mode": result["mode"],
        "records_processed": int(len(month_df)),
        "initial_flags": int(len(result["flagged"])),
        "seasonal_suppressed": int(result["flagged"]["seasonal_likely"].sum()) if len(result["flagged"]) else 0,
        "final_flags": int(len(result["report"])),
        "report_pdf_path": str(report_pdf_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Process one or more milk collection workbooks into Supabase.")
    parser.add_argument("files", nargs="+", help="Monthly .xls workbooks for the same month/year")
    parser.add_argument("--force", action="store_true", help="Bypass duplicate guard after manual cleanup")
    parser.add_argument("--report-output-dir", help="Directory for generated PDF reports")
    args = parser.parse_args(argv)
    if len(args.files) == 1:
        result = process_file_to_supabase(Path(args.files[0]), force=args.force, report_output_dir=args.report_output_dir)
    else:
        result = process_month_files_to_supabase([Path(path) for path in args.files], force=args.force, report_output_dir=args.report_output_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

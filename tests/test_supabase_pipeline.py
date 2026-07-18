import sys
from pathlib import Path

import pandas as pd
import pytest


SNF_ROOT = Path(__file__).resolve().parents[1]
if str(SNF_ROOT) not in sys.path:
    sys.path.insert(0, str(SNF_ROOT))

import supabase_pipeline


class FakeSupabase:
    def __init__(self, duplicate=False, history_rows=None):
        self.duplicate = duplicate
        self.history_rows = history_rows or []
        self.inserted = {}
        self.upserted = {}

    def select(self, table, params=None):
        params = params or {}
        if table == "report_bundles" and params.get("limit") == 1:
            return [{"id": 1}] if self.duplicate else []
        if table == "society_month_stats":
            return self.history_rows
        return []

    def insert(self, table, rows):
        self.inserted.setdefault(table, []).extend(rows)
        return []

    def upsert(self, table, rows, on_conflict):
        self.upserted.setdefault(table, []).extend(rows)
        return []


def _month_frame():
    return pd.DataFrame(
        [
            {
                "serial_no": 1,
                "vehicle": "V1",
                "date": "01-04-2026",
                "shift": "M",
                "dcs": 101.0,
                "society_name": "Alpha",
                "qty": 100.0,
                "fat_pct": 5.0,
                "snf_pct": 8.6,
                "clr": 28.0,
                "kg_fat": 5.0,
                "kg_snf": 8.6,
                "rate": 40.0,
                "amount": 4000.0,
                "facility": "FacilityAlpha",
                "file_month": 4,
                "file_year": 2026,
                "season": "summer",
            }
        ]
    )


def test_process_file_to_supabase_seed_mode_writes_compact_outputs(monkeypatch, tmp_path):
    client = FakeSupabase()
    monkeypatch.setattr(supabase_pipeline.pipeline, "load_file", lambda path: _month_frame())

    result = supabase_pipeline.process_file_to_supabase(
        "FacilityAlpha milk collection for the month of April 2026.xls",
        client=client,
        report_output_dir=tmp_path,
    )

    assert result["mode"] == "seed_only"
    assert len(client.inserted["society_month_stats"]) == 1
    assert "flagged_anomalies" not in client.inserted
    assert "report_bundles" in client.upserted
    assert "audit_trail" in client.inserted
    assert result["report_pdf_path"].endswith(".pdf")


def test_process_file_to_supabase_blocks_duplicate_month(monkeypatch):
    client = FakeSupabase(duplicate=True)
    monkeypatch.setattr(supabase_pipeline.pipeline, "load_file", lambda path: _month_frame())

    with pytest.raises(RuntimeError, match="already present"):
        supabase_pipeline.process_file_to_supabase(
            "FacilityAlpha milk collection for the month of April 2026.xls",
            client=client,
        )


def test_process_month_files_to_supabase_writes_one_consolidated_bundle(monkeypatch, tmp_path):
    client = FakeSupabase()
    facility_alpha = _month_frame()
    facility_beta = _month_frame().assign(facility="FacilityBeta", dcs=202.0, society_name="Beta")

    def fake_load_file(path):
        return facility_alpha if "FacilityAlpha" in str(path) else facility_beta

    monkeypatch.setattr(supabase_pipeline.pipeline, "load_file", fake_load_file)

    result = supabase_pipeline.process_month_files_to_supabase(
        [
            "FacilityAlpha milk collection for the month of April 2026.xls",
            "FacilityBeta milk collection for the month of April 2026.xls",
        ],
        client=client,
        report_output_dir=tmp_path,
    )

    assert result["facility"] == "ALL"
    assert result["facilities"] == ["FacilityAlpha", "FacilityBeta"]
    assert len(client.inserted["society_month_stats"]) == 2
    assert len(client.upserted["report_bundles"]) == 1
    assert client.upserted["report_bundles"][0]["facility"] == "ALL"
    assert client.upserted["report_bundles"][0]["bundle_json"]["file_identity"]["facilities"] == ["FacilityAlpha", "FacilityBeta"]

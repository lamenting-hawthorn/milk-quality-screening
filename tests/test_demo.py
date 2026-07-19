import json
import sqlite3
from contextlib import closing

import demo


def test_demo_runs_end_to_end_and_finds_injected_event(tmp_path):
    summary = demo.run_demo(tmp_path / "demo", render_pdf=False)

    assert summary["periods_processed"] == 4
    assert summary["records_processed"] == 1200
    assert summary["latest_mode"] == "detection"
    assert summary["latest_screening_records"] == 1

    bundle = json.loads((tmp_path / "demo" / "latest_analysis_bundle.json").read_text(encoding="utf-8"))
    injected = [
        row
        for row in bundle["report_records"]
        if row["dcs"] == 101 and row["date"] == "30-04-2026" and row["shift"] == "M"
    ]
    assert len(injected) == 1
    assert injected[0]["diagnosis"] == "LOW_DENSITY_COMPOSITION_SCREEN"

    with closing(sqlite3.connect(tmp_path / "demo" / "screening.db")) as connection:
        periods = connection.execute("SELECT COUNT(*) FROM report_bundles").fetchone()[0]
    assert periods == 4

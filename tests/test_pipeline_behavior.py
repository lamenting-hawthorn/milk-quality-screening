import pandas as pd
import pytest

import pipeline


def _records(rows):
    defaults = {
        "facility": "FacilityAlpha",
        "dcs": 101.0,
        "society_name": "Test Society",
        "date": "01-04-2025",
        "shift": "M",
        "vehicle": "V1",
        "qty": 100.0,
        "fat_pct": 5.0,
        "snf_pct": 8.6,
        "clr": 28.0,
        "file_month": 4,
        "file_year": 2025,
        "season": "summer",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _baseline(
    *,
    facility="FacilityAlpha",
    dcs=101.0,
    season="summer",
    record_count=30,
    fat_mean=5.0,
    fat_std=0.2,
    snf_mean=8.6,
    snf_std=0.2,
    clr_mean=28.0,
    clr_std=0.5,
    qty_mean=100.0,
    qty_std=10.0,
    snf_p90=None,
):
    return {
        "facility": facility,
        "dcs": dcs,
        "society_name": "Test Society",
        "season": season,
        "record_count": record_count,
        "fat_pct_mean": fat_mean,
        "fat_pct_std": fat_std,
        "snf_pct_mean": snf_mean,
        "snf_pct_std": snf_std,
        "snf_pct_p90": snf_p90,
        "clr_mean": clr_mean,
        "clr_std": clr_std,
        "qty_mean": qty_mean,
        "qty_std": qty_std,
    }


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("FacilityAlpha milk collection for the month of March 2026.xls", ("FacilityAlpha", 3, 2026)),
        (
            "FacilityBeta milk collection report for the month of Sept 2025.xls",
            ("FacilityBeta", 9, 2025),
        ),
        (
            "FacilityGamma milk collection report For the Month of July 2025.xls",
            ("FacilityGamma", 7, 2025),
        ),
    ],
)
def test_parse_filename_variants(filename, expected):
    assert pipeline.parse_filename(filename) == expected


@pytest.mark.parametrize(
    ("filename", "frame"),
    [
        (
            "FacilityBeta milk collection for the month of April 2025.xls",
            pd.DataFrame(
                [
                    {
                        "S.NO.": 1,
                        "VCH.": " 12 ",
                        "DATE": "01-04-2025",
                        "SHIFT.": "Morning",
                        "DCS": 10,
                        "SOCIETY NAME": "  Alpha  ",
                        "QTY": "100",
                        "Fat %": "5.1",
                        "Snf %": "8.7",
                        "CLR": "28",
                        "Kg, Fat": "5.1",
                        "Kg. Snf": "8.7",
                        "Rate": "40",
                        "Amount": "4000",
                        "Unnamed: 17": "ignored",
                    },
                    {"S.NO.": None, "SOCIETY NAME": "TOTAL", "QTY": "100"},
                ]
            ),
        ),
        (
            "FacilityAlpha milk collection report for the month of Jan 2026.xls",
            pd.DataFrame(
                [
                    {
                        "Sl No": 1,
                        "Veh No.": " V9 ",
                        "Date": "01-01-2026",
                        "Shift": "Evening",
                        "DCS No.": 20,
                        "Society Name": "  Beta  ",
                        "Qty": "200",
                        "Fat %": "6.2",
                        "Snf %": "8.9",
                        "Clr": "29",
                        "Kg. Fat": "12.4",
                        "Kg. Snf": "17.8",
                        "Rate": "42",
                        "Amount": "8400",
                        "Data": "ignored",
                    },
                    {"Sl No": None, "Society Name": "TOTAL", "Qty": "200"},
                ]
            ),
        ),
    ],
)
def test_load_file_accepts_both_excel_column_variants(monkeypatch, filename, frame):
    monkeypatch.setattr(pipeline.pd, "read_excel", lambda path, engine: frame)

    loaded = pipeline.load_file(filename)

    assert len(loaded) == 1
    row = loaded.iloc[0]
    assert list(loaded.columns).count("serial_no") == 1
    assert row["facility"] == filename.split()[0]
    assert row["society_name"] in {"Alpha", "Beta"}
    assert row["shift"] in {"M", "E"}
    assert row["season"] in {"summer", "winter"}
    assert "Unnamed: 17" not in loaded.columns
    assert "Data" not in loaded.columns


def test_apply_rules_uses_matching_season_baseline_before_all_year_fallback():
    df = _records(
        [
            {
                "date": "01-01-2026",
                "file_month": 1,
                "season": "winter",
                "snf_pct": 8.0,
                "clr": 26.0,
            }
        ]
    )
    baselines = pd.DataFrame(
        [
            _baseline(
                season="winter",
                record_count=15,
                snf_mean=8.0,
                snf_std=0.1,
                clr_mean=26.0,
                clr_std=0.2,
            )
        ]
    )

    assert pipeline.apply_rules(df, baselines).empty


def test_apply_rules_falls_back_to_all_year_when_seasonal_baseline_is_thin():
    normal = [
        {"date": f"{day:02d}-04-2025", "snf_pct": 8.8, "clr": 28.0}
        for day in range(1, 31)
    ]
    winter_anomaly = {
        "date": "01-01-2026",
        "file_month": 1,
        "season": "winter",
        "snf_pct": 7.2,
        "clr": 24.0,
    }
    df = _records([*normal, winter_anomaly])
    baselines = pd.DataFrame(
        [
            _baseline(season="winter", record_count=10),
            _baseline(
                season="all",
                record_count=31,
                snf_mean=8.8,
                snf_std=0.2,
                clr_mean=28.0,
                clr_std=0.5,
            ),
        ]
    )

    flagged = pipeline.apply_rules(df, baselines)

    row = flagged[flagged["date"] == "01-01-2026"].iloc[0]
    assert row["low_seasonal_data"] == 1
    assert row["R1_snf_drop"] == 1
    assert row["R7_clr_drop"] == 1


def test_run_pipeline_processes_months_in_order_and_uses_prior_history(monkeypatch, tmp_path):
    rows = []
    for month in range(1, 5):
        for society_number in range(1, 5):
            for day in range(1, 31):
                rows.append(
                    {
                        "facility": "FacilityAlpha",
                        "dcs": 100.0 + society_number,
                        "society_name": f"Synthetic Society {society_number}",
                        "date": f"{day:02d}-{month:02d}-2026",
                        "shift": "M" if day % 2 else "E",
                        "vehicle": f"SyntheticVehicle{society_number}",
                        "qty": 100.0 + (day % 5) - 2,
                        "fat_pct": 5.0 + ((day % 5) - 2) * 0.05,
                        "snf_pct": 8.6 + ((day % 5) - 2) * 0.04,
                        "clr": 28.0 + ((day % 5) - 2) * 0.1,
                        "file_month": month,
                        "file_year": 2026,
                        "season": pipeline.season_for_month(month),
                    }
                )
    records = pd.DataFrame(rows)
    records.loc[
        (records["file_month"] == 4) & (records["dcs"] == 101.0) & (records["date"] == "01-04-2026"),
        ["snf_pct", "clr"],
    ] = [7.0, 23.0]
    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: records)

    result = pipeline.run_pipeline("synthetic-input", tmp_path / "screening.db")

    assert len(result["runs"]) == 4
    assert [run["mode"] for run in result["runs"][:3]] == ["seed_only"] * 3
    assert result["runs"][3]["mode"] == "detection"
    assert result["runs"][3]["report_bundle"]["history_inputs"]["historical_month_stats_count"] == 12
    assert result["records_processed"] == 480
    assert (tmp_path / "screening.db").exists()


def test_run_pipeline_preserves_prior_history_and_skips_an_idempotent_period(monkeypatch, tmp_path):
    database = tmp_path / "screening.db"
    first_month = _records(
        [
            {
                "date": f"{day:02d}-01-2026",
                "file_month": 1,
                "file_year": 2026,
                "season": "winter",
            }
            for day in range(1, 31)
        ]
    )
    second_month = _records(
        [
            {
                "date": f"{day:02d}-02-2026",
                "file_month": 2,
                "file_year": 2026,
                "season": "winter",
            }
            for day in range(1, 31)
        ]
    )

    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: first_month)
    pipeline.run_pipeline("first", database)
    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: second_month)
    result = pipeline.run_pipeline("second", database)

    with pipeline.closing(pipeline.sqlite3.connect(database)) as connection:
        stored_months = connection.execute("SELECT COUNT(*) FROM report_bundles").fetchone()[0]
    assert result["runs"][0]["report_bundle"]["history_inputs"]["historical_month_stats_count"] == 1
    assert stored_months == 2

    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: second_month)
    with pytest.raises(ValueError, match="No new reporting periods"):
        pipeline.run_pipeline("second-again", database)
    with pipeline.closing(pipeline.sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM report_bundles").fetchone()[0] == 2


def test_inspect_collection_frame_returns_row_level_rejections():
    frame = pd.DataFrame(
        [
            {
                "S.NO.": 1,
                "VCH.": "V1",
                "DATE": "01-04-2026",
                "SHIFT.": "Morning",
                "DCS": 101,
                "SOCIETY NAME": "Alpha",
                "QTY": "100",
                "Fat %": "5.0",
                "Snf %": "8.6",
                "CLR": "28",
            },
            {
                "S.NO.": 2,
                "VCH.": "V1",
                "DATE": "02-04-2026",
                "SHIFT.": "Evening",
                "DCS": 101,
                "SOCIETY NAME": "Alpha",
                "QTY": "not-a-number",
                "Fat %": "5.0",
                "Snf %": "8.6",
                "CLR": "28",
            },
        ]
    )

    accepted, rejected, diagnostics = pipeline.inspect_collection_frame(frame, "FacilityAlpha", 4, 2026)

    assert len(accepted) == 1
    assert len(rejected) == 1
    assert "missing_or_invalid_qty" in rejected.iloc[0]["rejection_reason"]
    assert diagnostics["contract_version"] == "collection-workbook-v1"
    with pytest.raises(pipeline.InputValidationError, match="rejected data row"):
        pipeline.normalize_collection_frame(frame, "FacilityAlpha", 4, 2026)


def test_inspect_collection_frame_rejects_populated_rows_without_serial_number():
    frame = pd.DataFrame(
        [
            {
                "S.NO.": None,
                "VCH.": "V1",
                "DATE": "01-04-2026",
                "SHIFT.": "Morning",
                "DCS": 101,
                "SOCIETY NAME": "Alpha",
                "QTY": "100",
                "Fat %": "5.0",
                "Snf %": "8.6",
                "CLR": "28",
            }
        ]
    )

    accepted, rejected, diagnostics = pipeline.inspect_collection_frame(frame, "FacilityAlpha", 4, 2026)

    assert accepted.empty
    assert len(rejected) == 1
    assert rejected.iloc[0]["rejection_reason"] == "missing_serial_no"
    assert diagnostics["rejected_rows"] == 1


def test_recurring_signal_indicators_are_neutral_and_do_not_attribute_cause():
    report = _records(
        [
            {"date": "01-04-2026", "diagnosis": "LOW_DENSITY_COMPOSITION_SCREEN", "confidence": "RESAMPLE"},
            {"date": "02-04-2026", "diagnosis": "LOW_DENSITY_COMPOSITION_SCREEN", "confidence": "REVIEW"},
        ]
    )

    indicators = pipeline.build_recurring_signal_indicators(report)

    assert indicators[0]["indicator"] == "RECURRING_SCREENING_PATTERN"
    assert indicators[0]["screening_signal_count"] == 2
    assert "adulter" not in indicators[0]["interpretation"].lower()


def test_recurring_signal_indicators_preserve_monitor_priority():
    report = _records(
        [
            {"date": "01-04-2026", "diagnosis": "UNCLASSIFIED_SCREENING_SIGNAL", "confidence": "MONITOR"},
            {"date": "02-04-2026", "diagnosis": "UNCLASSIFIED_SCREENING_SIGNAL", "confidence": "MONITOR"},
        ]
    )

    assert pipeline.build_recurring_signal_indicators(report)[0]["highest_priority"] == "MONITOR"


def test_run_pipeline_initializes_empty_review_cases_and_honors_legacy_all_period(monkeypatch, tmp_path):
    database = tmp_path / "screening.db"
    seed_only = _records(
        [
            {
                "date": f"{day:02d}-01-2026",
                "file_month": 1,
                "file_year": 2026,
                "season": "winter",
            }
            for day in range(1, 31)
        ]
    )
    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: seed_only)
    pipeline.run_pipeline("seed", database)
    with pipeline.closing(pipeline.sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM review_cases").fetchone()[0] == 0

    legacy_period = seed_only.assign(facility="FacilityBeta")
    with pipeline.closing(pipeline.sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO report_bundles VALUES (?, ?, ?, ?)", ("ALL", 2026, 2, "{}"))
        connection.commit()
    legacy_period["file_month"] = 2
    monkeypatch.setattr(pipeline, "load_all", lambda source_dir: legacy_period)
    with pytest.raises(ValueError, match="No new reporting periods"):
        pipeline.run_pipeline("legacy", database)


def test_r5_clr_spike_only_flags_high_clr_direction():
    df = _records(
        [
            {"date": "01-04-2025", "clr": 29.6},
            {"date": "02-04-2025", "clr": 24.0},
        ]
    )
    baselines = pd.DataFrame([_baseline(clr_mean=28.0, clr_std=0.5)])

    flagged = pipeline.apply_rules(df, baselines)

    high = flagged[flagged["date"] == "01-04-2025"].iloc[0]
    assert high["R5_clr_spike"] == 1
    low = flagged[flagged["date"] == "02-04-2025"].iloc[0]
    assert low["R5_clr_spike"] == 0


def test_r3_uses_per_society_fat_threshold_not_fixed_low_fat_cutoff():
    low_fat_society = _records([{"fat_pct": 2.9}])
    low_fat_baseline = pd.DataFrame([_baseline(fat_mean=3.3, fat_std=0.1)])
    assert pipeline.apply_rules(low_fat_society, low_fat_baseline).empty

    high_fat_society = _records([{"fat_pct": 3.8}])
    high_fat_baseline = pd.DataFrame([_baseline(fat_mean=6.0, fat_std=0.2)])
    flagged = pipeline.apply_rules(high_fat_society, high_fat_baseline)
    assert flagged.iloc[0]["R3_fat_drop"] == 1


def test_legacy_r8_is_disabled_even_when_five_rows_exceed_p90():
    rows = [
        {"date": f"{day:02d}-04-2025", "snf_pct": 9.1}
        for day in range(1, 6)
    ] + [
        {"date": "06-04-2025", "snf_pct": 8.8},
        {"date": "07-04-2025", "snf_pct": 8.7},
    ]
    df = _records(rows)
    baselines = pd.DataFrame(
        [_baseline(snf_mean=8.8, snf_std=1.0, snf_p90=9.0)]
    )

    flagged = pipeline.apply_rules(df, baselines)

    assert flagged.empty


def test_seasonal_filter_suppresses_directional_facility_wide_flags():
    all_records = _records(
        [
            {"dcs": float(dcs), "society_name": f"Society {dcs}"}
            for dcs in range(1, 11)
        ]
    )
    flagged = _records(
        [
            {
                "dcs": float(dcs),
                "society_name": f"Society {dcs}",
                "z_snf": -2.2,
                "z_fat": -1.4,
                "z_clr": -1.3,
            }
            for dcs in range(1, 5)
        ]
    )

    filtered = pipeline.seasonal_filter(flagged, all_records)

    assert filtered["pct_flagged"].eq(40.0).all()
    assert filtered["seasonal_likely"].eq(1).all()


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"R1_snf_drop": 1, "R7_clr_drop": 1},
            ("LOW_DENSITY_COMPOSITION_SCREEN", "RESAMPLE", "S1_7"),
        ),
        (
            {"R2_snf_spike": 1, "R5_clr_spike": 1},
            ("HIGH_DENSITY_COMPOSITION_SCREEN", "RESAMPLE", "S2_5"),
        ),
        (
            {"R5_clr_spike": 1},
            ("HIGH_DENSITY_SCREEN", "REVIEW", "S5"),
        ),
        (
            {
                "z_snf": 0.0,
                "z_fat": 0.0,
                "z_clr": 0.0,
                "z_qty": 0.0,
                "clr": 28.0,
                "R8_repeated_spike": 1,
            },
            ("LEGACY_RULE_DISABLED", "MONITOR", "S_LEGACY"),
        ),
    ],
)
def test_diagnosis_cases(row, expected):
    assert pipeline.diagnose(pd.Series(row)) == expected


def test_measurement_directions_alone_do_not_create_substance_claims():
    row = pd.Series({"z_snf": 1.5, "z_fat": -1.4, "z_clr": 1.8, "z_qty": 2.0})

    category, priority, _ = pipeline.diagnose(row)

    assert category == "UNCLASSIFIED_SCREENING_SIGNAL"
    assert priority == "MONITOR"
    assert not any(term in category for term in ("SALT", "UREA", "AMMONIUM", "WATER"))


def test_build_baselines_from_month_stats_uses_prior_months_only():
    history = pd.DataFrame(
        [
            {
                "facility": "FacilityAlpha",
                "dcs": 101.0,
                "society_name": "Alpha",
                "file_year": 2025,
                "file_month": 4,
                "season": "summer",
                "record_count": 10,
                "fat_pct_mean": 5.0,
                "fat_pct_std": 0.2,
                "fat_pct_median": 5.0,
                "fat_pct_q1": 4.9,
                "fat_pct_q3": 5.1,
                "fat_pct_p90": 5.2,
                "fat_pct_p10": 4.8,
                "snf_pct_mean": 8.6,
                "snf_pct_std": 0.2,
                "snf_pct_median": 8.6,
                "snf_pct_q1": 8.5,
                "snf_pct_q3": 8.7,
                "snf_pct_p90": 8.8,
                "snf_pct_p10": 8.4,
                "clr_mean": 28.0,
                "clr_std": 0.4,
                "clr_median": 28.0,
                "clr_q1": 27.8,
                "clr_q3": 28.2,
                "clr_p90": 28.4,
                "clr_p10": 27.6,
                "qty_mean": 100.0,
                "qty_std": 10.0,
                "qty_median": 100.0,
                "qty_q1": 95.0,
                "qty_q3": 105.0,
                "qty_p90": 110.0,
                "qty_p10": 90.0,
            },
            {
                "facility": "FacilityAlpha",
                "dcs": 101.0,
                "society_name": "Alpha",
                "file_year": 2025,
                "file_month": 5,
                "season": "summer",
                "record_count": 12,
                "fat_pct_mean": 5.1,
                "fat_pct_std": 0.2,
                "fat_pct_median": 5.1,
                "fat_pct_q1": 5.0,
                "fat_pct_q3": 5.2,
                "fat_pct_p90": 5.3,
                "fat_pct_p10": 4.9,
                "snf_pct_mean": 8.7,
                "snf_pct_std": 0.2,
                "snf_pct_median": 8.7,
                "snf_pct_q1": 8.6,
                "snf_pct_q3": 8.8,
                "snf_pct_p90": 8.9,
                "snf_pct_p10": 8.5,
                "clr_mean": 28.1,
                "clr_std": 0.4,
                "clr_median": 28.1,
                "clr_q1": 27.9,
                "clr_q3": 28.3,
                "clr_p90": 28.5,
                "clr_p10": 27.7,
                "qty_mean": 101.0,
                "qty_std": 10.0,
                "qty_median": 101.0,
                "qty_q1": 96.0,
                "qty_q3": 106.0,
                "qty_p90": 111.0,
                "qty_p10": 91.0,
            },
            {
                "facility": "FacilityAlpha",
                "dcs": 101.0,
                "society_name": "Alpha",
                "file_year": 2025,
                "file_month": 6,
                "season": "summer",
                "record_count": 14,
                "fat_pct_mean": 5.2,
                "fat_pct_std": 0.2,
                "fat_pct_median": 5.2,
                "fat_pct_q1": 5.1,
                "fat_pct_q3": 5.3,
                "fat_pct_p90": 5.4,
                "fat_pct_p10": 5.0,
                "snf_pct_mean": 8.8,
                "snf_pct_std": 0.2,
                "snf_pct_median": 8.8,
                "snf_pct_q1": 8.7,
                "snf_pct_q3": 8.9,
                "snf_pct_p90": 9.0,
                "snf_pct_p10": 8.6,
                "clr_mean": 28.2,
                "clr_std": 0.4,
                "clr_median": 28.2,
                "clr_q1": 28.0,
                "clr_q3": 28.4,
                "clr_p90": 28.6,
                "clr_p10": 27.8,
                "qty_mean": 102.0,
                "qty_std": 10.0,
                "qty_median": 102.0,
                "qty_q1": 97.0,
                "qty_q3": 107.0,
                "qty_p90": 112.0,
                "qty_p10": 92.0,
            },
        ]
    )

    baselines = pipeline.build_baselines_from_month_stats(history, 2025, 7)

    summer = baselines[(baselines["season"] == "summer")].iloc[0]
    assert summer["prior_month_count"] == 3
    assert summer["same_season_prior_month_count"] == 3
    assert summer["eligible"] == 1


def test_analyze_month_seed_mode_generates_report_bundle_without_anomalies():
    month = _records(
        [
            {"date": "01-04-2026", "dcs": 101.0, "society_name": "Alpha"},
            {"date": "02-04-2026", "dcs": 102.0, "society_name": "Beta"},
        ]
    )

    result = pipeline.analyze_month(month, historical_month_stats=pd.DataFrame(), source_name="April.xls")

    assert result["mode"] == "seed_only"
    assert result["flagged"].empty
    assert result["report_bundle"]["sections"]["executive_summary"]["mode"] == "seed_only"
    assert result["report_bundle"]["sections"]["calibration"]["watchlist"]


def test_report_bundle_contains_human_report_sections():
    month = _records([{"date": "01-04-2026"}])
    result = pipeline.analyze_month(month, historical_month_stats=pd.DataFrame(), source_name="April.xls")

    sections = result["report_bundle"]["sections"]
    assert "executive_summary" in sections
    assert "audit_trail" in sections
    assert "facility_overview" in sections
    assert "diagnosis_distribution" in sections
    assert "top_offenders" in sections
    assert "detail_logs" in sections
    assert "action_plan" in sections
    assert "methodology" in sections
    assert result["report_bundle"]["methodology_version"] == "screening-v1-safety"
    assert "confirm" in result["report_bundle"]["disclaimer"].lower()
    assert "screening_distribution" in sections
    serialized = str(result["report_bundle"])
    assert "SALT/AMMONIUM" not in serialized
    assert "pattern fraud" not in serialized

import sqlite3

import pytest

import case_workflow


def _seed_case(database):
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE review_cases (
                case_id TEXT PRIMARY KEY, facility TEXT, dcs REAL, society_name TEXT,
                file_year INTEGER, file_month INTEGER, screening_date TEXT, shift TEXT,
                screening_category TEXT, priority TEXT, status TEXT,
                recommended_next_step TEXT, disposition TEXT, confirmation_reference TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO review_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("case-1", "FacilityAlpha", 101, "Alpha", 2026, 4, "01-04-2026", "M", "LOW_DENSITY_COMPOSITION_SCREEN", "MONITOR", "OPEN", "Resample", None, None),
        )
        connection.execute(
            "INSERT INTO review_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("case-2", "FacilityAlpha", 102, "Beta", 2026, 4, "01-04-2026", "M", "LOW_DENSITY_COMPOSITION_SCREEN", "RESAMPLE", "OPEN", "Resample", None, None),
        )


def test_case_workflow_lists_and_updates_human_disposition(tmp_path):
    database = tmp_path / "screening.db"
    _seed_case(database)

    assert [case["case_id"] for case in case_workflow.list_cases(database, "OPEN")] == ["case-2", "case-1"]
    result = case_workflow.update_case(
        database, "case-1", "lab_pending", "Controlled resample sent", "COC-2026-0042"
    )

    assert result == {"case_id": "case-1", "status": "LAB_PENDING"}
    case = case_workflow.list_cases(database, "LAB_PENDING")[0]
    assert case["disposition"] == "Controlled resample sent"
    assert case["confirmation_reference"] == "COC-2026-0042"


def test_case_workflow_rejects_unknown_status_and_case(tmp_path):
    database = tmp_path / "screening.db"
    _seed_case(database)

    with pytest.raises(ValueError, match="Unsupported status"):
        case_workflow.update_case(database, "case-1", "FRAUD")
    with pytest.raises(ValueError, match="Unknown case_id"):
        case_workflow.update_case(database, "missing", "OPEN")

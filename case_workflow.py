"""Local review-case workflow for screening results.

Cases record operational follow-up. They do not confirm adulteration, intent,
or fraud; confirmation must reference an appropriate controlled process.
"""
import argparse
import json
import sqlite3
from pathlib import Path

ALLOWED_STATUSES = {
    "OPEN",
    "UNDER_REVIEW",
    "RESAMPLE_REQUESTED",
    "LAB_PENDING",
    "CONFIRMED",
    "DISMISSED",
}


def list_cases(db_path, status=None):
    """Return review cases, optionally filtered by their operational status."""
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        query = "SELECT * FROM review_cases"
        parameters = []
        if status:
            query += " WHERE status = ?"
            parameters.append(status)
        query += """
            ORDER BY file_year DESC, file_month DESC,
                CASE priority
                    WHEN 'RESAMPLE' THEN 1
                    WHEN 'REVIEW' THEN 2
                    WHEN 'MONITOR' THEN 3
                    ELSE 4
                END,
                case_id
        """
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def update_case(db_path, case_id, status, disposition=None, confirmation_reference=None):
    """Record a human review outcome for an existing case."""
    status = status.upper()
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported status {status!r}; choose one of {sorted(ALLOWED_STATUSES)}")
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            """
            UPDATE review_cases
            SET status = ?, disposition = COALESCE(?, disposition),
                confirmation_reference = COALESCE(?, confirmation_reference)
            WHERE case_id = ?
            """,
            (status, disposition, confirmation_reference, case_id),
        )
        if cursor.rowcount != 1:
            raise ValueError(f"Unknown case_id {case_id!r}")
        connection.commit()
    return {"case_id": case_id, "status": status}


def main(argv=None):
    parser = argparse.ArgumentParser(description="List and update local milk-quality review cases.")
    parser.add_argument("--db", required=True, help="SQLite database created by milk-quality-screen")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="List review cases")
    list_parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES))
    update_parser = subparsers.add_parser("update", help="Record a review outcome")
    update_parser.add_argument("case_id")
    update_parser.add_argument("--status", required=True, choices=sorted(ALLOWED_STATUSES))
    update_parser.add_argument("--disposition")
    update_parser.add_argument("--confirmation-reference")
    args = parser.parse_args(argv)
    database = Path(args.db)
    if args.command == "list":
        print(json.dumps(list_cases(database, args.status), indent=2))
    else:
        print(
            json.dumps(
                update_case(database, args.case_id, args.status, args.disposition, args.confirmation_reference),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

"""Generate deterministic, privacy-safe milk collection demo workbooks."""

import argparse
import calendar
import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED = 20260719
FACILITY = "FacilityAlpha"
SOCIETIES = tuple((100 + index, f"Synthetic Society {index}") for index in range(1, 6))
MONTHS = (1, 2, 3, 4)
YEAR = 2026
INJECTED_EVENT = {
    "month": 4,
    "day": 30,
    "shift": "Morning",
    "dcs": 101,
    "snf_pct": 7.0,
    "clr": 23.0,
    "description": "Controlled low-solids and low-density screening event",
}


def _month_frame(month, rng):
    rows = []
    serial_number = 1
    days_in_month = calendar.monthrange(YEAR, month)[1]

    for day in range(1, days_in_month + 1):
        for shift in ("Morning", "Evening"):
            for society_index, (dcs, society_name) in enumerate(SOCIETIES, start=1):
                seasonal_offset = 0.03 * (month - 1)
                fat = 5.0 + society_index * 0.08 - seasonal_offset + rng.normal(0, 0.08)
                snf = 8.6 + society_index * 0.025 - seasonal_offset / 2 + rng.normal(0, 0.06)
                clr = 28.0 + society_index * 0.08 - seasonal_offset + rng.normal(0, 0.22)
                qty = 95.0 + society_index * 4 + rng.normal(0, 4.0)

                if (
                    month == INJECTED_EVENT["month"]
                    and day == INJECTED_EVENT["day"]
                    and shift == INJECTED_EVENT["shift"]
                    and dcs == INJECTED_EVENT["dcs"]
                ):
                    snf = INJECTED_EVENT["snf_pct"]
                    clr = INJECTED_EVENT["clr"]

                date = pd.Timestamp(year=YEAR, month=month, day=day)
                rows.append(
                    {
                        "Sl No": serial_number,
                        "Veh No.": f"SYN-{society_index:02d}",
                        "Date": date.strftime("%d-%m-%Y"),
                        "Shift": shift,
                        "DCS No.": dcs,
                        "Society Name": society_name,
                        "Qty": round(max(qty, 10), 2),
                        "Fat %": round(fat, 2),
                        "Snf %": round(snf, 2),
                        "Clr": round(clr, 2),
                        "Kg. Fat": round(max(qty, 10) * fat / 100, 2),
                        "Kg. Snf": round(max(qty, 10) * snf / 100, 2),
                        "Rate": 40.0,
                        "Amount": round(max(qty, 10) * 40.0, 2),
                    }
                )
                serial_number += 1

    return pd.DataFrame(rows)


def generate_synthetic_workbooks(output_dir, seed=DEFAULT_SEED):
    """Write reproducible workbook content and return a JSON-safe manifest."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    files = []
    records = 0

    for month in MONTHS:
        frame = _month_frame(month, rng)
        month_name = calendar.month_name[month]
        path = output_dir / f"{FACILITY} milk collection for the month of {month_name} {YEAR}.xlsx"
        frame.to_excel(path, index=False, engine="openpyxl")
        files.append(str(path))
        records += len(frame)

    manifest = {
        "seed": int(seed),
        "synthetic": True,
        "facility": FACILITY,
        "societies": len(SOCIETIES),
        "months": list(MONTHS),
        "year": YEAR,
        "records": records,
        "files": files,
        "injected_event": INJECTED_EVENT,
    }
    manifest_path = output_dir / "synthetic_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic milk collection workbooks.")
    parser.add_argument("--output-dir", default="demo-output/input", help="Directory for generated .xlsx files")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed controlling synthetic values")
    args = parser.parse_args(argv)
    print(json.dumps(generate_synthetic_workbooks(args.output_dir, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()


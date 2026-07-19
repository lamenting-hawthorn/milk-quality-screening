import build_report
import pipeline


def _month():
    return pipeline.normalize_collection_frame(
        __import__("pandas").DataFrame(
            [
                {
                    "S.NO.": 1,
                    "VCH.": "12",
                    "DATE": "01-04-2026",
                    "SHIFT.": "Morning",
                    "DCS": 10,
                    "SOCIETY NAME": "Alpha",
                    "QTY": 100,
                    "Fat %": 5.0,
                    "Snf %": 8.6,
                    "CLR": 28,
                    "Kg, Fat": 5.0,
                    "Kg. Snf": 8.6,
                    "Rate": 40,
                    "Amount": 4000,
                }
            ]
        ),
        "Facility Alpha",
        4,
        2026,
    )


def test_render_report_bundle_uses_bundle_only(tmp_path):
    result = pipeline.analyze_month(_month(), source_name="April.xls")
    output = build_report.render_report_bundle(result["report_bundle"], tmp_path / "report.pdf")

    assert output.exists()
    assert output.stat().st_size > 0
    assert output.read_bytes().startswith(b"%PDF-")

"""Render a milk quality screening PDF from a canonical report bundle."""
import json
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
BRAND = "#1f4e79"
ACCENT = "#c00000"
DISCLAIMER = "Screening only: confirmatory testing is required. This report does not identify adulterants, intent, or fraud."

SCREENING_EXPLANATIONS = {
    "LOW_DENSITY_COMPOSITION_SCREEN": "SNF and CLR crossed their lower screening limits together. Review sampling and instrument conditions, then collect a controlled resample.",
    "HIGH_DENSITY_COMPOSITION_SCREEN": "SNF and CLR crossed their upper screening limits together. The measurements cannot identify a cause; controlled resampling and a suitable laboratory panel are required.",
    "LOW_DENSITY_SCREEN": "CLR crossed its lower screening limit. Verify temperature correction, calibration, sampling, and context.",
    "HIGH_DENSITY_SCREEN": "CLR crossed its upper screening limit. Verify calibration and collect a controlled resample before selecting further tests.",
    "LOW_FAT_SCREEN": "Fat crossed its society-specific lower screening limit. Repeat using a reference method and verify milk class and sampling.",
    "LOW_SOLIDS_SCREEN": "SNF crossed its lower screening limit. Verify whether SNF is independently measured or formula-derived before interpretation.",
    "HIGH_SOLIDS_SCREEN": "SNF crossed its upper screening limit. Verify measurement provenance and collect a controlled resample.",
    "VOLUME_COMPOSITION_SHIFT": "Quantity and composition shifted together beyond screening limits. Verify collection records, route context, and sample integrity.",
    "COMPOSITION_RELATIONSHIP_SCREEN": "The fat/SNF relationship crossed a screening limit. Review instrument calibration, formula use, and measurement provenance.",
    "UNCLASSIFIED_SCREENING_SIGNAL": "A record crossed a screening limit but does not support a more specific neutral screening category.",
}


def _footer(canvas, doc):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm

    canvas.saveState()
    canvas.setFont("Helvetica-Oblique", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(2 * cm, 1 * cm, DISCLAIMER)
    canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("H1", parent=styles["Heading1"], textColor=colors.HexColor(BRAND), spaceAfter=8),
        "h2": ParagraphStyle("H2", parent=styles["Heading2"], textColor=colors.HexColor(BRAND), spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("BODY", parent=styles["BodyText"], alignment=TA_JUSTIFY, leading=12, fontSize=9.5),
        "small": ParagraphStyle("SMALL", parent=styles["BodyText"], fontSize=8, leading=10),
        "tiny": ParagraphStyle("TINY", parent=styles["BodyText"], fontSize=7, leading=9),
        "cover": ParagraphStyle("COVER", parent=styles["Title"], textColor=colors.HexColor(BRAND), fontSize=24, spaceAfter=14),
    }


def _write_diag_chart(bundle, chart_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return None
    counts = bundle["sections"]["diagnosis_distribution"]["counts"] or {"No final flags": 0}
    series = pd.Series(counts)
    fig, ax = plt.subplots(figsize=(7, 0.4 * len(series) + 0.8))
    series[::-1].plot(kind="barh", ax=ax, color=BRAND)
    ax.set_title("Screening category distribution")
    ax.set_xlabel("Records")
    fig.tight_layout()
    path = chart_dir / "screening_dist_bundle.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _write_conf_chart(bundle, chart_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return None
    counts = bundle["sections"]["diagnosis_distribution"]["confidence_counts"] or {"No final flags": 0}
    series = pd.Series(counts)
    fig, ax = plt.subplots(figsize=(5, 2.2))
    cmap = {"RESAMPLE": ACCENT, "REVIEW": "#e89923", "MONITOR": "#5b9bd5"}
    series.plot(kind="bar", ax=ax, color=[cmap.get(item, "#777") for item in series.index])
    ax.set_title("Screening priority distribution")
    ax.set_xlabel("")
    fig.tight_layout()
    path = chart_dir / "priority_dist_bundle.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _explain_diagnosis(name):
    return SCREENING_EXPLANATIONS.get(name, "This is a screening category only; review the measurements and obtain confirmatory evidence before action.")


def _top_offenders_by_keyword(report_df, keyword, limit=5):
    if report_df.empty or "diagnosis" not in report_df.columns:
        return []
    subset = report_df[report_df["diagnosis"].str.contains(keyword, na=False, regex=False)]
    if subset.empty:
        return []
    grouped = (
        subset.groupby(["facility", "dcs", "society_name"])
        .size()
        .rename("count")
        .reset_index()
        .sort_values("count", ascending=False)
        .head(limit)
    )
    return grouped.to_dict("records")


def render_report_bundle(bundle, output_path=None):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError:
        raise RuntimeError(
            "PDF rendering requires the reporting dependencies. Install with: pip install -e '.[reporting]'"
        ) from None

    styles = _styles()
    file_identity = bundle["file_identity"]
    output_path = Path(output_path or ROOT / f"milk_quality_screening_{file_identity['facility']}_{file_identity['file_year']}_{file_identity['file_month']:02d}.pdf")

    chart_temp = tempfile.TemporaryDirectory(prefix="milk-quality-report-")
    chart_dir = Path(chart_temp.name)
    diag_chart = _write_diag_chart(bundle, chart_dir)
    conf_chart = _write_conf_chart(bundle, chart_dir)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.6 * cm,
        title="Milk Quality Screening Report",
    )
    story = []

    summary = bundle["sections"]["executive_summary"]
    audit = bundle["sections"]["audit_trail"]
    facility_overview = bundle["sections"]["facility_overview"]["facility_metrics"]
    detail_rows = bundle["sections"]["detail_logs"]["rows"]
    calibration = bundle["sections"]["calibration"]
    action_rows = bundle["sections"]["action_plan"]["actions"]
    methodology = bundle["sections"]["methodology"]["rules"]
    severity_rows = bundle["severity"]

    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("MILK QUALITY SCREENING", styles["cover"]))
    title = "Milk Quality Calibration Report" if bundle["processing_metrics"]["mode"] != "detection" else "Milk Quality Screening Report"
    story.append(Paragraph(title, styles["h1"]))
    facilities = file_identity.get("facilities") or [file_identity["facility"]]
    facility_label = ", ".join(facilities) if file_identity["facility"] == "ALL" else file_identity["facility"]
    story.append(Paragraph(f"Period analysed: <b>{file_identity['file_year']}-{file_identity['file_month']:02d}</b> · Facilities: <b>{facility_label}</b>", styles["body"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>Intended use:</b> {bundle.get('disclaimer', DISCLAIMER)}", styles["body"]))
    story.append(Spacer(1, 0.8 * cm))

    metrics = bundle["processing_metrics"]
    kpi_data = [
        ["Total records analysed", f"{metrics['records_processed']:,}"],
        ["Unique societies", f"{metrics['societies_active']:,}"],
        ["Facilities", f"{metrics.get('facility_count', len(facilities)):,}"],
        ["Mode", metrics["mode"]],
        ["Initial screening signals", f"{audit['initial_flags']:,}"],
        ["Shared-event filtered", f"{audit['seasonal_suppressed']:,}"],
        ["Final review candidates", f"{audit['final_flags']:,}"],
    ]
    table = Table(kpi_data, colWidths=[8 * cm, 5 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f9")),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("<i>Methodology: per-society seasonal baselines · 7 screening rules · neutral screening categories · shared-event filter</i>", styles["small"]))
    story.append(PageBreak())

    story.append(Paragraph("Table of Contents", styles["h1"]))
    toc = [
        "1. Executive Summary",
        "2. Audit Trail - Flag Pipeline Transparency",
        "3. Facility Overview",
        "4. Screening Category Distribution",
        "5. Screening Signals by Society",
        "6. Priority Screening Details",
        "7. Facility Screening Summary",
        "8. Recommended Follow-up by Screening Category",
        "9. Methodology Summary",
        "10. Recommendations",
    ]
    if bundle["processing_metrics"]["mode"] != "detection":
        toc.insert(6, "Calibration Watchlist")
    for item in toc:
        story.append(Paragraph(item, styles["body"]))
    story.append(PageBreak())

    story.append(Paragraph("1. Executive Summary", styles["h1"]))
    story.append(Paragraph(summary["summary"], styles["body"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Important:</b> {bundle.get('disclaimer', DISCLAIMER)}", styles["body"]))
    top_rows = summary["top_findings"]
    if top_rows:
        rows = [["Facility", "DCS", "Society", "Frequency / Score", "Primary category"]]
        for row in top_rows:
            rows.append([
                row.get("facility", ""),
                int(row.get("dcs", 0)) if row.get("dcs") is not None else "",
                row.get("society_name", "")[:30],
                row.get("severity", row.get("deviation_score", "")),
                row.get("primary_diagnosis", ""),
            ])
        table = Table(rows, colWidths=[2 * cm, 1.4 * cm, 5.0 * cm, 2.6 * cm, 5.0 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(Spacer(1, 6))
        story.append(table)
    story.append(PageBreak())

    story.append(Paragraph("2. Audit Trail - Flag Pipeline Transparency", styles["h1"]))
    audit_rows = [
        ["Initial screening signals", f"{audit['initial_flags']:,}"],
        ["Shared-event filtered", f"{audit['seasonal_suppressed']:,}"],
        ["Final review candidates", f"{audit['final_flags']:,}"],
        ["Mode", bundle["processing_metrics"]["mode"]],
    ]
    audit_table = Table(audit_rows, colWidths=[8 * cm, 4 * cm])
    audit_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
    story.append(audit_table)
    if bundle["processing_metrics"]["mode"] != "detection":
        story.append(Spacer(1, 8))
        story.append(Paragraph("This month is calibration-only because there is not enough prior monthly history for record-level screening.", styles["body"]))
    story.append(PageBreak())

    story.append(Paragraph("3. Facility Overview", styles["h1"]))
    rows = [["Facility", "Records", "Societies", "Avg Fat", "Avg SNF", "Avg CLR"]]
    for row in facility_overview:
        rows.append([row["facility"], int(row["records"]), int(row["societies"]), f"{row['avg_fat']:.2f}", f"{row['avg_snf']:.2f}", f"{row['avg_clr']:.2f}"])
    table = Table(rows, colWidths=[3 * cm, 2 * cm, 2 * cm, 2 * cm, 2 * cm, 2 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(table)
    story.append(PageBreak())

    story.append(Paragraph("4. Screening Category Distribution", styles["h1"]))
    if diag_chart is not None:
        story.append(Image(str(diag_chart), width=15.5 * cm, height=0.45 * cm * max(1, len(bundle["sections"]["diagnosis_distribution"]["counts"])) + 1 * cm))
        story.append(Spacer(1, 4))
    else:
        rows = [["Screening category", "Count"]]
        for key, value in (bundle["sections"]["diagnosis_distribution"]["counts"] or {"No final flags": 0}).items():
            rows.append([key, value])
        table = Table(rows, colWidths=[10 * cm, 4 * cm])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        story.append(table)
        story.append(Spacer(1, 4))
    if conf_chart is not None:
        story.append(Image(str(conf_chart), width=10 * cm, height=4.5 * cm))
    else:
        rows = [["Screening priority", "Count"]]
        for key, value in (bundle["sections"]["diagnosis_distribution"]["confidence_counts"] or {"No final flags": 0}).items():
            rows.append([key, value])
        table = Table(rows, colWidths=[7 * cm, 3 * cm])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        story.append(table)
    story.append(Spacer(1, 6))
    top_diag_counts = bundle["sections"]["diagnosis_distribution"]["counts"] or {}
    for name, count in list(top_diag_counts.items())[:5]:
        story.append(Paragraph(f"<b>{name}</b> - {count} records: {_explain_diagnosis(name)}", styles["body"]))
        story.append(Spacer(1, 3))
    story.append(PageBreak())

    story.append(Paragraph("5. Screening Signals by Society", styles["h1"]))
    report_df = pd.DataFrame(bundle.get("report_records", []))
    offender_sections = [
        ("Low-density and low-solids screens", _top_offenders_by_keyword(report_df, "LOW_")),
        ("High-density and high-solids screens", _top_offenders_by_keyword(report_df, "HIGH_")),
        ("Volume-composition shifts", _top_offenders_by_keyword(report_df, "VOLUME_")),
        ("Composition-relationship screens", _top_offenders_by_keyword(report_df, "RELATIONSHIP_")),
    ]
    for title_text, rows_data in offender_sections:
        story.append(Paragraph(title_text, styles["h2"]))
        if rows_data:
            rows = [["Facility", "DCS", "Society", "Flags"]]
            for row in rows_data:
                rows.append([row["facility"], int(row["dcs"]), row["society_name"][:40], int(row["count"])])
            table = Table(rows, colWidths=[2.4 * cm, 1.5 * cm, 8.0 * cm, 2.0 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(table)
        else:
            story.append(Paragraph("No records in this category for the current report.", styles["small"]))
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    story.append(Paragraph("6. Priority Screening Details", styles["h1"]))
    if detail_rows:
        story.append(Paragraph("Low-priority unclassified signals near the screening boundary are excluded from these detail logs but remain in the stored audit data.", styles["small"]))
        detail_df = pd.DataFrame(detail_rows)
        severity_map = { (row["facility"], row["dcs"]): row for row in severity_rows }
        detail_df["severity"] = detail_df.apply(lambda r: severity_map.get((r["facility"], r["dcs"]), {}).get("severity", "ISOLATED"), axis=1)
        focus = detail_df[detail_df["severity"].isin(["VERY_FREQUENT", "FREQUENT"])].copy()
        if focus.empty:
            focus = detail_df.copy()
        seen = 0
        for (facility, dcs, society_name), group in focus.groupby(["facility", "dcs", "society_name"]):
            meta = severity_map.get((facility, dcs), {})
            severity = meta.get("severity", "ISOLATED")
            primary = meta.get("primary_diagnosis", group["diagnosis"].mode().iloc[0] if len(group) else "")
            baseline = group.iloc[0]
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"[{severity}] DCS {int(dcs)} - {society_name} ({facility})", styles["small"]))
            story.append(Paragraph(
                f"Total flags: {len(group)} | Primary: {primary} | Baselines: SNF {baseline['b_snf']:.1f}%, Fat {baseline['b_fat']:.1f}%, CLR {baseline['b_clr']:.1f}",
                styles["tiny"],
            ))
            # A4 usable width = 21cm - 2cm*2 margins = 17cm
            # Cols: Date(1.8) Sh(0.6) SNF(0.8) Fat(0.8) CLR(0.7) QTY(0.8) Conf(1.3) Reason(10.2) = 17.0cm
            tiny_p = styles["tiny"]
            col_widths = [1.8*cm, 0.6*cm, 0.8*cm, 0.8*cm, 0.7*cm, 0.8*cm, 1.3*cm, 10.2*cm]
            rows = [["Date", "Sh", "SNF%", "Fat%", "CLR", "QTY", "Priority", "Category & Reason"]]
            show = group.sort_values(["date", "shift"]).head(10)
            for _, row in show.iterrows():
                diag_line = f"<b>{row['diagnosis']}</b> — {row['explanation'][:150]}"
                rows.append([
                    row["date"], row["shift"],
                    f"{row['snf_pct']:.1f}", f"{row['fat_pct']:.1f}",
                    f"{row['clr']:.0f}", f"{row['qty']:.0f}",
                    row["confidence"][:4],
                    Paragraph(diag_line, tiny_p),
                ])
            if len(group) > 10:
                rows.append(["...", "...", "...", "...", "...", "...", "...",
                              Paragraph(f"+ {len(group)-10} more flagged records", tiny_p)])
            table = Table(rows, colWidths=col_widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.2, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 7.0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(table)
            seen += 1
            if seen >= 8:
                break
    else:
        story.append(Paragraph("No reportable screening candidates are present in this month. Review the calibration watchlist instead.", styles["body"]))
    story.append(PageBreak())

    if bundle["processing_metrics"]["mode"] != "detection":
        story.append(Paragraph("7. Calibration Watchlist", styles["h1"]))
        watchlist = calibration["watchlist"]
        if watchlist:
            rows = [["Facility", "DCS", "Society", "Records", "Deviation Score"]]
            for row in watchlist:
                rows.append([row["facility"], int(row["dcs"]), row["society_name"][:36], int(row["record_count"]), row["deviation_score"]])
            table = Table(rows, colWidths=[2.0 * cm, 1.4 * cm, 6.8 * cm, 1.8 * cm, 2.6 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(table)
        story.append(PageBreak())

    story.append(Paragraph("7. Facility Screening Summary" if bundle["processing_metrics"]["mode"] == "detection" else "8. Facility Screening Summary", styles["h1"]))
    if not report_df.empty:
        for facility, group in report_df.groupby("facility"):
            story.append(Paragraph(facility, styles["h2"]))
            top5 = group["diagnosis"].value_counts().head(5)
            rows = [["Screening category", "Count", "% of facility signals"]]
            total = max(len(group), 1)
            for name, count in top5.items():
                rows.append([name[:55], int(count), f"{count/total*100:.1f}%"])
            table = Table(rows, colWidths=[10.0 * cm, 2.0 * cm, 3.0 * cm])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(table)
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("No record-level screening candidates are available yet; facility-level category counts will populate after calibration history builds up.", styles["body"]))
    story.append(PageBreak())

    story.append(Paragraph("8. Recommended Follow-up by Screening Category" if bundle["processing_metrics"]["mode"] == "detection" else "9. Recommended Follow-up by Screening Category", styles["h1"]))
    for row in action_rows:
        story.append(Paragraph(f"<b>{row['diagnosis']}.</b> {row['action']}", styles["body"]))
        story.append(Spacer(1, 2))
    story.append(PageBreak())

    story.append(Paragraph("9. Methodology Summary" if bundle["processing_metrics"]["mode"] == "detection" else "10. Methodology Summary", styles["h1"]))
    method_rows = [["Rule", "Trigger"]]
    for row in methodology:
        method_rows.append([row["id"], row["trigger"]])
    table = Table(method_rows, colWidths=[1.5 * cm, 13.0 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(table)
    story.append(PageBreak())

    story.append(Paragraph("10. Recommendations" if bundle["processing_metrics"]["mode"] == "detection" else "11. Recommendations", styles["h1"]))
    if bundle["processing_metrics"]["mode"] == "detection":
        story.append(Paragraph("Immediate: review RESAMPLE-priority records, verify chain of custody and instrument status, and collect controlled samples before choosing confirmatory tests.", styles["body"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("Short-term: investigate recurring category clusters for data-quality, route, feed, season, instrument, and sampling explanations.", styles["body"]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("Ongoing: continue monthly processing and validate screening precision against blinded confirmatory outcomes before operational escalation.", styles["body"]))
    else:
        story.append(Paragraph("This month should be treated as calibration. Use the watchlist for sampling priorities, then continue processing subsequent months so society-specific baselines can mature.", styles["body"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    chart_temp.cleanup()
    return output_path


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Render a milk quality screening PDF from an analysis bundle.")
    parser.add_argument("bundle_json", help="Path to a report bundle JSON file")
    parser.add_argument("--output", help="Output PDF path")
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.bundle_json).read_text())
    path = render_report_bundle(bundle, args.output)
    print(path)


if __name__ == "__main__":
    main()

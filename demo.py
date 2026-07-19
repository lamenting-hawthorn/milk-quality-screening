"""Run the complete synthetic milk quality screening demonstration."""

import argparse
import json
import os
from pathlib import Path

import build_report
import pipeline
from synthetic_data import DEFAULT_SEED, generate_synthetic_workbooks


def run_demo(output_dir="demo-output", seed=DEFAULT_SEED, render_pdf=True):
    output_dir = Path(output_dir)
    input_dir = output_dir / "input"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = generate_synthetic_workbooks(input_dir, seed=seed)
    database_path = output_dir / "screening.db"
    result = pipeline.run_pipeline(input_dir, database_path)
    latest_bundle = result["report_bundle"]
    bundle_path = output_dir / "latest_analysis_bundle.json"
    bundle_path.write_text(json.dumps(latest_bundle, indent=2) + "\n", encoding="utf-8")

    report_path = None
    if render_pdf:
        matplotlib_cache = output_dir / ".cache" / "matplotlib"
        matplotlib_cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache))
        report_path = output_dir / "milk_quality_screening_demo.pdf"
        build_report.render_report_bundle(latest_bundle, report_path)

    summary = {
        "synthetic": True,
        "seed": int(seed),
        "periods_processed": len(result["runs"]),
        "records_processed": result["records_processed"],
        "latest_mode": result["mode"],
        "latest_screening_records": len(result["runs"][-1]["report"]),
        "input_manifest": manifest["manifest_path"],
        "database": str(database_path),
        "analysis_bundle": str(bundle_path),
        "report": str(report_path) if report_path else None,
    }
    summary_path = output_dir / "demo_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the end-to-end synthetic milk quality screening demo.")
    parser.add_argument("--output-dir", default="demo-output", help="Directory for generated demo artifacts")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed controlling synthetic values")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF rendering")
    args = parser.parse_args(argv)
    print(json.dumps(run_demo(args.output_dir, seed=args.seed, render_pdf=not args.no_pdf), indent=2))


if __name__ == "__main__":
    main()

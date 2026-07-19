# Milk Quality Screening

An open-source, evidence-aware screening engine for dairy collection data. It
turns routine milk composition reports into reproducible statistical signals,
review queues, and auditable quality-control reports.

> [!IMPORTANT]
> This project identifies **statistical screening patterns** that can prioritize
> human review and confirmatory testing. It does not identify specific
> adulterants, establish intent, or prove fraud from routine collection data.

## Project status

The project is an alpha-quality screening engine with a tested analysis core,
PDF reporting, local SQLite output, and an optional Supabase persistence path.
Repository tests and examples use synthetic identities; no customer or
production data is included.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[reporting]"
milk-quality-demo
```

The command creates deterministic synthetic Excel workbooks, analyzes four
months in chronological order, detects one controlled screening event, and
writes all outputs to `demo-output/`.

```json
{
  "synthetic": true,
  "periods_processed": 4,
  "records_processed": 1200,
  "latest_mode": "detection",
  "latest_screening_records": 1
}
```

Read the [demo walkthrough](docs/demo.md) for the generated scenario, output
files, reproducibility contract, and safety boundaries.

For contributor tooling and the full test suite:

```bash
pip install -e ".[reporting,dev]"
pytest
ruff check .
```

## Using your own reports

Run the local screening CLI against a directory of `.xls` or `.xlsx` collection reports:

```bash
milk-quality-screen --source-dir data/input --db data/screening.db
```

Validate one workbook before processing it. The command emits a versioned
schema fingerprint, accepted/rejected counts, and row-level rejection reasons;
screening stops rather than silently dropping invalid data rows.

```bash
milk-quality-validate "data/input/Facility milk collection for the month of April 2026.xlsx" \
  --output validation-report.json
```

Each reportable signal opens a durable local review case. Track the human
workflow and link the controlled resample or laboratory disposition:

```bash
milk-quality-cases --db data/screening.db list --status OPEN
milk-quality-cases --db data/screening.db update CASE_ID \
  --status LAB_PENDING --confirmation-reference "COC-2026-0042"
```

Re-running an already completed period leaves it unchanged. New periods use
persisted prior monthly statistics for their baseline; SQLite remains a local
single-user workflow, not a multi-center hosted deployment.

Render a previously generated canonical analysis bundle:

```bash
milk-quality-report analysis_bundle.json --output report.pdf
```

The accepted workbook layouts and analytical boundaries are documented in
[Methodology](docs/methodology.md).

## Capabilities

- Parses two common Excel milk-collection report layouts into a canonical schema.
- Establishes facility- and producer-level seasonal baselines.
- Generates explainable composition and volume screening signals.
- Preserves methodology version, input provenance, and analysis audit trails.
- Produces PDF reports and machine-readable analysis bundles.
- Supports local SQLite execution and optional Supabase persistence.
- Rejects unsupported or malformed workbooks with a schema fingerprint and
  row-level diagnostics instead of silent record loss.
- Preserves local historical baselines across incremental runs and creates
  idempotent reporting-period records.
- Surfaces recurring screening patterns and durable review cases for resample
  and confirmatory-test follow-up.

## Why this project exists

Milk collection operations often have composition data but lack a reproducible
way to decide which records deserve additional review. This project bridges
that gap while keeping the analytical boundary explicit: statistical signals
are triage evidence, not laboratory confirmation.

## Safety and privacy

- Never upload customer workbooks, databases, reports, or identifiers.
- Use synthetic or explicitly licensed data in issues and pull requests.
- Do not use screening output as the sole basis for adverse action.
- Confirm material findings with an appropriate validated reference method.

See [SECURITY.md](SECURITY.md) for private vulnerability reporting and
[CONTRIBUTING.md](CONTRIBUTING.md) for contribution requirements.

## Documentation

- [Architecture](docs/architecture.md) — components, data flow, boundaries, and deployment model
- [Demo walkthrough](docs/demo.md) — deterministic synthetic scenario and generated artifacts
- [Methodology](docs/methodology.md) — rules, baseline policy, intended use, and limitations
- [Field-pilot guide](docs/field-pilot.md) — prospective validation and evidence requirements
- [Hosted deployment boundary](docs/hosted-deployment.md) — multi-tenant security prerequisites
- [Contributing](CONTRIBUTING.md) — contributor workflow and privacy requirements
- [Security](SECURITY.md) — vulnerability reporting and deployment responsibilities

## Roadmap

1. Add versioned public schemas and configurable input adapters.
2. Add prospective validation tooling and reference-test labels.
3. Build a seeded dashboard and multi-tenant API behind the stable core.
4. Publish a field-pilot guide, demo video, and tagged release after external validation.

## License

Released under the [MIT License](LICENSE).

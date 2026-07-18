# Milk Quality Screening

An open-source, evidence-aware screening engine for dairy collection data. It
turns routine milk composition reports into reproducible statistical signals,
review queues, and auditable quality-control reports.

> [!IMPORTANT]
> This project prioritizes records for human review and confirmatory testing.
> It does not identify adulterants, establish intent, or prove fraud.

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
pip install -e ".[reporting,dev]"
pytest
```

Run the local screening CLI against a directory of `.xls` collection reports:

```bash
milk-quality-screen --source-dir data/input --db data/screening.db
```

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
- [Methodology](docs/methodology.md) — rules, baseline policy, intended use, and limitations
- [Contributing](CONTRIBUTING.md) — contributor workflow and privacy requirements
- [Security](SECURITY.md) — vulnerability reporting and deployment responsibilities

## Roadmap

1. Add deterministic, file-based synthetic demo fixtures.
2. Introduce schema contracts and structured parser diagnostics.
3. Replace compatibility field names with a versioned public schema.
4. Add prospective validation tooling and reference-test labels.
5. Build a seeded dashboard and multi-tenant API behind the stable core.

## License

Released under the [MIT License](LICENSE).

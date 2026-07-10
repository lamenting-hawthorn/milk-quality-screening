# Milk Quality Screening

An open-source, evidence-aware screening engine for dairy collection data. It
turns routine milk composition reports into reproducible statistical signals,
review queues, and auditable quality-control reports.

> [!IMPORTANT]
> This project prioritizes records for human review and confirmatory testing.
> It does not identify adulterants, establish intent, or prove fraud.

## Project status

The repository is being rebuilt from a working prototype into a generic,
privacy-safe open-source package. The first public release will use synthetic
fixtures exclusively; no customer or production data is included.

## Planned capabilities

- Parse common Excel milk-collection report layouts into a canonical schema.
- Establish facility- and producer-level seasonal baselines.
- Generate explainable composition and volume screening signals.
- Preserve methodology version, input provenance, and analysis audit trails.
- Produce human-readable reports and machine-readable analysis bundles.
- Support local execution with optional hosted persistence adapters.

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

## Roadmap

1. Extract and rebrand the reusable analysis engine.
2. Add deterministic synthetic fixtures and regression tests.
3. Package the CLI and report renderer.
4. Publish architecture and scientific validation documentation.
5. Add continuous integration, security checks, and a seeded demo.

## License

Released under the [MIT License](LICENSE).


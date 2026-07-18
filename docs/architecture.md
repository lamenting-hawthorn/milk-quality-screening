# Architecture

## Goals

Milk Quality Screening converts monthly dairy collection workbooks into
reproducible screening evidence. The design prioritizes traceability, neutral
language, privacy, and the ability to replace storage or presentation layers
without rewriting analytical rules.

The current alpha is intentionally a compact Python application. Its canonical
analysis bundle is the boundary between computation, reporting, and storage.

## System flow

```mermaid
flowchart LR
    A["Excel collection reports"] --> B["Parser and normalizer"]
    B --> C["Canonical collection records"]
    C --> D["Monthly statistics"]
    H["Historical monthly statistics"] --> E["Seasonal baseline builder"]
    D --> E
    C --> F["Screening rules"]
    E --> F
    F --> G["Analysis bundle"]
    G --> I["PDF report"]
    G --> J["SQLite output"]
    G --> K["Optional Supabase adapter"]
```

## Components

### Analysis engine

`pipeline.py` owns parsing, normalization, monthly aggregation, historical
baseline construction, screening rules, confidence adjustments, seasonal event
routing, summaries, and canonical bundle generation.

Its main programmatic entry point is `analyze_month(month_df,
historical_month_stats)`. Inputs and intermediate values are pandas data frames;
the returned bundle is JSON-serializable.

### Report renderer

`build_report.py` consumes only the canonical bundle. It does not read raw
workbooks or recompute screening decisions. This separation prevents report
formatting changes from silently changing analytical outcomes.

### Local persistence

`run_pipeline` writes derived tables to SQLite. The database is an output and is
excluded from version control. Raw workbooks are never part of the repository.

### Hosted persistence adapter

`supabase_pipeline.py` persists compact monthly statistics, baselines,
screening records, summaries, audit rows, and the canonical bundle through the
Supabase REST API. Credentials come from environment variables and must remain
server-side.

The hosted adapter is optional. The analysis engine and report renderer do not
require Supabase.

## Canonical data flow

1. `parse_filename` extracts facility and reporting period from a workbook name.
2. `normalize_collection_frame` maps supported input columns to canonical fields.
3. `compute_society_month_stats` creates compact historical summaries.
4. `build_baselines_from_month_stats` uses only periods before the target month.
5. `apply_rules` produces neutral screening signals.
6. Confidence and shared-event logic adjust review priority.
7. `build_analysis_bundle` records methodology, provenance, results, and actions.
8. Output adapters consume the bundle without changing the result.

## Key invariants

- No future period may contribute to a target period's baseline.
- Screening categories never identify a substance, intent, or fraud.
- Insufficient history produces calibration mode rather than invented certainty.
- The deprecated repeated-spike rule remains disabled and always emits zero.
- Raw workbooks, databases, generated reports, and credentials remain untracked.
- Report generation consumes derived data only.

## Trust boundaries

| Boundary | Required control |
|---|---|
| Workbook to parser | Validate required columns and numeric coercion; reject unusable schemas |
| Engine to report | Consume the versioned bundle; do not recompute decisions |
| Engine to persistence | Persist only expected derived fields and sanitize missing values |
| Server to Supabase | Keep privileged keys server-side and apply least privilege |
| Repository to contributors | Synthetic or explicitly redistributable fixtures only |

## Current limitations

- Source modules remain flat while the public API stabilizes.
- Input schema detection supports two known layouts and lacks a formal schema registry.
- SQLite writes currently replace derived tables in a single local run.
- Supabase requests are synchronous and use a privileged server-side credential.
- There is no user authentication, tenant isolation, job queue, or hosted API yet.
- The compatibility schema still contains legacy field names such as `diagnosis`
  and `confidence`; their values now contain neutral screening categories and
  priorities and are explicitly marked deprecated in the bundle.

## Evolution path

The next architectural boundary is an installable `src/` package with explicit
domain, ingestion, application, and adapter modules. Hosted deployment should
then add an authenticated API, queue-backed workers, private object storage,
PostgreSQL row-level isolation, idempotency keys, and immutable run provenance.
Those additions should preserve the canonical bundle contract and keep the
screening engine independent from infrastructure providers.


# Synthetic Demo

The demo is the fastest way to inspect the complete public workflow without
using customer or production data.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[reporting]"
milk-quality-demo
```

Use a different output directory or seed when needed:

```bash
milk-quality-demo --output-dir /tmp/milk-quality-demo --seed 20260719
```

Use `--no-pdf` when only the database and JSON artifacts are required.

## Scenario

The default seed generates:

- One synthetic facility: `FacilityAlpha`
- Five synthetic societies
- January through April 2026
- Morning and evening collection shifts
- 1,200 total collection records
- Bounded background variation in quantity, fat, SNF, and CLR
- One controlled low-solids and low-density event on 30 April for society 101

January through March establish historical monthly statistics. April is then
screened using only those earlier periods. Bounded background variation keeps
the demonstration focused on the single documented event.

## Outputs

The default command writes:

| Path | Purpose |
|---|---|
| `demo-output/input/*.xlsx` | Four generated collection workbooks |
| `demo-output/input/synthetic_manifest.json` | Seed, scenario, and injected-event declaration |
| `demo-output/screening.db` | Derived SQLite screening tables |
| `demo-output/latest_analysis_bundle.json` | Versioned machine-readable result for April |
| `demo-output/milk_quality_screening_demo.pdf` | Human-readable screening report |
| `demo-output/demo_summary.json` | Compact run summary and artifact paths |

All files under `demo-output/` are generated and ignored by Git.

## Expected result

The default run processes four periods and 1,200 records. The latest period is
in `detection` mode and contains exactly one final review candidate classified
as `LOW_DENSITY_COMPOSITION_SCREEN`.

That label remains a neutral screening category. It does not identify a cause,
substance, intent, or regulatory violation.

## Reproducibility

The numeric workbook content is deterministic for a given seed. Tests generate
the scenario twice and compare the loaded data frames cell by cell. Excel ZIP
container metadata may differ between generated files, so binary file hashes
are not the reproducibility contract.

The end-to-end regression test also verifies that:

- All generated workbooks pass through the public Excel parser.
- Historical periods are processed chronologically.
- The declared event appears exactly once in final report records.
- Four report bundles are persisted to SQLite.

## Privacy boundary

Synthetic names, identifiers, dates, vehicles, and measurements are generated
entirely by this repository. Do not replace them with real operational data in
issues, pull requests, screenshots, or committed fixtures.

# Screening Methodology

## Intended use

This software prioritizes milk collection records for review, controlled
resampling, and suitable confirmatory testing. It is decision support for a
quality-control workflow.

It does not identify an adulterant, prove contamination, establish intent,
determine regulatory compliance, or prove fraud. A statistical threshold
crossing is not laboratory confirmation.

## Input measurements

The current engine accepts collection-level fields including quantity, fat,
solids-not-fat (SNF), corrected lactometer reading (CLR), collection date,
shift, facility, and producer or society identifier.

Interpretation depends on measurement provenance. In particular, SNF may be
formula-derived from fat and CLR rather than independently measured. Derived
variables must not be described as independent corroborating evidence.

## Baseline policy

Screening compares each record with prior observations for the same facility
and producer or society.

- Only months before the target month are eligible for its baseline.
- At least three prior months are required overall.
- A seasonal baseline requires at least two prior months in the same season.
- A seasonal group needs at least 15 records; otherwise the engine may use an
  all-year baseline with at least 30 records and reduce priority.
- Thin baselines require more extreme deviations before a signal is retained.
- Summer is currently configured as April through September; this is a
  configurable modeling assumption, not a universal biological boundary.

The engine uses pooled monthly means and variances for historical baselines.
This is a pragmatic alpha implementation and should be validated for each new
population, instrument, milk class, and operating environment.

## Screening signals

The active implementation uses standardized deviations from the selected
baseline plus absolute guardrails.

| Rule | Current trigger | Neutral interpretation |
|---|---|---|
| R1 | SNF z-score below -2 and SNF below 8.0 | Low-solids screen |
| R2 | SNF z-score above 2 and SNF above 9.2 | High-solids screen |
| R3 | Fat z-score below -2.5 and fat more than 2 points below baseline | Low-fat screen |
| R4 | SNF z-score above 1.5, fat z-score below -0.5, and SNF above 9.0 | Composition-relationship screen |
| R5 | CLR z-score above 2 and CLR at least 29 | High-density screen |
| R6 | Quantity z-score above 2 with fat or SNF z-score below -1.5 | Volume-composition shift |
| R7 | CLR z-score below -2 and CLR below 25 | Low-density screen |

These thresholds are screening heuristics, not universal acceptance limits.
They require prospective validation before operational reliance.

## Recurring screening patterns

When the same society and screening category recur at least twice in a
processed reporting period, the engine emits a `RECURRING_SCREENING_PATTERN`
indicator. It is a starting point for operational follow-up: review source
integrity, verify the collection process, and collect a controlled resample.
It does not identify a substance, establish intent, or confirm an adverse
finding.

## Disabled repeated-spike rule

R8 is intentionally disabled. A fixed count of measurements above a percentile
does not account for exposure: producers with more collections have more
opportunities to exceed the threshold even when their process is stable. The
compatibility column remains present but is always zero.

Any future recurrence signal should model the number of opportunities and
control false-positive risk explicitly.

## Shared events

When more than 30% of active societies at a facility and shift show aligned
screening movement, the engine labels the pattern as a shared or seasonal event
and excludes those records from the individual review report.

This routing is intended to prevent a facility-wide or environmental pattern
from being misrepresented as an individual event. It is not permission to
discard the event: shared patterns should enter a separate facility,
instrument, feed, weather, transport, or process investigation.

## Priority adjustments

- Records below 10 units of quantity receive reduced screening priority.
- All-year fallback caused by thin seasonal history caps the highest priority.
- Outputs use `RESAMPLE`, `REVIEW`, and `MONITOR` as workflow priorities.

Priority is not probability, confidence in causality, or severity of harm.

## Required operational workflow

1. Review source integrity, units, date, shift, instrument, and milk-class metadata.
2. Check whether the pattern is individual or shared across a facility and shift.
3. Collect a controlled resample using documented chain of custody.
4. Repeat relevant measurements using appropriate calibrated or reference methods.
5. Choose confirmatory laboratory tests based on the observed evidence and context.
6. Record the disposition and reference result for later validation.
7. Never use the screening output alone for an adverse action.

## Validation requirements

Before production use, evaluate the system prospectively against independent
reference outcomes. Validation should be stratified by facility, instrument,
operator, season, milk class, and relevant demographic or operational groups.

At minimum, report:

- Sensitivity and specificity with uncertainty intervals
- Positive and negative predictive value at the deployment prevalence
- False-positive rate per record and per producer-period
- Calibration or priority yield for each screening category
- Missing-data and parser-rejection rates
- Drift in input distributions and signal rates
- Time from signal to controlled resample and confirmatory disposition

Do not publish a single overall "accuracy" number when subgroup performance,
class imbalance, or reference-test coverage is unknown.

## Known limitations

- Thresholds have not been established as regulatory or diagnostic limits.
- Correlated and formula-derived measurements can create redundant signals.
- Mean and standard-deviation baselines are sensitive to skew and outliers.
- Season definitions are coarse and may not match local biological conditions.
- Instrument calibration, temperature correction, feed, breed, disease, and
  sampling procedure may explain composition changes.
- The current engine does not ingest confirmatory outcomes or estimate causal
  probabilities.

## Change control

The analysis bundle records a methodology version. Any change to thresholds,
baseline eligibility, seasonal routing, category mapping, or priority adjustment
must update tests and documentation and should advance that version. Historical
runs should remain reproducible under the version that produced them.

# Data provenance and extraction

Only official unrestricted demo releases are fetched. Full restricted MIMIC/eICU
credentials are neither needed nor bypassed.

- MIMIC-IV demo v2.2: https://physionet.org/content/mimic-iv-demo/2.2/
  Johnson et al. DOI: 10.13026/dp1f-ex47.
- eICU demo v2.0.1: https://physionet.org/content/eicu-crd-demo/2.0.1/
  Johnson et al. DOI: 10.13026/4mxk-na84.
- Definition reference: KDIGO 2012 AKI guideline:
  https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf

The datasets are licensed under Open Data Commons Open Database License 1.0.
Preserve attribution and applicable database licensing obligations.
Each source LICENSE.txt is retained alongside its tables.
data/download_manifest.json records URLs, bytes and publisher SHA-256 hashes.
Raw source tables are kept in data/raw/; only selected relevant tables are fetched.

## Local database

SQLite tables:
- stays: source-prefixed stay/patient/hospital IDs, ICU duration, patient context.
- observations: measurement hour, availability hour, variable, value, optional interval.
- audit: per-source parsing, exclusions and accepted measurement counts.

Indexed, parameterized queries are used. Foreign keys cascade source rebuilds.
Re-extraction replaces a source transactionally. Patient uploads are not persisted.
No credentials are embedded. Offline inference reads the saved model and SQLite.

## Harmonization

MIMIC ICU admission is the time origin. Absolute timestamps become relative hours.
MIMIC labs: charttime is measurement time; storetime is availability when present.
Lab item IDs and units are allow-listed. Blood creatinine is 50912, BUN 51006.
The shared core does not confuse urine creatinine with blood creatinine.
Source ID maps and drug patterns are in aki/extract.py.

eICU offsets are minutes relative to ICU admission and are divided by 60.
Revised lab offsets and urine entry offsets are respected when supplied.
Selected lab names are checked against the database's standardized labmeasurenamesystem
units before import; local interface unit spellings are not used as the unit contract.
Periodic/aperiodic vitals are aggregated to completed-hour means. A bin is only
available at its end; later-in-hour values cannot enter earlier predictions.
If both source vital tables supply MAP at the same hourly timestamp,
non-invasive MAP is retained by deterministic import order.

Implausible/non-numeric values are rejected, counted and never clipped into
apparently healthy values. API bounds are accessible through /v1/input-schema.

Urine extraction uses urine-specific item IDs/paths, never overall output totals.
Simultaneous urine entries are grouped; collection intervals are left unknown.
Documented volumes are model features, not complete weight-normalized urine rates.
Current urine KDIGO checks require explicit complete intervals supplied by a caller.
Positive-volume rates additionally require weight; exact timed zero does not.
Collection completeness is separate from whether a normalized rate is available.
MIMIC input-event volume is available at infusion completion, not assigned in full
to infusion start. Source medication orders are context, not proof of administration.

Historical ESRD/chronic-dialysis evidence is used only where available before the
prediction context. Unknown history remains unknown. Discharge diagnoses,
APACHE summaries, mortality and discharge status are not input features.

## Future full-data support

These adapters target pinned demo schemas. Full datasets need approved access,
local source-path configuration, chunked scaling review and new cohort audits.
Do not interpret a successful demo import as a completed full-dataset study.


## Observed release inventory

The downloaded eICU patient table contains 2,520 stays, 1,841 unique patient IDs
and 186 anonymous hospital IDs; 2,500 stays meet the adult age filter.
The project landing page describes a smaller hospital selection. Hospital grouping
here uses IDs verified directly against the downloaded hospital table, not an
assumed hospital count from descriptive text. Only hospitals with sufficient
labelled data are evaluated; other holdouts are reported as insufficient.


## Forecast timing audit (0.2)

The prediction endpoint uses qualifying creatinine **sample time**, with the
result's entry/revision time retained separately. A sample already collected
before scoring is not a future event, even when its result arrives later.
Only available values enter features. Negative labels need late-horizon collection,
not late entry of an old sample. RRT before a future endpoint causes censoring.

This distinguishes collection from availability using the
[official eICU lab column definitions](https://eicu.mit.edu/eicutables/lab/).
Source timestamps approximate collection and knowledge; they do not establish
biological injury onset or exact clinician awareness.


CSV upload weights remain timestamped observations. A later weight cannot become
a baseline for an earlier replay. Partial-source downloads retain the other
source entries in the download manifest; artifact writes are atomic.

Still-qualifying lab revisions preserve earliest as-of criterion recognition.
Latest corrected result availability remains separate from that first recognition.
See [clinical test cases](CLINICAL_TEST_CASES.md) for counterexamples and limits.

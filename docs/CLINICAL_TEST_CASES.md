# Clinical logic cases and review limits

These are automated research-rule and engineering checks, not a nephrologist's
review or clinical validation. The endpoint is first new creatinine-defined AKI
within the next 24 hours. Existing AKI is recognized separately.

## Cases a reviewer can inspect

| Scenario | Expected behavior | Why it matters |
|---|---|---|
| Creatinine 0.6 -> 0.9 mg/dL in 12h | Existing stage-1 AKI; no new-AKI score | A normal-looking absolute value can still represent an acute rise |
| Stable high creatinine, or no valid prior sample | Do not invent acute injury or a healthy baseline | CKD and missing baseline differ from demonstrated acute change |
| >=0.3 mg/dL rise in 48h; >=1.5x in 7 days | Include exact thresholds; reject comparisons outside their windows | Boundary arithmetic and timing change labels |
| Sample drawn at hour 6, result available at 14 | Hidden at hour 12; recognized at 14 | The model cannot know an unreported result |
| AKI recognized at 6, still-abnormal correction at 8 | First recognition stays 6; corrected value availability is 8 | Corrections must not exaggerate warning lead |
| Abnormal result corrected to non-qualifying | Current assessment follows corrected evidence | Retractions are not persistent true injury labels |
| Future recovery, later weight or later dialysis history | Cannot change an earlier replay | Prevents hindsight from entering real-time inputs |
| Missing urine or volume with unknown duration | Urine stage unknown; never call it zero output | Missing charting is not anuria |
| Exact zero for a complete 12h interval, no weight | Existing stage-3 urine criterion | Anuria duration does not require body mass |
| Exact zero over 18h | Establishes zero over the contained last 12h | This inference needs no assumption about volume distribution |
| Eleven hourly zeros, missing one hour in the last 12h | No 12h anuria claim; complete last 6h can still meet stage 1 | Each criterion needs its own confirmed duration |
| Positive 18h total, no shorter collections | Do not prorate into a 6h/12h rate | The within-interval volume distribution is unknown |
| Complete positive-volume collection without weight | Coverage true, volume known, normalized rate unknown | Known duration and known body mass are separate requirements |
| Overlapping collections, including one crossing a window boundary | Unknown coverage rather than double counting | A skipped long collection must not hide contradictory records |
| Equivalent duplicate urine row omits duration | Preserve known duration regardless of row order | Duplicate formatting should not alter an alert |
| A genuinely later correction removes duration | Old duration is no longer usable | An obsolete record must not invent current coverage |
| Exactly 0.5 mL/kg/h or 0.3 mL/kg/h | Strict below-threshold criteria stay strict | Avoids falsely promoting a boundary value |
| AKI already observed, recovered AKI, dialysis/RRT | Exclude a first-new-AKI forecast as appropriate | Existing/recurrent disease is outside the trained target |
| Sample at prediction time; sample exactly 24h later | First is not future; second is within the horizon | Endpoint interval is (t, t+24h] |
| Early discharge/death without an observed endpoint | Censor; do not invent a negative label | Missing follow-up is not proof of no injury |
| Positive endpoint observed before early exit | Keep observed positive | Full negative follow-up is not needed to prove a positive |
| Sparse/stale data | Abstain with a reason | Insufficient evidence must not become a reassuring 0% |
| Same patient has several ICU stays | Keep all stays in one partition | Prevents patient leakage across training and evaluation |
| Drug/ventilation context changes | Accepted but no score change in this version | These fields are not active learned predictors |
| False alert and missed early window | Retain examples and report both | A working demonstration must expose errors as well as successes |

KDIGO thresholds follow the [2012 guideline, tables 2 and 7](https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf).
Timing follows the [official eICU lab definitions](https://eicu.mit.edu/eicutables/lab/).
Inferring a zero rate without weight and clipping a longer exact-zero collection
are arithmetic consequences of nonnegative volume, not extra guideline quotations.

## Independent checks and how to run

[test_expert_cases.py](../tests/test_expert_cases.py) includes a separate pairwise
creatinine reference using decimal-exact fractions. Thirty-two reproducible
timelines contain delayed results and revisions; every availability snapshot
checks current stages and earliest as-of recognition against that reference.
Sixteen seeded urine histories use separate 6h/12h/24h sums, and eight permutations
check that reordering and future readings cannot change available features.
These seeded cases supplement the explicit counterexamples above.

Other suites check guideline example trajectories, label censoring, source units,
extraction, split/calibration isolation, training-versus-API feature parity, SQL,
CSV, API validation, readiness and corrupt artifacts. Live HTTP checks exercise
authentication, CORS, replay, batches and the actual Windows API launcher.

Run verify.bat --http. For the separate launcher check run:
.venv\Scripts\python.exe scripts\smoke_http.py --launcher
Current counts and outcomes are in [the audit](../reports/LOGIC_AUDIT.md).

The reference checks validate the stated operational rules, not whether those
rules resolve every clinical ambiguity. Admission baselines can be missing,
source urine durations are unknown, false alerts remain frequent, and reverse
cross-dataset transfer is weak. A clinician-reviewed cohort, an untouched external
evaluation and prospective workflow testing remain necessary for clinical use.

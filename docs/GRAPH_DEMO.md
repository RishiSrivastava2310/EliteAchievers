# Showing the patient story to judges

1. Double-click show_graphs.bat.
2. Start with "Patient 1". At ICU hour 150 the model raises a warning.
3. Point to the solid blood-test readings and the model's risk above the warning line.
4. Use "Show what happened later": the later kidney-injury sample is 18.35 hours after that selected warning.
5. Drag the timeline to compare earlier readings and earlier calculated risk.
6. Use **Next patient** / **Previous patient** to explore 15 real patient stories.
7. Compare "Stable example" and "Rising example" to explain the concept simply.

Suggested sentence: "The model looks at changes in the patient's measurements,
raises an early kidney warning, and lets us compare it with what the later
record shows. This selected historical case gives an 18.35-hour warning interval."

The 15 real cases come from eICU's public demo. Blood tests use recorded sample
times; delayed results enter only once available. Every risk dot is a real
calculation using available inputs. The replay recalculates every six hours. Patient 1 retains its full replay; the other patients show the recent history up to the selected forecast, with next-day blood tests available through the outcome toggle.
Connecting lines guide the eye; they are not additional measurements.
The view shows the recent portion of the stay around the selected point; replay earlier points to inspect earlier readings. Later records are dashed and never
used as earlier model inputs. Future risk scores are not revealed by the outcome toggle.
The selected outcome marker is the qualifying creatinine sample, not a claim
that biological injury begins at that exact time.

The 15 real patients include five warning-before-injury examples, four
below-threshold examples with no injury recorded in the next day, three warnings
without a qualifying injury sample in that day, and three below-threshold
predictions before an injury sample. These are selected demonstrations, not an
estimate of accuracy. Each negative next-day outcome requires full follow-up
and a blood-test sample late in that day. Replay points without that coverage
show "Follow-up incomplete". Later blood tests can be revealed for every real
patient, including patients without a recorded injury.

The two comparison examples use labelled synthetic inputs and the trained model.
No future outcomes are fabricated. Missing/unscorable estimates are shown as
"Not scored", with a message in the plot instead of an empty chart or a fake zero.

The standalone report embeds its plots and data. No API server, CDN, chart
service or internet connection is needed to open it. Print / Save as PDF gives
a shareable view of the current story. reports/judge_graphs.png is a static preview.

Optional plain explanations use backend settings in .env:
GEMINI_API_KEY=your_private_key
GEMINI_MODEL=gemini-3.5-flash-lite

Keep this key on the backend. Save settings and rerun show_graphs.bat; restart
start_api.bat for API calls. Without a key, the report uses an existing plain
explanation. Provider failures also preserve working graphs and explanations.
Only the selected frame of each case requests an AI explanation during the
build; repeated requests stop if the provider is unavailable; other replay points use the deterministic explanation. The application
frontend can request any point through POST /v1/summarize. The display heading is
"What this means", with no provider branding.

From PowerShell, run:

```powershell
.\show_graphs.bat
.\show_graphs.bat next
```

The first command starts at Patient 1. The second opens the next real patient
report (cycling through 15 selected historical patients). The browser buttons
also cycle between these 15 patients. Stable and Rising are separate illustrative
comparisons. The command remembers the last command-selected patient; browser clicks
stay within the open report.

show_graphs.bat reuses a current report. Pass --refresh to rebuild it.
The exported report is a snapshot; rebuild after changing data/model/code/settings.
scripts/check_showcase.js tests all control states without network requests.
tests/test_showcase.py checks record/plot and saved-prediction parity.

API implementation reference:
https://ai.google.dev/gemini-api/docs/structured-output
Model lifecycle reference:
https://ai.google.dev/gemini-api/docs/deprecations

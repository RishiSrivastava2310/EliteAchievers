import {
  measurementKeys,
  type Patient,
  type Reading,
  type Recognition,
  type PatientSnapshot,
  type RiskCategory,
} from './types';
export const HOUR = 3_600_000;
export const units: Record<string, string> = {
  creatinine: 'mg/dL',
  bun: 'mg/dL',
  urineOutput: 'mL/kg/h',
  map: 'mmHg',
  heartRate: 'bpm',
  spo2: '%',
  potassium: 'mmol/L',
  bicarbonate: 'mmol/L',
  lactate: 'mmol/L',
};
export const labels: Record<string, string> = {
  creatinine: 'Creatinine',
  bun: 'BUN',
  urineOutput: 'Urine output',
  map: 'Mean arterial pressure',
  heartRate: 'Heart rate',
  spo2: 'SpO₂',
  potassium: 'Potassium',
  bicarbonate: 'Bicarbonate',
  lactate: 'Lactate',
};
export function atHour(p: Patient, hour: number) {
  return new Date(new Date(p.admittedAt).getTime() + hour * HOUR).toISOString();
}
export function hourOf(p: Patient, at: string) {
  return (Date.parse(at) - Date.parse(p.admittedAt)) / HOUR;
}
export function visibleReadings(p: Patient, at: string): Reading[] {
  return p.readings.filter((r) => r.at <= at && r.availableAt <= at).sort((a, b) => a.at.localeCompare(b.at));
}
export function latest(readings: Reading[], key: string) {
  return readings.filter((r) => r.key === key).at(-1);
}
export interface CreatinineComparison {
  reading: Reading;
  delta48?: number;
  ratio7?: number;
  stage: number;
}
function compareCreatinine(readings: Reading[]): CreatinineComparison[] {
  const cr = readings
    .filter((r) => r.key === 'creatinine' && r.value > 0)
    .sort((a, b) => a.at.localeCompare(b.at));
  return cr.map((reading, i) => {
    const before = cr
      .slice(0, i)
      .filter((r) => r.at < reading.at && Date.parse(reading.at) - Date.parse(r.at) <= 168 * HOUR);
    const in48 = before.filter((r) => Date.parse(reading.at) - Date.parse(r.at) <= 48 * HOUR);
    const delta48 = in48.length ? reading.value - Math.min(...in48.map((r) => r.value)) : undefined;
    const ratio7 = before.length ? reading.value / Math.min(...before.map((r) => r.value)) : undefined;
    const meets = (delta48 ?? 0) >= 0.3 - 1e-9 || (ratio7 ?? 0) >= 1.5 - 1e-9;
    const stage = !meets
      ? 0
      : (ratio7 ?? 0) >= 3 - 1e-9 || (reading.value >= 4 && (delta48 ?? 0) >= 0.3 - 1e-9)
        ? 3
        : (ratio7 ?? 0) >= 2 - 1e-9
          ? 2
          : 1;
    return { reading, delta48, ratio7, stage };
  });
}
export function creatinineSignal(readings: Reading[], at: string) {
  const comparisons = compareCreatinine(
    readings.filter((r) => Date.parse(r.at) <= Date.parse(at) && Date.parse(r.availableAt) <= Date.parse(at)),
  );
  const current = comparisons.at(-1);
  const observed = comparisons.find((c) => c.stage > 0);
  const rising = (current?.delta48 ?? 0) > 1e-9 || (current?.ratio7 ?? 1) > 1 + 1e-9;
  const tone: 'red' | 'orange' | 'blue' | 'neutral' = observed
    ? 'red'
    : current?.ratio7 === undefined
      ? 'neutral'
      : rising
        ? 'orange'
        : 'blue';
  return {
    current,
    observed,
    tone,
    message:
      tone === 'red'
        ? 'Call The Doctor'
        : tone === 'orange'
          ? 'May Need Attention'
          : tone === 'blue'
            ? 'No rise detected'
            : 'Comparison unavailable',
    stale: Boolean(current && Date.parse(at) - Date.parse(current.reading.at) > 12 * HOUR),
  };
}
// Research implementation of the feasibility document's creatinine definition.
// Only earlier, available measurements contribute to baseline and onset recognition.
export function recognize(readings: Reading[], at: string, weightKg?: number): Recognition {
  const available = readings
    .filter((r) => Date.parse(r.at) <= Date.parse(at) && Date.parse(r.availableAt) <= Date.parse(at))
    .sort((a, b) => a.at.localeCompare(b.at));
  const cr = available.filter((r) => r.key === 'creatinine' && r.value > 0);
  let stage = 0;
  let onsetAt: string | undefined;
  const evidence: string[] = [];
  for (const comparison of compareCreatinine(cr)) {
    if (comparison.stage) {
      stage = Math.max(stage, comparison.stage);
      onsetAt ??= comparison.reading.at;
    }
  }
  if (stage) evidence.push(`Creatinine-defined stage ${stage} observed by the selected time.`);
  const urine = available.filter(
    (r) => r.key === 'urineOutput' && r.value >= 0 && r.intervalHours && r.intervalHours > 0,
  );
  const urineAvailable = Boolean(weightKg && urine.length);
  // Urine readings are normalized interval averages. Require contiguous, non-overlapping windows.
  if (urineAvailable) {
    for (let i = 0; i < urine.length; i++) {
      let hours = 0;
      let volume = 0;
      let end = Date.parse(urine[i].at);
      for (let j = i; j >= 0; j--) {
        const r = urine[j];
        const duration = r.intervalHours!;
        if (Date.parse(r.at) !== end) break;
        hours += duration;
        volume += r.value * duration;
        end -= duration * HOUR;
        const avg = volume / hours;
        const us =
          (hours >= 24 && avg < 0.3) || (hours >= 12 && avg === 0)
            ? 3
            : hours >= 12 && avg < 0.5
              ? 2
              : hours >= 6 && avg < 0.5
                ? 1
                : 0;
        if (us) {
          stage = Math.max(stage, us);
          onsetAt = !onsetAt || urine[i].at < onsetAt ? urine[i].at : onsetAt;
        }
      }
    }
    if (stage && !evidence.length)
      evidence.push('Urine-output criterion met over complete recorded intervals.');
  }
  if (!urineAvailable)
    evidence.push('Urine-output criteria are not assessable without weight and complete interval data.');
  const recentCr = cr.at(-1);
  const enough = cr.length >= 2 && !!recentCr && Date.parse(at) - Date.parse(recentCr.at) <= 24 * HOUR;
  return {
    status: stage ? 'Observed AKI' : enough ? 'No AKI observed' : 'Insufficient data',
    stage,
    onsetAt,
    evidence,
    urineAvailable,
  };
}
export function snapshot(p: Patient, hour: number, threshold = 0.5): PatientSnapshot {
  const at = atHour(p, hour);
  const readings = visibleReadings(p, at);
  const recognition = recognize(readings, at, p.weightKg);
  const eligibility =
    p.age < 18
      ? 'Adult cohort only (18+).'
      : p.durationHours < 24
        ? 'ICU stay is shorter than 24 hours.'
        : p.esrd || p.chronicDialysis
          ? 'Excluded: ESRD or chronic dialysis.'
          : p.rrtAt && p.rrtAt <= at
            ? 'Renal replacement therapy observed before prediction.'
            : hour < 12
              ? 'Prediction starts at ICU hour 12.'
              : recognition.status === 'Observed AKI'
                ? 'AKI already observed; new-onset prediction is ineligible.'
                : recognition.status === 'Insufficient data'
                  ? 'Insufficient recent creatinine measurements.'
                  : null;
  const forecast = !eligibility
    ? p.forecasts
        .filter((f) => f.at <= at && f.availableAt <= at && Date.parse(at) - Date.parse(f.at) <= 6 * HOUR)
        .sort((a, b) => a.at.localeCompare(b.at))
        .at(-1)
    : undefined;
  const ended = p.outcome && p.outcome.at <= at && p.outcome.availableAt <= at;
  const eligibleForecast = ended ? undefined : forecast;
  const probability = eligibleForecast?.probability;
  const risk: RiskCategory =
    probability === undefined
      ? 'Unavailable'
      : probability >= threshold
        ? 'High'
        : probability >= threshold / 2
          ? 'Moderate'
          : 'Low';
  const fresh = measurementKeys.filter((k) => {
    const r = latest(readings, k);
    return r && Date.parse(at) - Date.parse(r.at) <= 12 * HOUR;
  }).length;
  return {
    patient: p,
    readings,
    recognition,
    forecast: eligibleForecast,
    probability,
    risk,
    eligibility: ended
      ? 'A completed ICU outcome is recorded; new ICU forecasts are not applicable.'
      : eligibility,
    completeness: Math.round((fresh / measurementKeys.length) * 100),
    latestAt: readings.at(-1)?.at,
  };
}
export function formatTime(at?: string) {
  return at
    ? new Date(at).toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'UTC',
      }) + ' UTC'
    : 'Unavailable';
}

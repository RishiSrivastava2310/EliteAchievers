import type { Patient } from './types';
import { atHour, hourOf, snapshot } from './clinical';

export interface ForecastPoint {
  hour: number;
  risk: number | null;
  synthetic?: boolean;
}

export function forecastHistory(patient: Patient, hour: number, threshold: number) {
  const selectedAt = atHour(patient, hour);
  const forecasts = patient.forecasts
    .filter(
      (f) =>
        f.at <= selectedAt &&
        f.availableAt <= selectedAt &&
        !snapshot(patient, hourOf(patient, f.at), threshold).eligibility,
    )
    .sort((a, b) => a.at.localeCompare(b.at));
  // Keep the supplied precision: rounding 49.96% to 50% must not create an alert.
  const points = forecasts.map((f) => ({
    hour: hourOf(patient, f.at),
    risk: f.probability * 100,
    synthetic: f.synthetic,
  }));
  const rows: ForecastPoint[] = [...points];
  for (let i = rows.length - 1; i > 0; i--) {
    if (rows[i].hour - rows[i - 1].hour > 6) rows.splice(i, 0, { hour: rows[i - 1].hour + 6.01, risk: null });
  }
  return {
    forecasts,
    points,
    rows,
    latest: points.at(-1),
    firstAlert: points.find((p) => p.risk >= threshold * 100),
    current: snapshot(patient, hour, threshold),
    min: points.length ? Math.min(...points.map((p) => p.risk)) : null,
    max: points.length ? Math.max(...points.map((p) => p.risk)) : null,
  };
}

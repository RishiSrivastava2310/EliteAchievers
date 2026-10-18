import { measurementKeys, type Patient, type IcuOutcome } from './types';

export function normalizeOutcome(p: Patient, outcome: IcuOutcome): IcuOutcome {
  if (
    !outcome ||
    !['died', 'discharged_alive'].includes(outcome.status) ||
    typeof outcome.at !== 'string' ||
    typeof outcome.availableAt !== 'string' ||
    !Number.isFinite(Date.parse(outcome.at)) ||
    !Number.isFinite(Date.parse(outcome.availableAt)) ||
    Date.parse(outcome.availableAt) < Date.parse(outcome.at) ||
    Date.parse(outcome.at) < Date.parse(p.admittedAt) ||
    Date.parse(outcome.at) > Date.parse(p.admittedAt) + p.durationHours * 3_600_000 ||
    p.readings.some((r) => Date.parse(r.at) > Date.parse(outcome.at))
  ) {
    throw new Error(
      `${p.id}: outcome must be a valid ICU death or live discharge, within the stay, after its measurements, and available no earlier than it occurred.`,
    );
  }
  return {
    status: outcome.status,
    at: new Date(outcome.at).toISOString(),
    availableAt: new Date(outcome.availableAt).toISOString(),
  };
}

/** Validate and canonicalize at the API boundary before any temporal comparison. */
export function normalizePatient(p: Patient): Patient {
  const validDate = (value: string) => typeof value === 'string' && Number.isFinite(Date.parse(value));
  if (
    !p ||
    typeof p.id !== 'string' ||
    !p.id ||
    !Number.isFinite(p.age) ||
    p.age < 0 ||
    !Number.isFinite(p.durationHours) ||
    p.durationHours <= 0 ||
    !validDate(p.admittedAt) ||
    !Array.isArray(p.readings) ||
    !Array.isArray(p.forecasts) ||
    typeof p.synthetic !== 'boolean' ||
    typeof p.esrd !== 'boolean' ||
    typeof p.chronicDialysis !== 'boolean' ||
    !['Female', 'Male', 'Unknown'].includes(p.sex) ||
    !['MIMIC-IV', 'eICU-CRD', 'Manual', 'CSV'].includes(p.source)
  ) {
    throw new Error('A patient response is missing required or correctly typed fields.');
  }
  if (
    (p.weightKg !== undefined && (!Number.isFinite(p.weightKg) || p.weightKg <= 0)) ||
    (p.rrtAt !== undefined && !validDate(p.rrtAt))
  )
    throw new Error('A patient response contains an invalid weight or RRT time.');
  const readings = p.readings
    .map((r) => {
      if (
        !r ||
        !measurementKeys.includes(r.key) ||
        !Number.isFinite(r.value) ||
        r.value < 0 ||
        (r.key === 'creatinine' && r.value === 0) ||
        !validDate(r.at) ||
        !validDate(r.availableAt) ||
        Date.parse(r.availableAt) < Date.parse(r.at) ||
        (r.intervalHours !== undefined &&
          (!Number.isFinite(r.intervalHours) || r.intervalHours <= 0 || r.intervalHours > 24))
      )
        throw new Error('Backend measurements contain invalid values or timestamps.');
      return { ...r, at: new Date(r.at).toISOString(), availableAt: new Date(r.availableAt).toISOString() };
    })
    .sort((a, b) => a.at.localeCompare(b.at));
  const forecasts = p.forecasts
    .map((f) => {
      if (
        !f ||
        !Number.isFinite(f.probability) ||
        f.probability < 0 ||
        f.probability > 1 ||
        f.horizonHours !== 24 ||
        typeof f.synthetic !== 'boolean' ||
        typeof f.modelVersion !== 'string' ||
        !validDate(f.at) ||
        !validDate(f.availableAt) ||
        Date.parse(f.availableAt) < Date.parse(f.at)
      )
        throw new Error('Backend forecasts contain invalid values or timestamps.');
      return { ...f, at: new Date(f.at).toISOString(), availableAt: new Date(f.availableAt).toISOString() };
    })
    .sort((a, b) => a.at.localeCompare(b.at));
  return {
    ...p,
    admittedAt: new Date(p.admittedAt).toISOString(),
    rrtAt: p.rrtAt ? new Date(p.rrtAt).toISOString() : undefined,
    readings,
    forecasts,
    outcome: p.outcome === undefined ? undefined : normalizeOutcome(p, p.outcome),
  };
}

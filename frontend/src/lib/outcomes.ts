import type { Patient, OutcomeUpdate } from './types';
import { atHour, hourOf } from './clinical';
import { normalizeOutcome } from './validation';

export function replayEndHour(patients: Patient[]) {
  return Math.ceil(
    Math.max(
      72,
      ...patients.flatMap((p) => [p.durationHours, p.outcome ? hourOf(p, p.outcome.availableAt) : 0]),
    ),
  );
}

export function fatalityAt(patients: Patient[], hour: number) {
  const known = patients.filter(
    (p) =>
      p.outcome &&
      Date.parse(p.outcome.at) <= Date.parse(atHour(p, hour)) &&
      Date.parse(p.outcome.availableAt) <= Date.parse(atHour(p, hour)),
  );
  const deaths = known.filter((p) => p.outcome?.status === 'died').length;
  return {
    deaths,
    alive: known.length - deaths,
    known: known.length,
    awaiting: patients.length - known.length,
    rate: known.length ? (deaths / known.length) * 100 : null,
  };
}
export function fatalitySeries(patients: Patient[], hour: number) {
  // A step occurs only when a terminal outcome has occurred AND become available.
  const times = new Set([0, hour]);
  for (const p of patients) {
    if (!p.outcome) continue;
    const availableHour = Math.max(hourOf(p, p.outcome.at), hourOf(p, p.outcome.availableAt));
    if (availableHour >= 0 && availableHour <= hour) times.add(availableHour);
  }
  return [...times].sort((a, b) => a - b).map((h) => ({ hour: h, ...fatalityAt(patients, h) }));
}
export function applyOutcomes(patients: Patient[], updates: OutcomeUpdate[]) {
  const normalized = new Map<string, OutcomeUpdate['outcome']>();
  for (const update of updates) {
    if (normalized.has(update.patientId)) throw new Error(`Duplicate ICU stay ID: ${update.patientId}.`);
    const p = patients.find((p) => p.id === update.patientId);
    if (!p) throw new Error(`ICU stay ${update.patientId} is not in the loaded cohort.`);
    normalized.set(p.id, normalizeOutcome(p, update.outcome));
  }
  return patients.map((p) => (normalized.has(p.id) ? { ...p, outcome: normalized.get(p.id) } : p));
}
export function parseOutcomeCsv(text: string): OutcomeUpdate[] {
  if (text.length > 2_000_000) throw new Error('CSV must be smaller than 2 MB.');
  const rows = text
    .trim()
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter(Boolean);
  if (rows.length < 2) throw new Error('CSV must contain a header and at least one outcome.');
  const header = rows[0].split(',').map((s) => s.trim());
  for (const field of ['stay_id', 'status', 'timestamp'])
    if (!header.includes(field)) throw new Error(`Missing required column: ${field}.`);
  const seen = new Set<string>();
  return rows.slice(1).map((row, i) => {
    const cells = row.split(',').map((s) => s.trim().replace(/^"|"$/g, ''));
    const get = (field: string) => cells[header.indexOf(field)] || '';
    const patientId = get('stay_id');
    const status = get('status');
    const at = get('timestamp');
    const availableAt = get('available_at') || at;
    if (!patientId || seen.has(patientId)) throw new Error(`Row ${i + 2}: missing or duplicate ICU stay ID.`);
    if (status !== 'died' && status !== 'discharged_alive')
      throw new Error(`Row ${i + 2}: status must be died or discharged_alive.`);
    for (const time of [at, availableAt])
      if (!/Z$|[+-]\d{2}:\d{2}$/.test(time) || !Number.isFinite(Date.parse(time)))
        throw new Error(`Row ${i + 2}: timestamps need an ISO date and timezone.`);
    if (Date.parse(availableAt) < Date.parse(at))
      throw new Error(`Row ${i + 2}: availability cannot precede the outcome.`);
    seen.add(patientId);
    return {
      patientId,
      outcome: { status, at: new Date(at).toISOString(), availableAt: new Date(availableAt).toISOString() },
    };
  });
}
export function outcomeCsvTemplate(patients: Patient[]) {
  return (
    'stay_id,status,timestamp,available_at\n' +
    patients
      .slice(0, 3)
      .map((p) =>
        [
          p.id,
          p.outcome?.status ?? 'discharged_alive',
          p.outcome?.at ?? atHour(p, p.durationHours),
          p.outcome?.availableAt ?? atHour(p, p.durationHours),
        ].join(','),
      )
      .join('\n')
  );
}

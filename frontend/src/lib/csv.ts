import { measurementKeys, type Reading } from './types';
export function parseCsv(text: string): Reading[] {
  if (text.length > 2_000_000) throw new Error('CSV must be smaller than 2 MB.');
  const rows = text
    .trim()
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter(Boolean);
  if (rows.length < 2) throw new Error('CSV must contain a header and at least one reading.');
  const header = rows[0].split(',').map((v) => v.trim());
  for (const key of ['timestamp', 'measurement', 'value'])
    if (!header.includes(key)) throw new Error(`Missing required column: ${key}.`);
  return rows.slice(1).map((row, i) => {
    const cells = row.split(',').map((v) => v.trim().replace(/^"|"$/g, ''));
    const get = (key: string) => cells[header.indexOf(key)];
    const at = get('timestamp');
    const key = get('measurement');
    const value = Number(get('value'));
    const availableAt = get('available_at') || at;
    const interval = get('interval_hours');
    if (!/Z$|[+-]\d{2}:\d{2}$/.test(at) || !Number.isFinite(Date.parse(at)))
      throw new Error(`Row ${i + 2}: timestamp needs an ISO date and timezone (e.g. 2025-02-14T12:00:00Z).`);
    if (!Number.isFinite(Date.parse(availableAt)) || Date.parse(availableAt) < Date.parse(at))
      throw new Error(`Row ${i + 2}: availability cannot precede measurement time.`);
    if (!measurementKeys.includes(key as (typeof measurementKeys)[number]))
      throw new Error(`Row ${i + 2}: unknown measurement '${key}'.`);
    if (get('value') === '' || !Number.isFinite(value) || value < 0)
      throw new Error(`Row ${i + 2}: value must be a nonnegative number.`);
    if (key === 'creatinine' && value === 0)
      throw new Error(`Row ${i + 2}: creatinine must be greater than zero.`);
    if (interval && (!Number.isFinite(Number(interval)) || Number(interval) <= 0 || Number(interval) > 24))
      throw new Error(`Row ${i + 2}: interval_hours must be between 0 and 24.`);
    return {
      id: crypto.randomUUID(),
      at: new Date(at).toISOString(),
      availableAt: new Date(availableAt).toISOString(),
      key: key as Reading['key'],
      value,
      intervalHours: interval ? Number(interval) : undefined,
    };
  });
}
export function downloadFile(name: string, content: string, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const csvTemplate =
  'timestamp,measurement,value,available_at,interval_hours\n2025-02-14T06:00:00Z,creatinine,0.9,2025-02-14T06:30:00Z,\n2025-02-14T12:00:00Z,creatinine,1.0,2025-02-14T12:30:00Z,\n2025-02-14T12:00:00Z,urineOutput,0.8,2025-02-14T12:00:00Z,6\n';

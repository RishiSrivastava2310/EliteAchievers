import { useState, useEffect, type FormEvent } from 'react';
import { Upload, Download, Plus } from 'lucide-react';
import { useStore } from '../lib/store';
import { parseCsv, downloadFile, csvTemplate } from '../lib/csv';
import { atHour, labels, units, HOUR } from '../lib/clinical';
import { measurementKeys, type Patient, type Reading, type Source } from '../lib/types';
import { Modal, Notice, Button } from './ui';
export function DataEntry({
  open,
  onOpenChange,
  patient,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  patient?: Patient;
}) {
  const { addPatient, addReadings, mode, hour } = useStore();
  const [tab, setTab] = useState<'manual' | 'csv'>('manual');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState<Reading['key']>('creatinine');
  const [file, setFile] = useState<File | null>(null);
  const [id, setId] = useState(`SYN-LOCAL-${String(Date.now()).slice(-5)}`);
  const [age, setAge] = useState('60');
  const [sex, setSex] = useState<'Female' | 'Male' | 'Unknown'>('Unknown');
  const [admission, setAdmission] = useState('2025-02-14T06:00');
  const [timestamp, setTimestamp] = useState(
    (patient ? atHour(patient, hour) : '2025-02-14T06:00:00Z').slice(0, 16),
  );
  const [available, setAvailable] = useState(timestamp);
  const [value, setValue] = useState('');
  const [interval, setInterval] = useState('');
  const [weight, setWeight] = useState('');
  useEffect(() => {
    if (open) {
      setError('');
      if (patient) {
        const selected = atHour(patient, Math.min(hour, patient.durationHours)).slice(0, 16);
        setTimestamp(selected);
        setAvailable(selected);
      }
    }
  }, [open, patient, hour]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      let readings: Reading[];
      if (tab === 'csv') {
        if (!file) throw new Error('Choose a CSV history file.');
        readings = parseCsv(await file.text());
      } else {
        const at = new Date(timestamp + 'Z').toISOString();
        const availableAt = new Date(available + 'Z').toISOString();
        if (!value || !Number.isFinite(Number(value)) || Number(value) < 0)
          throw new Error('Enter a valid nonnegative measurement.');
        if (key === 'creatinine' && Number(value) === 0)
          throw new Error('Creatinine must be greater than zero.');
        if (availableAt < at) throw new Error('Availability cannot precede measurement time.');
        readings = [
          {
            id: crypto.randomUUID(),
            at,
            availableAt,
            key,
            value: Number(value),
            intervalHours: key === 'urineOutput' && interval ? Number(interval) : undefined,
          },
        ];
      }
      const admissionAt = patient?.admittedAt || new Date(admission + 'Z').toISOString();
      if (
        readings.some((r) => r.at < admissionAt || (patient && r.at > atHour(patient, patient.durationHours)))
      )
        throw new Error('Measurements must fall within the ICU stay timeline.');
      if (patient) await addReadings(patient.id, readings);
      else {
        if (!/^SYN-[A-Za-z0-9-]+$/.test(id))
          throw new Error('Use a fictional ID beginning with SYN- and letters, numbers or hyphens.');
        const durationHours = Math.max(
          72,
          ...readings.map((r) => (Date.parse(r.at) - Date.parse(admissionAt)) / HOUR),
        );
        addPatient({
          id,
          age: Number(age),
          sex,
          source: (tab === 'csv' ? 'CSV' : 'Manual') as Source,
          unit: 'Research ICU',
          admission: 'Locally entered synthetic history',
          admittedAt: admissionAt,
          durationHours,
          weightKg: weight ? Number(weight) : undefined,
          esrd: false,
          chronicDialysis: false,
          synthetic: true,
          readings,
          forecasts: [],
        });
      }
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to save readings.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={patient ? 'Add timestamped observations' : 'Add a synthetic ICU stay'}
      description={
        patient
          ? `Append readings to ${patient.id}. Forecasts are never generated from entered values.`
          : 'Use fictional, de-identified information. Entries remain in this browser session.'
      }
    >
      <div className="segmented">
        <button
          className={tab === 'manual' ? 'selected' : ''}
          onClick={() => {
            setTab('manual');
            setError('');
          }}
        >
          <Plus size={15} />
          Manual entry
        </button>
        <button
          className={tab === 'csv' ? 'selected' : ''}
          onClick={() => {
            setTab('csv');
            setError('');
          }}
        >
          <Upload size={15} />
          CSV history
        </button>
      </div>
      <Notice>
        Only enter synthetic data in this browser workspace. Restricted patient records must stay within your
        approved local infrastructure.
      </Notice>
      <form onSubmit={submit} className="entry-form">
        {!patient && (
          <>
            <div className="form-grid">
              <label>
                Fictional ICU stay ID
                <input required value={id} onChange={(e) => setId(e.target.value)} maxLength={60} />
              </label>
              <label>
                Age (years)
                <input
                  required
                  type="number"
                  min="18"
                  max="120"
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                />
              </label>
              <label>
                Recorded sex
                <select value={sex} onChange={(e) => setSex(e.target.value as typeof sex)}>
                  <option>Unknown</option>
                  <option>Female</option>
                  <option>Male</option>
                </select>
              </label>
              <label>
                Weight (kg, optional)
                <input
                  type="number"
                  min="20"
                  max="400"
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                />
              </label>
            </div>
            <label>
              ICU admission (UTC)
              <input
                type="datetime-local"
                required
                value={admission}
                onChange={(e) => setAdmission(e.target.value)}
              />
            </label>
          </>
        )}
        {tab === 'manual' ? (
          <>
            <div className="form-grid">
              <label>
                Measurement
                <select value={key} onChange={(e) => setKey(e.target.value as Reading['key'])}>
                  {measurementKeys.map((k) => (
                    <option key={k} value={k}>
                      {labels[k]} ({units[k]})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Value ({units[key]})
                <input
                  required
                  type="number"
                  min="0"
                  step="any"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="0.00"
                />
              </label>
              <label>
                Measured at (UTC)
                <input
                  type="datetime-local"
                  required
                  value={timestamp}
                  onChange={(e) => {
                    setTimestamp(e.target.value);
                    setAvailable(e.target.value);
                  }}
                />
              </label>
              <label>
                Available at (UTC)
                <input
                  type="datetime-local"
                  required
                  value={available}
                  onChange={(e) => setAvailable(e.target.value)}
                />
              </label>
            </div>
            {key === 'urineOutput' && (
              <label>
                Complete collection interval (hours)
                <input
                  type="number"
                  min="0.1"
                  max="24"
                  step="0.1"
                  value={interval}
                  onChange={(e) => setInterval(e.target.value)}
                  placeholder="Required for urine-output recognition"
                />
              </label>
            )}
          </>
        ) : (
          <div className="csv-upload">
            <Upload size={28} />
            <strong>Choose a timestamped CSV history</strong>
            <p>timestamp, measurement, value, available_at, interval_hours</p>
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="CSV history file"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => downloadFile('aki-nator-history-template.csv', csvTemplate)}
            >
              <Download size={15} />
              Download CSV template
            </Button>
          </div>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="modal-actions">
          <Button variant="secondary" type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || (!patient && mode === 'backend')}>
            {busy ? 'Saving…' : patient ? 'Save observations' : 'Add synthetic stay'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

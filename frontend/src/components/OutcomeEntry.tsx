import { useEffect, useState, type FormEvent } from 'react';
import { Upload, Download, ClipboardPlus } from 'lucide-react';
import { useStore } from '../lib/store';
import { atHour } from '../lib/clinical';
import { parseOutcomeCsv, outcomeCsvTemplate } from '../lib/outcomes';
import { downloadFile } from '../lib/csv';
import type { IcuOutcome } from '../lib/types';
import { Modal, Button, Notice } from './ui';

export function OutcomeEntry({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, saveOutcomes } = useStore();
  const patients = data?.patients ?? [];
  const [tab, setTab] = useState<'manual' | 'csv'>('manual');
  const [id, setId] = useState(patients[0]?.id ?? '');
  const p = patients.find((patient) => patient.id === id) ?? patients[0];
  const [status, setStatus] = useState<IcuOutcome['status']>('discharged_alive');
  const [at, setAt] = useState('');
  const [available, setAvailable] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open || !p) return;
    setStatus(p.outcome?.status ?? 'discharged_alive');
    setAt((p.outcome?.at ?? atHour(p, p.durationHours)).slice(0, 16));
    setAvailable((p.outcome?.availableAt ?? atHour(p, p.durationHours)).slice(0, 16));
    setError('');
  }, [open, p]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (tab === 'csv') {
        if (!file) throw new Error('Choose an outcome CSV file.');
        saveOutcomes(parseOutcomeCsv(await file.text()));
      } else {
        if (!p) throw new Error('Load an ICU stay before recording its outcome.');
        saveOutcomes([
          {
            patientId: p.id,
            outcome: {
              status,
              at: new Date(at + 'Z').toISOString(),
              availableAt: new Date(available + 'Z').toISOString(),
            },
          },
        ]);
      }
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to save outcomes.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Record ICU outcomes"
      description="Edit full-history outcomes for fictional stays. Replay charts reveal them only after their occurrence and availability times."
    >
      <div className="segmented">
        <button
          className={tab === 'manual' ? 'selected' : ''}
          onClick={() => {
            setTab('manual');
            setError('');
          }}
        >
          <ClipboardPlus size={16} />
          Manual outcome
        </button>
        <button
          className={tab === 'csv' ? 'selected' : ''}
          onClick={() => {
            setTab('csv');
            setError('');
          }}
        >
          <Upload size={16} />
          Outcome CSV
        </button>
      </div>
      <form className="entry-form" onSubmit={submit}>
        {tab === 'manual' ? (
          <>
            <label>
              ICU stay
              <select
                aria-label="Outcome ICU stay"
                value={p?.id ?? ''}
                onChange={(e) => setId(e.target.value)}
                required
              >
                {patients.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Recorded outcome
              <select
                aria-label="Recorded outcome"
                value={status}
                onChange={(e) => setStatus(e.target.value as IcuOutcome['status'])}
              >
                <option value="discharged_alive">Discharged alive from ICU</option>
                <option value="died">Died in ICU</option>
              </select>
            </label>
            <div className="form-grid">
              <label>
                Outcome time (UTC)
                <input type="datetime-local" required value={at} onChange={(e) => setAt(e.target.value)} />
              </label>
              <label>
                Outcome available at (UTC)
                <input
                  type="datetime-local"
                  required
                  value={available}
                  onChange={(e) => setAvailable(e.target.value)}
                />
              </label>
            </div>
          </>
        ) : (
          <>
            <label className="file-upload">
              Outcome CSV file
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setError('');
                }}
              />
            </label>
            <p>
              Required columns: stay_id, status, timestamp. Optional: available_at. Use died or
              discharged_alive, and ISO timestamps with a timezone.
            </p>
            <Button
              type="button"
              variant="secondary"
              disabled={!patients.length}
              onClick={() => downloadFile('aki-nator-outcome-template.csv', outcomeCsvTemplate(patients))}
            >
              <Download size={16} />
              Download outcome template
            </Button>
          </>
        )}
        <p className="caption">
          Saving replaces the outcome for each matching fictional stay. A terminal outcome cannot precede that
          stay’s recorded measurements. Changes remain in this browser session.
        </p>
        {error && (
          <div role="alert">
            <Notice tone="danger">{error}</Notice>
          </div>
        )}
        <div className="modal-actions">
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !patients.length}>
            {busy ? 'Saving…' : 'Save outcomes'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

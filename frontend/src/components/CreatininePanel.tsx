import { useEffect, useState } from 'react';
import { Activity, TriangleAlert, Info, FlaskConical } from 'lucide-react';
import { Panel, PanelHead, Badge, Disclosure, Button } from './ui';
import { MeasurementChart } from './charts';
import { atHour, creatinineSignal, formatTime, hourOf, snapshot } from '../lib/clinical';
import type { Patient } from '../lib/types';

export function CreatinineWarning({ patient, hour }: { patient: Patient; hour: number }) {
  const signal = creatinineSignal(patient.readings, atHour(patient, hour));
  if (signal.tone !== 'red' && signal.tone !== 'orange') return null;
  return (
    <div
      className={`creatinine-warning signal-${signal.tone}`}
      role={signal.tone === 'red' ? 'alert' : 'status'}
    >
      <TriangleAlert size={23} />
      <div>
        <strong>{signal.message}</strong>
        <p>
          {signal.tone === 'red'
            ? 'A creatinine AKI criterion has been observed in the available history.'
            : 'Serum creatinine has risen, below the AKI criteria.'}{' '}
          {patient.synthetic
            ? 'Synthetic research signal.'
            : 'Research signal; review the recorded measurements.'}
        </p>
      </div>
      <Button
        variant="secondary"
        onClick={() =>
          document.getElementById('serum-creatinine')?.scrollIntoView({
            behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
            block: 'start',
          })
        }
      >
        Review graph
      </Button>
    </div>
  );
}

export function CreatininePanel({ patient, hour }: { patient: Patient; hour: number }) {
  const [overlay, setOverlay] = useState(false);
  useEffect(() => setOverlay(false), [patient.id]);
  const signal = creatinineSignal(patient.readings, atHour(patient, hour));
  const { current, observed } = signal;
  const retrospective = overlay ? snapshot(patient, patient.durationHours).recognition : undefined;
  const Icon =
    signal.tone === 'red' || signal.tone === 'orange'
      ? TriangleAlert
      : signal.tone === 'blue'
        ? Activity
        : Info;
  return (
    <Panel className={`serum-panel serum-${signal.tone}`}>
      <PanelHead
        title="Serum creatinine"
        subtitle="Measured concentration · mg/dL"
        icon={FlaskConical}
        action={
          <label className="toggle-label">
            <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
            Retrospective overlay
          </label>
        }
      />
      <div className="serum-summary">
        <div className="serum-value">
          <strong>{current ? current.reading.value.toFixed(2) : '—'}</strong>
          <span>mg/dL</span>
        </div>
        <div className={`creatinine-signal signal-${signal.tone}`} role="status" aria-atomic="true">
          <Icon size={19} />
          <strong>{signal.message}</strong>
        </div>
      </div>
      <div className="creatinine-comparisons">
        <div>
          <span>Change within 48 hours</span>
          <strong>
            {current?.delta48 === undefined
              ? 'Unavailable'
              : `${current.delta48 > 0 ? '+' : ''}${current.delta48.toFixed(2)} mg/dL`}
          </strong>
          <small>AKI criterion: ≥ 0.30 mg/dL rise</small>
        </div>
        <div>
          <span>Ratio within 7 days</span>
          <strong>
            {current?.ratio7 === undefined ? 'Unavailable' : `${current.ratio7.toFixed(2)}× baseline`}
          </strong>
          <small>AKI criterion: ≥ 1.50× baseline</small>
        </div>
      </div>
      <p className="serum-context">
        {observed
          ? `Creatinine criterion observed at ICU hour ${hourOf(patient, observed.reading.at)}. The recorded warning remains visible during later replay.`
          : signal.tone === 'orange'
            ? 'A smaller rise is present. Orange is an attention cue for this research interface.'
            : signal.tone === 'neutral'
              ? 'At least two comparable, available measurements are required.'
              : 'No rise detected in the available comparisons. This does not rule out AKI.'}
      </p>
      <div className="serum-timestamp">
        <span>Latest: {formatTime(current?.reading.at)}</span>
        {signal.stale && <Badge tone="warning">Stale · over 12h old</Badge>}
      </div>
      {overlay && (
        <div className="retrospective-banner">
          Later outcomes shown for retrospective review only. Excluded from the selected-time risk view.
        </div>
      )}
      <MeasurementChart
        patient={patient}
        hour={hour}
        measurement="creatinine"
        retrospective={overlay}
        stroke={signal.tone === 'red' ? '#c34e48' : '#267da3'}
      />
      {overlay && (
        <div className="chart-footnote">
          {retrospective?.onsetAt
            ? `Retrospective first AKI observation: hour ${hourOf(patient, retrospective.onsetAt)} · ${formatTime(retrospective.onsetAt)}`
            : 'No AKI criteria observed in the available full history.'}
        </div>
      )}
      <div className="serum-method">
        <Disclosure title="Thresholds & color coding">
          <p>
            Red line and “Call The Doctor”: an increase of at least 0.3 mg/dL within 48 hours OR at least 1.5
            times the lowest earlier available value within 7 days. Either criterion is sufficient.
          </p>
          <p>
            The line is blue otherwise. A positive rise below those criteria shows “May Need Attention” in
            orange. This attention cue is a display convention, not a validated clinical threshold. Missing
            comparisons remain unavailable.
          </p>
          <p>
            Only measurements available at the selected hour are used. This is a research demonstration; the
            warning does not contact a doctor or replace clinical assessment.
          </p>
          <a
            className="text-link"
            href="https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf"
            target="_blank"
            rel="noreferrer"
          >
            KDIGO creatinine criteria
          </a>
        </Disclosure>
      </div>
    </Panel>
  );
}

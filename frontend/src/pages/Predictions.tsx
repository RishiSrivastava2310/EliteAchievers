import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, Clock3, ScanLine } from 'lucide-react';
import { useStore } from '../lib/store';
import { snapshot, formatTime } from '../lib/clinical';
import { PageTitle, Panel, PanelHead, Button, Badge, Notice, Disclosure, Empty } from '../components/ui';
import { RecognitionAndPrediction } from './PatientDetail';
import { CreatininePanel, CreatinineWarning } from '../components/CreatininePanel';
import { MortalityPanel } from '../components/MortalityPanel';
import { replayEndHour } from '../lib/outcomes';
export function Predictions() {
  const { data, hour, setHour, threshold, mode } = useStore();
  const [id, setId] = useState(data?.patients[0]?.id || '');
  const navigate = useNavigate();
  const p = data?.patients.find((p) => p.id === id);
  const maxHour = replayEndHour(data?.patients ?? []);
  return (
    <>
      <PageTitle
        eyebrow="PREDICTION & RECOGNITION"
        title="AKI prediction & recognition"
        icon={ScanLine}
        description="Future risk and current evidence, clearly separated."
      />
      <Panel className="prediction-picker">
        <label>
          <ScanLine size={18} />
          Select ICU stay
          <select aria-label="Prediction patient" value={id} onChange={(e) => setId(e.target.value)}>
            {data?.patients.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id} · {p.source}
              </option>
            ))}
          </select>
        </label>
        <label>
          <Clock3 size={17} />
          ICU hour
          <input
            aria-label="Prediction ICU hour"
            type="number"
            min="0"
            max={maxHour}
            value={hour}
            onChange={(e) => setHour(Math.max(0, Math.min(maxHour, Number(e.target.value))))}
          />
        </label>
        {p && (
          <Button variant="secondary" onClick={() => navigate(`/patients/${p.id}`)}>
            Open full record
            <ArrowUpRight size={16} />
          </Button>
        )}
      </Panel>
      {p ? (
        <>
          <CreatinineWarning patient={p} hour={hour} />
          <RecognitionAndPrediction patient={p} hour={hour} />
          <div id="serum-creatinine" className="clinical-feature-graphs record-anchor">
            <CreatininePanel patient={p} hour={hour} />
            <MortalityPanel patients={data?.patients ?? []} hour={hour} />
          </div>
        </>
      ) : (
        <Empty
          title="No ICU stays loaded"
          description="Add a stay in the patient directory or connect a research backend to review predictions."
          action={<Button onClick={() => navigate('/patients')}>Open patient directory</Button>}
        />
      )}
      <Panel>
        <PanelHead
          title="Prediction availability across the cohort"
          subtitle={`At selected ICU hour ${hour}. Eligibility requires no AKI so far and sufficient recent data.`}
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>ICU STAY</th>
                <th>ELIGIBILITY</th>
                <th>24-HOUR ESTIMATE</th>
                <th>GENERATED AT</th>
                <th>MODEL / PROVENANCE</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data?.patients.map((p) => {
                const s = snapshot(p, hour, threshold);
                return (
                  <tr key={p.id} className={id === p.id ? 'selected-prediction-row' : ''}>
                    <td>
                      <button
                        className="patient-id"
                        aria-pressed={id === p.id}
                        onClick={() => {
                          setId(p.id);
                          document.querySelector('.prediction-picker')?.scrollIntoView({
                            behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
                              ? 'instant'
                              : 'smooth',
                            block: 'start',
                          });
                        }}
                      >
                        {p.id}
                      </button>
                    </td>
                    <td>
                      <Badge tone={s.eligibility ? 'neutral' : 'teal'}>
                        {s.eligibility ? 'Ineligible / unavailable' : 'Eligible'}
                      </Badge>
                      {s.eligibility && <small className="eligibility-reason">{s.eligibility}</small>}
                    </td>
                    <td>
                      <b>{s.probability === undefined ? '—' : `${Math.round(s.probability * 100)}%`}</b>
                      {s.forecast?.synthetic && <small>Illustrative only</small>}
                    </td>
                    <td>{formatTime(s.forecast?.at)}</td>
                    <td>{s.forecast?.modelVersion || 'No eligible model output'}</td>
                    <td>
                      <button
                        className="icon-button"
                        aria-label={`Open ${p.id}`}
                        onClick={() => navigate(`/patients/${p.id}`)}
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Disclosure title="Clinical definitions & eligibility">
        <Notice>
          {mode === 'synthetic'
            ? 'Forecasts are simulated examples. No ML model has been trained or validated in this application.'
            : 'Forecasts are supplied by the connected backend. Check the model evaluation before interpreting them.'}
        </Notice>
        <p>
          Adult ICU stays of at least 24 hours, prediction from hour 12, excluding ESRD, chronic dialysis,
          prior renal replacement therapy and already observed AKI. The primary outcome is new
          creatinine-defined AKI in the next 24 hours. Complete weight-normalized urine-output intervals
          support secondary recognition.
        </p>
        <p>
          Baseline creatinine uses the lowest earlier available value in the preceding seven days. Later
          outcomes are reserved for retrospective review. All definitions require review by the research team
          before real-world evaluation.
        </p>
        <a
          href="https://kdigo.org/wp-content/uploads/2016/10/KDIGO-2012-AKI-Guideline-English.pdf"
          target="_blank"
          rel="noreferrer"
          className="text-link"
        >
          KDIGO 2012 AKI guideline
          <ArrowUpRight size={15} />
        </a>
      </Disclosure>
    </>
  );
}

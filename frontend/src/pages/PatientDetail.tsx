import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Download,
  Plus,
  Play,
  Pause,
  Clock3,
  Activity,
  ScanLine,
  ChevronDown,
  ChevronRight,
  CalendarDays,
  Database,
  UserRound,
  TriangleAlert,
  HeartPulse,
  Droplets,
  FlaskConical,
  ChartNoAxesCombined,
  Bell,
} from 'lucide-react';
import { useStore } from '../lib/store';
import { atHour, latest, snapshot, formatTime, labels, units, HOUR } from '../lib/clinical';
import { downloadFile } from '../lib/csv';
import { measurementKeys, type MeasurementKey, type Patient } from '../lib/types';
import { PageTitle, Panel, PanelHead, Button, Badge, Empty, Progress } from '../components/ui';
import { MeasurementChart, RiskChart } from '../components/charts';
import { DataEntry } from '../components/DataEntry';
import { CreatininePanel, CreatinineWarning } from '../components/CreatininePanel';
import { MortalityPanel } from '../components/MortalityPanel';
function RecognitionAndPrediction({ patient, hour }: { patient: Patient; hour: number }) {
  const { threshold } = useStore();
  const s = snapshot(patient, hour, threshold);
  return (
    <div className="clinical-status-grid">
      <Panel className="prediction-panel">
        <div className="clinical-card-heading">
          <span className="clinical-icon">
            <ScanLine size={20} />
          </span>
          <div>
            <h2>Early AKI prediction</h2>
            <p>New creatinine-defined AKI · next 24 hours</p>
          </div>
          <Badge tone={s.forecast?.synthetic ? 'warning' : 'neutral'}>
            {s.forecast?.synthetic ? 'Simulated' : s.forecast ? 'Model output' : 'No forecast'}
          </Badge>
        </div>
        {s.probability !== undefined ? (
          <>
            <div className="risk-large">
              {Math.round(s.probability * 100)}
              <span>%</span>
              <Badge tone={s.risk === 'High' ? 'danger' : s.risk === 'Moderate' ? 'warning' : 'teal'}>
                {s.risk} risk
              </Badge>
            </div>
            <Progress value={s.probability * 100} />
            <p className="caption">
              {s.forecast?.synthetic
                ? 'Illustrative scenario value. No trained model, clinical calibration or predictive validity.'
                : `Model ${s.forecast?.modelVersion}. Generated ${formatTime(s.forecast?.at)}.`}
            </p>
          </>
        ) : (
          <div className="unavailable-risk">
            <strong>{s.eligibility ? 'Not eligible' : 'Prediction unavailable'}</strong>
            <p>{s.eligibility || 'No model forecast was supplied for this eligible replay time.'}</p>
          </div>
        )}
        <div className="clinical-card-footer">A 24-hour horizon does not guarantee 24 hours of warning.</div>
      </Panel>
      <Panel className="recognition-panel" data-observed={s.recognition.stage > 0}>
        <div className="clinical-card-heading">
          <span className="clinical-icon">
            <Activity size={20} />
          </span>
          <div>
            <h2>AKI recognition</h2>
            <p>Evidence already available at replay time</p>
          </div>
        </div>
        <div className="recognition-result">
          <Badge
            tone={
              s.recognition.stage
                ? 'danger'
                : s.recognition.status === 'Insufficient data'
                  ? 'neutral'
                  : 'teal'
            }
          >
            {s.recognition.stage ? `Observed AKI · stage ${s.recognition.stage}` : s.recognition.status}
          </Badge>
          <p>
            {s.recognition.stage
              ? `First observed ${formatTime(s.recognition.onsetAt)}`
              : 'An absence of observed criteria does not rule out AKI.'}
          </p>
        </div>
        <ul className="recognition-evidence">
          {s.recognition.evidence.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
        <div className="clinical-card-footer">Research implementation · KDIGO 2012 criteria</div>
      </Panel>
    </div>
  );
}
export { RecognitionAndPrediction };
const recordSections = [
  { id: 'replay', label: 'Replay', icon: Clock3 },
  { id: 'trends', label: 'Clinical trends', icon: ChartNoAxesCombined },
  { id: 'measurements', label: 'Measurements', icon: FlaskConical },
  { id: 'history', label: 'Alerts & explanations', icon: Bell },
];
export function PatientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, hour, setHour, threshold, alerts } = useStore();
  const p = data?.patients.find((p) => p.id === id);
  const [playing, setPlaying] = useState(false);
  const [entry, setEntry] = useState(false);
  const [measure, setMeasure] = useState<MeasurementKey>('map');
  const [secondary, setSecondary] = useState<MeasurementKey>('bun');
  const [expanded, setExpanded] = useState(false);
  const currentHour = Math.min(hour, p?.durationHours ?? 72);
  useEffect(() => {
    if (!playing || !p) return;
    const interval = setInterval(() => {
      if (currentHour >= p.durationHours) {
        setPlaying(false);
        return;
      }
      setHour(Math.min(currentHour + 1, p.durationHours));
    }, 850);
    return () => clearInterval(interval);
  }, [playing, currentHour, p, setHour]);
  useEffect(() => {
    setPlaying(false);
  }, [id]);
  if (!p)
    return (
      <Empty
        title="ICU stay not found"
        description="This stay is not available in the loaded cohort."
        action={<Button onClick={() => navigate('/patients')}>Back to directory</Button>}
      />
    );
  const s = snapshot(p, currentHour, threshold);
  const at = atHour(p, currentHour);
  const patientAlerts = alerts.filter((a) => a.patientId === p.id);
  return (
    <>
      <button className="back-link" onClick={() => navigate('/patients')}>
        <ArrowLeft size={15} />
        Patient directory
      </button>
      <PageTitle
        eyebrow="PATIENT RECORD"
        title={p.id}
        icon={UserRound}
        description={`${p.unit} · ${p.admission}`}
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() =>
                downloadFile(`${p.id}-research-history.json`, JSON.stringify(p, null, 2), 'application/json')
              }
            >
              <Download size={15} />
              Export history
            </Button>
            <Button onClick={() => setEntry(true)}>
              <Plus size={16} />
              Add readings
            </Button>
          </>
        }
      />
      <div className="patient-demographics">
        <span>
          <UserRound size={16} />
          <strong>{p.age}</strong> years · {p.sex}
        </span>
        <span>
          <Database size={16} />
          {p.source}
          {p.synthetic && <Badge tone="warning">Fictional</Badge>}
        </span>
        <span>
          <CalendarDays size={16} />
          Admitted {formatTime(p.admittedAt)}
        </span>
        <span>
          <Activity size={16} />
          {p.weightKg ? `${p.weightKg} kg` : 'Weight unavailable'}
        </span>
      </div>
      <CreatinineWarning patient={p} hour={currentHour} />
      <nav className="record-navigation" aria-label="Patient record sections">
        {recordSections.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() =>
              document.getElementById(id)?.scrollIntoView({
                behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
                  ? 'instant'
                  : 'smooth',
                block: 'start',
              })
            }
          >
            <Icon size={17} />
            {label}
          </button>
        ))}
      </nav>
      <div id="replay" className="record-anchor" />
      <Panel className="replay-panel">
        <div className="replay-heading">
          <div>
            <Clock3 size={21} />
            <h2>Historical ICU replay</h2>
            <Badge tone="teal">Hour {currentHour}</Badge>
          </div>
          <span>
            <Clock3 size={14} />
            {formatTime(at)}
          </span>
        </div>
        <div className="replay-controls">
          <Button
            variant="secondary"
            aria-label={playing ? 'Pause replay' : 'Play replay'}
            onClick={() => {
              if (currentHour >= p.durationHours) setHour(0);
              setPlaying(!playing);
            }}
          >
            {playing ? <Pause size={17} /> : <Play size={17} />}
          </Button>
          <div className="slider-wrap">
            <input
              aria-label="Selected ICU hour"
              type="range"
              min={0}
              max={p.durationHours}
              step={1}
              value={currentHour}
              onChange={(e) => {
                setPlaying(false);
                setHour(Number(e.target.value));
              }}
            />
            <div className="slider-labels">
              <span>Admission · 0h</span>
              <span>12h</span>
              <span>24h</span>
              <span>48h</span>
              <span>{p.durationHours}h</span>
            </div>
          </div>
          <div className="replay-hour-input">
            <input
              aria-label="Enter ICU hour"
              type="number"
              min={0}
              max={p.durationHours}
              value={currentHour}
              onChange={(e) => {
                setPlaying(false);
                setHour(Math.max(0, Math.min(p.durationHours, Number(e.target.value))));
              }}
            />
            <span>hours</span>
          </div>
        </div>
        <div className="replay-caption">
          <span>Only observations available by this time enter the research view.</span>
          <span>
            Latest measurement: <strong>{formatTime(s.latestAt)}</strong>
          </span>
        </div>
      </Panel>
      <RecognitionAndPrediction patient={p} hour={currentHour} />
      <div id="trends" className="patient-core-stats record-anchor">
        {(['creatinine', 'bun', 'urineOutput', 'map'] as MeasurementKey[]).map((key) => {
          const r = latest(s.readings, key);
          const stale = r && Date.parse(at) - Date.parse(r.at) > 12 * HOUR;
          return (
            <Panel key={key} className={`measurement-stat measurement-${key}`}>
              <span>
                {key === 'map' ? (
                  <HeartPulse size={18} />
                ) : key === 'urineOutput' ? (
                  <Droplets size={18} />
                ) : (
                  <FlaskConical size={18} />
                )}
                {labels[key]}
              </span>
              <div>
                <strong>
                  {r ? r.value.toFixed(key === 'creatinine' || key === 'urineOutput' ? 2 : 0) : '—'}
                </strong>
                <small>{units[key]}</small>
              </div>
              <p>
                {!r ? 'No recorded measurement' : stale ? 'Stale · more than 12 hours old' : formatTime(r.at)}
              </p>
            </Panel>
          );
        })}
      </div>
      <div id="serum-creatinine" className="clinical-feature-graphs record-anchor">
        <CreatininePanel patient={p} hour={currentHour} />
        <MortalityPanel patients={data?.patients ?? []} hour={currentHour} />
      </div>
      <div className="detail-chart-grid">
        <Panel>
          <PanelHead
            title="24-hour AKI risk over time"
            icon={ScanLine}
            subtitle={
              p.synthetic
                ? 'Illustrative probabilities · no trained model'
                : 'Eligible, backend-supplied forecasts only'
            }
          />
          <RiskChart patient={p} hour={currentHour} />
        </Panel>
        <Panel>
          <PanelHead
            title="BUN & urine-output observations"
            icon={Droplets}
            subtitle="Separate units; select a measurement to inspect its trend"
            action={
              <select
                aria-label="Select BUN or urine output"
                value={secondary}
                onChange={(e) => setSecondary(e.target.value as MeasurementKey)}
              >
                <option value="bun">BUN</option>
                <option value="urineOutput">Urine output</option>
              </select>
            }
          />
          <MeasurementChart patient={p} hour={currentHour} measurement={secondary} />
        </Panel>
        <Panel className="vitals-panel">
          <PanelHead
            title="Vitals & laboratory trends"
            icon={HeartPulse}
            subtitle="Timestamps reflect individual observations"
            action={
              <select
                aria-label="Select vital or laboratory measurement"
                value={measure}
                onChange={(e) => setMeasure(e.target.value as MeasurementKey)}
              >
                {measurementKeys
                  .filter((k) => !['creatinine', 'bun', 'urineOutput'].includes(k))
                  .map((k) => (
                    <option key={k} value={k}>
                      {labels[k]}
                    </option>
                  ))}
              </select>
            }
          />
          <MeasurementChart patient={p} hour={currentHour} measurement={measure} />
        </Panel>
      </div>
      <div id="measurements" className="record-anchor" />
      <Panel>
        <button
          className="expandable-heading"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          <div>
            <h2>Detailed measurements</h2>
            <p>Latest value, collection time and availability at ICU hour {currentHour}</p>
          </div>
          <span>
            {s.completeness}% complete {expanded ? <ChevronDown size={19} /> : <ChevronRight size={19} />}
          </span>
        </button>
        {expanded && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>MEASUREMENT</th>
                  <th>VALUE</th>
                  <th>MEASURED AT</th>
                  <th>AVAILABLE AT</th>
                  <th>FRESHNESS</th>
                </tr>
              </thead>
              <tbody>
                {measurementKeys.map((k) => {
                  const r = latest(s.readings, k);
                  const stale = r && Date.parse(at) - Date.parse(r.at) > 12 * HOUR;
                  return (
                    <tr key={k}>
                      <td>
                        <strong>{labels[k]}</strong>
                      </td>
                      <td>{r ? `${r.value} ${units[k]}` : '—'}</td>
                      <td>{formatTime(r?.at)}</td>
                      <td>{formatTime(r?.availableAt)}</td>
                      <td>
                        <Badge tone={!r ? 'neutral' : stale ? 'warning' : 'teal'}>
                          {!r ? 'Missing' : stale ? 'Stale > 12h' : 'Recent'}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <div id="history" className="dashboard-bottom record-anchor">
        <Panel>
          <PanelHead
            title="Model contributions"
            subtitle="Explanation method is shown only when supplied by the model"
          />
          {s.forecast?.contributions?.length ? (
            <div className="contribution-list">
              {s.forecast.contributions.map((c) => (
                <div key={c.feature}>
                  <span>{c.feature}</span>
                  <b>{c.value.toFixed(3)}</b>
                  <small>{c.method}</small>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="Contributions unavailable"
              description="No model explanations were provided for this replay time."
            />
          )}
        </Panel>
        <Panel>
          <PanelHead title="Patient alert history" subtitle="Observations available by the selected hour" />
          {patientAlerts.length ? (
            <div className="patient-alert-list">
              {patientAlerts.map((a) => (
                <div key={a.id}>
                  <TriangleAlert size={16} />
                  <section>
                    <strong>{a.title}</strong>
                    <small>{formatTime(a.at)}</small>
                    <p>{a.detail}</p>
                  </section>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No alerts at this time"
              description="There are no available alerts for the selected replay point."
            />
          )}
        </Panel>
      </div>
      <DataEntry open={entry} onOpenChange={setEntry} patient={p} />
    </>
  );
}

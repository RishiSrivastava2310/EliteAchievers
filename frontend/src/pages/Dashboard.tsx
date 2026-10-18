import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Clock3, Activity, TriangleAlert, ClipboardCheck, ArrowUpRight } from 'lucide-react';
import { useStore } from '../lib/store';
import { snapshot, formatTime } from '../lib/clinical';
import { PatientTable } from '../components/PatientTable';
import { CohortChart, RiskDonut } from '../components/charts';
import { Panel, PanelHead, Button, Modal, ArrowLink, Empty } from '../components/ui';
import { MortalityPanel } from '../components/MortalityPanel';
import { replayEndHour } from '../lib/outcomes';

export function Dashboard() {
  const { session, data, hour, setHour, threshold, alerts, mode } = useStore();
  const navigate = useNavigate();
  const [source, setSource] = useState('All sources');
  const [risk, setRisk] = useState('All risks');
  const [status, setStatus] = useState('All statuses');
  const [help, setHelp] = useState(false);
  const stays = (data?.patients || [])
    .map((p) => snapshot(p, hour, threshold))
    .filter(
      (s) =>
        (source === 'All sources' || s.patient.source === source) &&
        (risk === 'All risks' || s.risk === risk) &&
        (status === 'All statuses' || s.recognition.status === status),
    );
  const elevated = stays.filter((s) => s.risk === 'High').length;
  const observed = stays.filter((s) => s.recognition.stage > 0).length;
  const completeness = stays.length
    ? Math.round(stays.reduce((sum, s) => sum + s.completeness, 0) / stays.length)
    : null;
  const latest = stays
    .flatMap((s) => (s.latestAt ? [s.latestAt] : []))
    .sort()
    .at(-1);
  const name = session!.user.name.startsWith('Dr.')
    ? 'Dr. ' + session!.user.name.split(' ')[1]
    : session!.user.name.split(' ')[0];
  const lastHour = replayEndHour(data?.patients ?? []);
  const hours = [
    ...new Set([...Array.from({ length: Math.floor(lastHour / 6) + 1 }, (_, i) => i * 6), lastHour, hour]),
  ].sort((a, b) => a - b);
  const counts = [
    { name: 'Low risk', value: stays.filter((s) => s.risk === 'Low').length, color: '#40c1b2' },
    { name: 'Moderate risk', value: stays.filter((s) => s.risk === 'Moderate').length, color: '#267da3' },
    { name: 'High risk', value: elevated, color: '#173b50' },
    { name: 'Unavailable', value: stays.filter((s) => s.risk === 'Unavailable').length, color: '#e7edef' },
  ];
  return (
    <>
      <section className="overview-hero" aria-labelledby="overview-title">
        <div className="hero-content">
          <p className="hero-greeting">Welcome back, {name}.</p>
          <h1 id="overview-title">ICU overview</h1>
          <p className="hero-description">
            Review patient histories, renal trends
            <br className="desktop-break" /> and research signals in one place.
          </p>
          <div className="hero-actions">
            <Button onClick={() => navigate('/patients')}>
              View patients
              <ArrowRight size={16} />
            </Button>
            <button className="hero-help" onClick={() => setHelp(true)}>
              How it works
              <ArrowUpRight size={15} />
            </button>
          </div>
        </div>
        <div className="replay-glass">
          <div className="glass-label">
            <Clock3 size={16} />
            Historical replay
          </div>
          <div className="glass-hour">
            <span>ICU hour</span>
            <strong>{hour}</strong>
          </div>
          <label htmlFor="overview-hour" className="glass-select-label">
            Selected observation time
          </label>
          <select
            id="overview-hour"
            aria-label="Replay time"
            value={hour}
            onChange={(e) => setHour(Number(e.target.value))}
          >
            {hours.map((h) => (
              <option key={h} value={h}>
                Hour {h} after admission
              </option>
            ))}
          </select>
          <p>Only observations available by this time are included.</p>
        </div>
      </section>
      <section className="cohort-summary" aria-label="Cohort summary">
        {[
          { label: 'Patients monitored', value: stays.length, sub: 'Stays in this view', path: '/patients' },
          {
            label: 'Elevated risk',
            value: elevated,
            sub: `${mode === 'synthetic' ? 'Illustrative' : 'Model'} estimates ≥ ${Math.round(threshold * 100)}%`,
            path: '/predictions',
          },
          { label: 'Observed AKI', value: observed, sub: 'Available research criteria', path: '/patients' },
          {
            label: 'Data completeness',
            value: completeness === null ? '—' : `${completeness}%`,
            sub: 'Core measurements · last 12h',
            path: '/quality',
          },
        ].map((item) => (
          <button className="summary-metric" key={item.label} onClick={() => navigate(item.path)}>
            <span>{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
            <small>{item.sub}</small>
          </button>
        ))}
      </section>
      <PatientTable
        compact
        source={source}
        onSource={setSource}
        risk={risk}
        onRisk={setRisk}
        status={status}
        onStatus={setStatus}
      />
      <div className="measurement-caption">
        <span>
          Latest available measurement <strong>{formatTime(latest)}</strong>
        </span>
        <span>
          {mode === 'synthetic' ? 'Synthetic cohort' : 'Connected cohort'} · ICU hour {hour}
        </span>
      </div>
      <div className="section-intro">
        <h2>Cohort trends</h2>
        <p>Available observations across the loaded ICU stays.</p>
      </div>
      <div className="dashboard-charts">
        <Panel>
          <PanelHead
            title="Risk and recognition over time"
            subtitle={`First ${hour} ICU hours · ${mode === 'synthetic' ? 'synthetic observations' : 'backend observations'}`}
          />
          <div className="chart-legend">
            <span>
              <i style={{ background: '#267da3' }} />
              Elevated risk
            </span>
            <span>
              <i style={{ background: '#40c1b2' }} />
              Observed AKI
            </span>
          </div>
          <CohortChart />
        </Panel>
        <Panel>
          <PanelHead
            title="Risk distribution"
            subtitle={
              mode === 'synthetic'
                ? 'Illustrative estimates at the selected time'
                : 'Backend estimates at the selected time'
            }
          />
          <RiskDonut counts={counts} />
        </Panel>
      </div>
      <div className="overview-outcomes">
        <MortalityPanel
          patients={(data?.patients ?? []).filter((p) => source === 'All sources' || p.source === source)}
          hour={hour}
          cohortLabel={source === 'All sources' ? 'Loaded cohort' : source}
        />
      </div>
      <div className="dashboard-bottom">
        <Panel>
          <PanelHead
            title="Recent alerts"
            subtitle="Available at the selected replay time"
            action={<ArrowLink onClick={() => navigate('/alerts')}>View all</ArrowLink>}
          />
          {alerts.length ? (
            <div className="recent-alerts">
              {alerts.slice(0, 3).map((a) => (
                <button key={a.id} onClick={() => navigate(`/patients/${a.patientId}`)}>
                  <span className="alert-symbol">
                    {a.severity === 'critical' ? (
                      <Activity size={19} />
                    ) : a.severity === 'warning' ? (
                      <TriangleAlert size={19} />
                    ) : (
                      <ClipboardCheck size={19} />
                    )}
                  </span>
                  <div>
                    <strong>{a.title}</strong>
                    <p>
                      {a.patientId} · {formatTime(a.at)}
                    </p>
                  </div>
                  <ArrowUpRight size={16} />
                </button>
              ))}
            </div>
          ) : (
            <Empty
              title="No alerts at this time"
              description="No research alerts are available for the selected replay hour."
            />
          )}
        </Panel>
        <Panel className="workspace-status">
          <PanelHead title="Data & model status" />
          <dl>
            <div>
              <dt>Data source</dt>
              <dd>{mode === 'synthetic' ? 'Fictional ICU histories' : 'Connected backend'}</dd>
            </div>
            <div>
              <dt>Research model</dt>
              <dd>{data?.model.state === 'ready' ? data.model.version || 'Connected' : 'Not connected'}</dd>
            </div>
            <div>
              <dt>Forecast horizon</dt>
              <dd>Next 24 hours</dd>
            </div>
          </dl>
          <p>A forecast horizon does not guarantee the same amount of advance warning.</p>
          <ArrowLink onClick={() => navigate('/settings')}>Workspace settings</ArrowLink>
        </Panel>
      </div>
      <Modal
        open={help}
        onOpenChange={setHelp}
        title="Using AKI NATOR"
        description="Start with a patient, then choose an ICU hour."
      >
        <div className="explanation-list">
          <p>
            <b>Historical replay.</b> The workspace uses collection and availability timestamps to keep future
            observations out of the selected-time view.
          </p>
          <p>
            <b>Prediction.</b> A future model estimates new creatinine-defined AKI within the next 24 hours.
            Already observed AKI, dialysis exclusions and insufficient data prevent a new-onset forecast.
          </p>
          <p>
            <b>Recognition.</b> Available creatinine changes and complete urine-output intervals are checked
            separately from prediction.
          </p>
          <p>
            <b>This workspace.</b> {data?.provenance}
          </p>
        </div>
        <Button onClick={() => setHelp(false)}>Got it</Button>
      </Modal>
    </>
  );
}

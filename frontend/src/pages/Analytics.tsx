import { useState } from 'react';
import {
  ChartNoAxesCombined,
  Database,
  ShieldCheck,
  ArrowRight,
  ArrowUpRight,
  FileClock,
  FlaskConical,
} from 'lucide-react';
import { useStore } from '../lib/store';
import { PageTitle, Panel, PanelHead, Empty, Badge, Notice, Disclosure } from '../components/ui';
import { EvaluationChart } from '../components/charts';
export function Analytics() {
  const { data, mode } = useStore();
  const [selected, setSelected] = useState('');
  const evaluation = data?.evaluations.find((e) => e.id === selected) || data?.evaluations[0];
  return (
    <>
      <PageTitle
        eyebrow="MODEL RESEARCH"
        title="Model analytics"
        icon={ChartNoAxesCombined}
        description="Evaluate model performance, calibration and the cost of alerts."
        actions={
          <Badge tone={data?.model.state === 'ready' ? 'teal' : 'neutral'}>
            {data?.model.state === 'ready' ? `Model ${data.model.version}` : 'No trained model connected'}
          </Badge>
        }
      />
      <Notice>{data?.model.description}</Notice>
      {evaluation && (
        <div className="evaluation-picker">
          <label>
            Evaluation run
            <select
              aria-label="Evaluation run"
              value={evaluation.id}
              onChange={(e) => setSelected(e.target.value)}
            >
              {data?.evaluations.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </select>
          </label>
          <span>
            {evaluation.trainSource} → {evaluation.testSource} · n = {evaluation.cohortSize}
          </span>
        </div>
      )}
      <div className="stats-grid">
        {['AUROC', 'AUPRC', 'Brier score', 'Evaluation cohort'].map((name, i) => {
          const m = evaluation?.metrics.find((m) => m.name.toLowerCase() === name.toLowerCase());
          return (
            <Panel className="metric-card" key={name}>
              <div>
                <span>{name}</span>
                {i === 3 ? <Database size={18} /> : <ChartNoAxesCombined size={18} />}
              </div>
              <strong>{i === 3 ? (evaluation?.cohortSize ?? '—') : (m?.value.toFixed(3) ?? '—')}</strong>
              <p>
                {m?.lower !== undefined
                  ? `95% CI ${m.lower.toFixed(3)}–${m.upper?.toFixed(3)}`
                  : 'No evaluation result available'}
              </p>
            </Panel>
          );
        })}
      </div>
      <div className="analytics-charts">
        {[
          {
            title: 'ROC curve',
            subtitle: 'True-positive rate vs false-positive rate',
            points: evaluation?.roc,
          },
          {
            title: 'Precision–recall curve',
            subtitle: 'Precision vs recall',
            points: evaluation?.precisionRecall,
          },
          {
            title: 'Calibration',
            subtitle: 'Observed frequency vs predicted probability',
            points: evaluation?.calibration,
          },
        ].map((c) => (
          <Panel key={c.title}>
            <PanelHead title={c.title} subtitle={c.subtitle} />
            {c.points?.length ? (
              <EvaluationChart points={c.points} name={c.title} />
            ) : (
              <Empty
                title="Awaiting evaluation results"
                description="This plot will appear when the backend supplies the corresponding curve."
              />
            )}
          </Panel>
        ))}
      </div>
      <div className="dashboard-bottom">
        <Panel>
          <PanelHead
            title="Alert burden & observed lead time"
            subtitle="Operating characteristics at a documented alert threshold"
          />
          <div className="evaluation-stat">
            <span>False alerts per patient-day</span>
            <strong>{evaluation?.falseAlertsPerPatientDay ?? 'Unavailable'}</strong>
          </div>
          <div className="evaluation-stat">
            <span>Median observed lead time</span>
            <strong>
              {evaluation?.medianLeadTimeHours !== undefined
                ? `${evaluation.medianLeadTimeHours} hours`
                : 'Unavailable'}
            </strong>
          </div>
          <div className="panel-padding">
            <Notice>
              Lead time must be measured relative to actual onset. A 24-hour forecast horizon is not an
              observed lead-time result.
            </Notice>
          </div>
        </Panel>
        <Panel className="research-note">
          <div className="research-note-icon">
            <FlaskConical size={24} />
          </div>
          <h2>Evaluation status</h2>
          <p>
            {mode === 'synthetic'
              ? 'Synthetic data demonstrates the monitoring interface. It cannot establish model accuracy, calibration or hospital transportability.'
              : 'Confirm patient-level separation, temporal splits and cohort definitions for every evaluation run.'}
          </p>
        </Panel>
      </div>
      <Panel>
        <PanelHead
          title="Model feature contributions"
          subtitle="Evaluation-level explanations, with the method supplied by the backend"
        />
        {evaluation?.contributions?.length ? (
          <div className="contribution-list">
            {evaluation.contributions.map((c) => (
              <div key={c.feature}>
                <span>{c.feature}</span>
                <b>{c.value.toFixed(3)}</b>
                <small>{c.method}</small>
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="No model explanations supplied"
            description="Feature contributions will appear when the backend returns them for this evaluation."
          />
        )}
      </Panel>
      <Disclosure title="Evaluation protocol">
        <div className="protocol-grid">
          <div>
            <ShieldCheck size={20} />
            <h3>Patient & temporal separation</h3>
            <p>Patient-level internal splits and a held-out temporal cohort prevent leakage.</p>
          </div>
          <div>
            <FileClock size={20} />
            <h3>Time-aligned features</h3>
            <p>All feature windows end at the prediction time; missingness remains explicit.</p>
          </div>
          <div>
            <ChartNoAxesCombined size={20} />
            <h3>Subgroup evaluation</h3>
            <p>Compare age, recorded sex, baseline kidney function and ICU type when supplied.</p>
          </div>
        </div>
      </Disclosure>
    </>
  );
}
export function Validation() {
  const { data, mode } = useStore();
  return (
    <>
      <PageTitle
        eyebrow="CROSS-HOSPITAL VALIDATION"
        title="Cross-hospital validation"
        icon={ShieldCheck}
        description="Test how well a model transfers from one hospital dataset to another."
      />
      <div className="validation-flow">
        <div>
          <span className="source-tag">MIMIC-IV</span>
          <h2>Source cohort</h2>
          <p>Patient-level and temporal internal validation</p>
        </div>
        <div className="flow-arrow">
          <ArrowRight size={24} />
          <small>External evaluation</small>
        </div>
        <div>
          <span className="source-tag source-blue">eICU-CRD</span>
          <h2>Target cohort</h2>
          <p>Cross-dataset and leave-hospital-out evaluation</p>
        </div>
      </div>
      <Notice>
        {mode === 'synthetic'
          ? 'The loaded synthetic source scenarios are not validation cohorts. No cross-hospital performance has been measured.'
          : 'Cross-hospital results reflect only evaluation runs returned by the backend.'}
      </Notice>
      <Panel>
        <PanelHead
          title="Transportability matrix"
          subtitle="Train / test direction and corresponding held-out results"
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>TRAIN DATASET</th>
                <th>TEST DATASET</th>
                <th>AUROC</th>
                <th>AUPRC</th>
                <th>TEST COHORT</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['MIMIC-IV', 'MIMIC-IV'],
                ['MIMIC-IV', 'eICU-CRD'],
                ['eICU-CRD', 'MIMIC-IV'],
                ['eICU-CRD', 'eICU-CRD'],
              ].map(([train, test]) => {
                const e = data?.evaluations.find((e) => e.trainSource === train && e.testSource === test);
                return (
                  <tr key={train + test}>
                    <td>
                      <strong>{train}</strong>
                    </td>
                    <td>{test}</td>
                    <td>
                      {e?.metrics.find((m) => m.name.toUpperCase() === 'AUROC')?.value.toFixed(3) ?? '—'}
                    </td>
                    <td>
                      {e?.metrics.find((m) => m.name.toUpperCase() === 'AUPRC')?.value.toFixed(3) ?? '—'}
                    </td>
                    <td>{e?.cohortSize ?? 'Unavailable'}</td>
                    <td>
                      <Badge tone={e ? 'teal' : 'neutral'}>{e ? 'Result available' : 'Not evaluated'}</Badge>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="analytics-charts">
        {[
          {
            title: 'Calibration under shift',
            description:
              'Target-site reliability plots, Brier scores and recalibration require held-out evaluation results.',
          },
          {
            title: 'Missing-data robustness',
            description: 'Feature-group removal experiments quantify sensitivity to measurement practices.',
          },
          {
            title: 'Leave-hospital-out',
            description:
              'Hospital-level holdouts within eICU-CRD require hospital identifiers and frozen evaluation cohorts.',
          },
        ].map((c) => (
          <Panel key={c.title}>
            <PanelHead title={c.title} />
            <Empty title="No results supplied" description={c.description} />
          </Panel>
        ))}
      </div>
      <Disclosure title="Dataset scope & access">
        <p>
          MIMIC-IV and eICU-CRD form the adult research scope. SafeICU is excluded from this frontend because
          adult-trained models and creatinine reference values must not be assumed to transfer to pediatric
          populations.
        </p>
        <a
          className="text-link"
          href="https://physionet.org/content/mimiciv/"
          target="_blank"
          rel="noreferrer"
        >
          Dataset access is managed by PhysioNet
          <ArrowUpRight size={15} />
        </a>
      </Disclosure>
    </>
  );
}

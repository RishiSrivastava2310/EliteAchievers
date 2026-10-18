import { useState } from 'react';
import { HeartPulse, ClipboardPlus } from 'lucide-react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import type { Patient } from '../lib/types';
import { atHour, formatTime } from '../lib/clinical';
import { fatalityAt, fatalitySeries } from '../lib/outcomes';
import { useStore } from '../lib/store';
import { Panel, PanelHead, Badge, Button, Empty, Disclosure } from './ui';
import { OutcomeEntry } from './OutcomeEntry';

export function MortalityPanel({
  patients,
  hour,
  cohortLabel = 'Loaded cohort',
}: {
  patients: Patient[];
  hour: number;
  cohortLabel?: string;
}) {
  const { mode } = useStore();
  const [entry, setEntry] = useState(false);
  const current = fatalityAt(patients, hour);
  const rows = fatalitySeries(patients, hour);
  const fictional = patients.length > 0 && patients.every((p) => p.synthetic);
  const known = patients.filter(
    (p) => p.outcome && p.outcome.at <= atHour(p, hour) && p.outcome.availableAt <= atHour(p, hour),
  );
  return (
    <>
      <Panel className="mortality-panel">
        <PanelHead
          title="Recorded ICU fatality rate"
          subtitle={`${cohortLabel} · deaths / completed stays with known outcomes`}
          icon={HeartPulse}
          action={
            mode === 'synthetic' ? (
              <Button variant="secondary" onClick={() => setEntry(true)} disabled={!patients.length}>
                <ClipboardPlus size={15} />
                Record outcomes
              </Button>
            ) : (
              <Badge tone="neutral">Recorded outcomes</Badge>
            )
          }
        />
        <div className="mortality-summary">
          <div className="mortality-value" aria-live="polite">
            <strong>
              {current.rate === null ? 'Unavailable' : current.rate.toFixed(1)}
              {current.rate !== null && <span>%</span>}
            </strong>
            <p>
              {current.known} of {patients.length} stays have an available completed outcome
            </p>
          </div>
          <Badge tone={fictional ? 'warning' : 'neutral'}>
            {fictional
              ? 'Fictional outcomes'
              : patients.some((p) => p.synthetic)
                ? 'Mixed provenance'
                : 'Recorded data'}
          </Badge>
        </div>
        <div className="outcome-counts">
          <div className="outcome-deaths">
            <span>Recorded deaths</span>
            <strong>{current.deaths}</strong>
          </div>
          <div className="outcome-alive">
            <span>Discharged alive</span>
            <strong>{current.alive}</strong>
          </div>
          <div>
            <span>Awaiting / unknown</span>
            <strong>{current.awaiting}</strong>
          </div>
        </div>
        <div className="outcome-clock">
          <span>Admission-aligned ICU hours</span>
          <strong>Selected hour {hour}</strong>
        </div>
        {current.rate === null ? (
          <Empty
            title="No available completed outcomes"
            description="The rate appears after timestamped deaths or live discharges become available. Missing outcomes are excluded from the denominator."
          />
        ) : (
          <div
            className="chart mortality-chart"
            role="img"
            aria-label={`Recorded fatality rate ${current.rate.toFixed(1)} percent, based on ${current.deaths} deaths among ${current.known} known ICU outcomes at hour ${hour}`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 18, left: -10, right: 25, bottom: 0 }}>
                <CartesianGrid stroke="#e8edeb" vertical={false} />
                <XAxis
                  dataKey="hour"
                  type="number"
                  domain={[0, Math.max(24, hour)]}
                  tick={{ fontSize: 13, fill: '#6e7b80' }}
                  tickFormatter={(h) => `${h}h`}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  tick={{ fontSize: 13, fill: '#6e7b80' }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{ borderRadius: 10, fontSize: 13 }}
                  labelFormatter={(h) => `ICU hour ${h}`}
                  formatter={(v) => [`${Number(v).toFixed(1)}%`, 'Recorded fatality rate']}
                />
                <Line
                  name="Recorded fatality rate"
                  dataKey="rate"
                  type="stepAfter"
                  stroke="#bb6753"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: '#fff', strokeWidth: 2 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="serum-method">
          <Disclosure title="Outcome records & calculation">
            <p>
              Recorded ICU deaths divided by completed ICU stays with known outcomes, as available by the
              selected hour. Stays with missing outcomes or ongoing follow-up are excluded. This descriptive
              cohort rate is not an individual mortality prediction or an AKI-attributable death rate.
            </p>
            <p>
              The step graph changes at outcome availability times. Limited follow-up and incomplete outcome
              reporting can bias the displayed rate.{' '}
              {fictional && 'All outcomes here are fictional interface examples, not clinical statistics.'}
            </p>
            {known.length > 0 && (
              <div className="available-outcomes">
                {known.map((p) => (
                  <div key={p.id}>
                    <strong>{p.id}</strong>
                    <Badge tone={p.outcome!.status === 'died' ? 'danger' : 'teal'}>
                      {p.outcome!.status === 'died' ? 'Died in ICU' : 'Discharged alive'}
                    </Badge>
                    <span>{formatTime(p.outcome!.at)}</span>
                    <small>Available {formatTime(p.outcome!.availableAt)}</small>
                  </div>
                ))}
              </div>
            )}
          </Disclosure>
        </div>
      </Panel>
      <OutcomeEntry open={entry} onOpenChange={setEntry} />
    </>
  );
}

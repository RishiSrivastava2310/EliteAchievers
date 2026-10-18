import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, TriangleAlert, Info, Check, ArrowUpRight, CheckCheck } from 'lucide-react';
import { useStore } from '../lib/store';
import { formatTime } from '../lib/clinical';
import { PageTitle, Panel, Badge, Button, Empty } from '../components/ui';
export function Alerts() {
  const { alerts, acknowledged, acknowledge, hour, toast } = useStore();
  const [filter, setFilter] = useState('all');
  const [severity, setSeverity] = useState('all');
  const navigate = useNavigate();
  const filtered = alerts.filter(
    (a) =>
      (filter === 'all' || (filter === 'reviewed') === acknowledged.includes(a.id)) &&
      (severity === 'all' || a.severity === severity),
  );
  return (
    <>
      <PageTitle
        eyebrow="RESEARCH ALERTS"
        title="Alerts"
        icon={TriangleAlert}
        description={`Alerts from available observations and forecasts at ICU hour ${hour}. Review status is saved in this browser.`}
        actions={
          <Button
            variant="secondary"
            disabled={!alerts.some((a) => !acknowledged.includes(a.id))}
            onClick={() => {
              alerts.forEach((a) => acknowledge(a.id));
              toast('All currently available alerts marked reviewed.');
            }}
          >
            <CheckCheck size={16} />
            Mark all reviewed
          </Button>
        }
      />
      <div className="alert-summary">
        {[
          {
            name: 'Observed AKI',
            count: alerts.filter((a) => a.severity === 'critical').length,
            icon: Activity,
            tone: 'red',
          },
          {
            name: 'Elevated-risk signals',
            count: alerts.filter((a) => a.severity === 'warning').length,
            icon: TriangleAlert,
            tone: 'orange',
          },
          {
            name: 'Data quality signals',
            count: alerts.filter((a) => a.severity === 'info').length,
            icon: Info,
            tone: 'blue',
          },
        ].map((s) => (
          <div key={s.name} className={`stat-card stat-${s.tone}`}>
            <s.icon size={22} />
            <strong>{s.count}</strong>
            <span>{s.name}</span>
          </div>
        ))}
      </div>
      <Panel>
        <div className="alerts-toolbar">
          <div className="segmented">
            {['all', 'unreviewed', 'reviewed'].map((v) => (
              <button
                key={v}
                aria-pressed={filter === v}
                className={filter === v ? 'selected' : ''}
                onClick={() => setFilter(v)}
              >
                {v[0].toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>
          <select
            aria-label="Filter alert type"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            <option value="all">All alert types</option>
            <option value="critical">Observed AKI</option>
            <option value="warning">Elevated risk</option>
            <option value="info">Data quality</option>
          </select>
        </div>
        {filtered.length ? (
          <div className="alert-feed">
            {filtered.map((a) => (
              <article
                key={a.id}
                className={`${a.severity} ${acknowledged.includes(a.id) ? 'reviewed' : ''}`}
              >
                <span className={`alert-symbol ${a.severity}`}>
                  {a.severity === 'critical' ? (
                    <Activity size={21} />
                  ) : a.severity === 'warning' ? (
                    <TriangleAlert size={21} />
                  ) : (
                    <Info size={21} />
                  )}
                </span>
                <div>
                  <div className="alert-title">
                    <h3>{a.title}</h3>
                    {a.synthetic && <Badge tone="neutral">Synthetic</Badge>}
                  </div>
                  <p>{a.detail}</p>
                  <small>
                    {a.patientId} · {formatTime(a.at)}
                  </small>
                </div>
                <div className="alert-actions">
                  <Button variant="ghost" onClick={() => navigate(`/patients/${a.patientId}`)}>
                    View stay
                    <ArrowUpRight size={15} />
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={acknowledged.includes(a.id)}
                    onClick={() => {
                      acknowledge(a.id);
                      toast('Alert marked reviewed.');
                    }}
                  >
                    <Check size={15} />
                    {acknowledged.includes(a.id) ? 'Reviewed' : 'Mark reviewed'}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="No alerts in this view"
            description="Adjust the filters or change the replay time to see available alerts."
          />
        )}
      </Panel>
    </>
  );
}

import { Download, Database, Clock3, ClipboardCheck, CircleDashed } from 'lucide-react';
import { useStore } from '../lib/store';
import { snapshot, latest, atHour, labels, HOUR } from '../lib/clinical';
import { measurementKeys } from '../lib/types';
import { downloadFile } from '../lib/csv';
import { PageTitle, Panel, PanelHead, Badge, Button, Progress, Disclosure } from '../components/ui';
export function DataQuality() {
  const { data, hour, threshold, mode } = useStore();
  const snaps = (data?.patients || []).map((p) => snapshot(p, hour, threshold));
  const metrics = measurementKeys.map((key) => {
    let recent = 0,
      stale = 0,
      missing = 0;
    for (const s of snaps) {
      const r = latest(s.readings, key);
      if (!r) missing++;
      else if (Date.parse(atHour(s.patient, hour)) - Date.parse(r.at) > 12 * HOUR) stale++;
      else recent++;
    }
    return {
      key,
      recent,
      stale,
      missing,
      coverage: snaps.length ? Math.round((recent / snaps.length) * 100) : 0,
    };
  });
  const total = snaps.length * measurementKeys.length;
  const recent = metrics.reduce((s, m) => s + m.recent, 0),
    stale = metrics.reduce((s, m) => s + m.stale, 0),
    missing = metrics.reduce((s, m) => s + m.missing, 0);
  return (
    <>
      <PageTitle
        eyebrow="DATA QUALITY"
        title="Data quality"
        icon={ClipboardCheck}
        description={`Measurement availability at ICU hour ${hour}, without backfilling from later observations.`}
        actions={
          <Button
            variant="secondary"
            onClick={() =>
              downloadFile(
                'aki-nator-data-quality.csv',
                'measurement,recent,stale,missing,recent_coverage_percent\n' +
                  metrics.map((m) => [m.key, m.recent, m.stale, m.missing, m.coverage].join(',')).join('\n'),
              )
            }
          >
            <Download size={15} />
            Export report
          </Button>
        }
      />
      <div className="stats-grid quality-stats">
        {[
          {
            name: 'Measurement slots',
            value: total,
            icon: Database,
            note: 'Loaded stays × 9 core types',
            tone: 'neutral',
          },
          {
            name: 'Recently measured',
            value: recent,
            icon: ClipboardCheck,
            note: 'Recorded within the last 12 hours',
            tone: 'teal',
          },
          {
            name: 'Stale measurements',
            value: stale,
            icon: Clock3,
            note: 'Latest measurement older than 12h',
            tone: 'amber',
          },
          {
            name: 'Missing measurements',
            value: missing,
            icon: CircleDashed,
            note: 'No available observation at this time',
            tone: 'coral',
          },
        ].map((c) => (
          <Panel className={`metric-card metric-${c.tone}`} key={c.name}>
            <div>
              <span>{c.name}</span>
              <c.icon size={18} />
            </div>
            <strong>{c.value}</strong>
            <p>{c.note}</p>
          </Panel>
        ))}
      </div>
      {total > 0 && (
        <section className="availability-summary" aria-label="Overall measurement availability">
          <div className="availability-labels">
            <h2>Availability at a glance</h2>
            <div>
              <span className="legend-recent">Recent {Math.round((recent / total) * 100)}%</span>
              <span className="legend-stale">Stale {Math.round((stale / total) * 100)}%</span>
              <span className="legend-missing">Missing {Math.round((missing / total) * 100)}%</span>
            </div>
          </div>
          <div
            className="availability-bar"
            role="img"
            aria-label={`${recent} recent, ${stale} stale and ${missing} missing measurement slots`}
          >
            <span className="availability-recent" style={{ width: `${(recent / total) * 100}%` }} />
            <span className="availability-stale" style={{ width: `${(stale / total) * 100}%` }} />
            <span className="availability-missing" style={{ width: `${(missing / total) * 100}%` }} />
          </div>
        </section>
      )}
      <Panel>
        <PanelHead
          title="Core measurement availability"
          subtitle="One latest available value per ICU stay and measurement type"
          action={
            <Badge tone="neutral">
              {snaps.length} {mode === 'synthetic' ? 'fictional' : 'loaded'} stays
            </Badge>
          }
        />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>MEASUREMENT TYPE</th>
                <th>RECENT ≤ 12H</th>
                <th>STALE &gt; 12H</th>
                <th>MISSING</th>
                <th>RECENT COVERAGE</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.key}>
                  <td>
                    <strong>{labels[m.key]}</strong>
                  </td>
                  <td>
                    <span className="quality-number">{m.recent}</span>
                  </td>
                  <td>
                    <span className={m.stale ? 'quality-stale' : ''}>{m.stale}</span>
                  </td>
                  <td>
                    <span className={m.missing ? 'quality-missing' : ''}>{m.missing}</span>
                  </td>
                  <td>
                    <div className="completeness-cell">
                      <Progress value={m.coverage} />
                      <b>{m.coverage}%</b>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="quality-sources">
        <Panel>
          <PanelHead title="Source availability" subtitle="Loaded stays, not evaluation cohort sizes" />
          {['MIMIC-IV', 'eICU-CRD', 'Manual', 'CSV'].map((source) => {
            const cohort = snaps.filter((s) => s.patient.source === source);
            if (!cohort.length) return null;
            const mean = Math.round(cohort.reduce((sum, s) => sum + s.completeness, 0) / cohort.length);
            return (
              <div className="source-quality" key={source}>
                <div>
                  <strong>{source}</strong>
                  <small>
                    {cohort.length} stays{mode === 'synthetic' ? ' · fictional scenarios' : ''}
                  </small>
                </div>
                <Progress value={mean} />
                <b>{mean}%</b>
              </div>
            );
          })}
        </Panel>
      </div>
      <Disclosure title="How measurement completeness is calculated">
        <p>
          The share of nine core measurement types with at least one available observation collected within
          the last 12 hours. This is a display freshness convention, not a validated measure of clinical
          adequacy.
        </p>
        <p>
          Missing or stale observations remain visible. Urine-output recognition additionally requires known
          weight and complete, contiguous collection intervals.
        </p>
        <p>
          Measurement ordering can reflect illness severity. Missingness and sampling frequency must be
          audited during model development to avoid misleading cross-hospital comparisons.
        </p>
      </Disclosure>
    </>
  );
}

import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Search,
  ChevronLeft,
  ChevronRight,
  ArrowUpRight,
  SlidersHorizontal,
  Download,
  ArrowDownUp,
} from 'lucide-react';
import { useStore } from '../lib/store';
import { snapshot, latest, formatTime } from '../lib/clinical';
import { downloadFile } from '../lib/csv';
import { Badge, Button, Empty, Panel, Progress } from './ui';
import type { PatientSnapshot } from '../lib/types';
export function riskTone(s: PatientSnapshot) {
  return s.risk === 'High'
    ? 'danger'
    : s.risk === 'Moderate'
      ? 'warning'
      : s.risk === 'Low'
        ? 'teal'
        : 'neutral';
}
export function PatientTable({
  compact = false,
  source = 'All sources',
  risk = 'All risks',
  status = 'All statuses',
  onSource,
  onRisk,
  onStatus,
}: {
  compact?: boolean;
  source?: string;
  risk?: string;
  status?: string;
  onSource?: (v: string) => void;
  onRisk?: (v: string) => void;
  onStatus?: (v: string) => void;
}) {
  const { data, hour, threshold } = useStore();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get('q') || '');
  const [page, setPage] = useState(0);
  const [sortRisk, setSortRisk] = useState(false);
  const size = compact ? 5 : 8;
  useEffect(() => setSearch(params.get('q') || ''), [params]);
  useEffect(() => setPage(0), [search, source, risk, status, sortRisk]);
  const filtered = (data?.patients || [])
    .map((p) => snapshot(p, hour, threshold))
    .filter(
      (s) =>
        (source === 'All sources' || s.patient.source === source) &&
        (risk === 'All risks' || s.risk === risk) &&
        (status === 'All statuses' || s.recognition.status === status) &&
        `${s.patient.id} ${s.patient.unit} ${s.patient.source}`.toLowerCase().includes(search.toLowerCase()),
    );
  if (sortRisk) filtered.sort((a, b) => (b.probability ?? -1) - (a.probability ?? -1));
  const maxPage = Math.max(0, Math.ceil(filtered.length / size) - 1);
  const currentPage = Math.min(page, maxPage);
  const rows = filtered.slice(currentPage * size, (currentPage + 1) * size);
  function exportRows() {
    downloadFile(
      'aki-nator-monitoring.csv',
      'stay_id,source,selected_icu_hour,aki_status,risk_category,probability,synthetic\n' +
        filtered
          .map((s) =>
            [
              s.patient.id,
              s.patient.source,
              hour,
              s.recognition.status,
              s.risk,
              s.probability ?? '',
              s.patient.synthetic,
            ].join(','),
          )
          .join('\n'),
    );
  }
  return (
    <Panel className="patient-panel">
      <div className="panel-head">
        <div>
          <div className="heading-with-count">
            <h2>{compact ? 'Patient monitoring' : 'All ICU stays'}</h2>
            <span className="count-tag">{filtered.length}</span>
          </div>
          <p>
            {compact
              ? 'Available measurements at the selected ICU hour.'
              : 'De-identified ICU stays and their available history.'}
          </p>
        </div>
        <Button variant="secondary" onClick={exportRows}>
          <Download size={15} />
          <span>Export view</span>
        </Button>
      </div>
      <div className="table-toolbar">
        <div className="table-search">
          <Search size={17} />
          <input
            aria-label="Search patient monitoring"
            placeholder="Search stay ID, unit or source…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="table-filters">
          <SlidersHorizontal size={15} />
          <select aria-label="Filter source" value={source} onChange={(e) => onSource?.(e.target.value)}>
            <option>All sources</option>
            {['MIMIC-IV', 'eICU-CRD', 'Manual', 'CSV'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select aria-label="Filter risk" value={risk} onChange={(e) => onRisk?.(e.target.value)}>
            <option>All risks</option>
            {['High', 'Moderate', 'Low', 'Unavailable'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select aria-label="Filter AKI status" value={status} onChange={(e) => onStatus?.(e.target.value)}>
            <option>All statuses</option>
            {['Observed AKI', 'No AKI observed', 'Insufficient data'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>ICU stay</th>
              <th>Source</th>
              <th>
                <button className="th-sort" onClick={() => setSortRisk(!sortRisk)}>
                  24h risk
                  <ArrowDownUp size={12} />
                </button>
              </th>
              <th>AKI recognition</th>
              <th>Creatinine</th>
              <th>Completeness</th>
              <th aria-label="Open record" />
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const cr = latest(s.readings, 'creatinine');
              return (
                <tr key={s.patient.id}>
                  <td>
                    <button className="patient-id" onClick={() => navigate(`/patients/${s.patient.id}`)}>
                      {s.patient.id}
                    </button>
                    <small>
                      {s.patient.age} years · {s.patient.sex} · {s.patient.unit}
                    </small>
                  </td>
                  <td>
                    <span className={`source-tag ${s.patient.source === 'eICU-CRD' ? 'source-blue' : ''}`}>
                      {s.patient.source}
                    </span>
                    {s.patient.synthetic && <small>Fictional scenario</small>}
                  </td>
                  <td>
                    <div className="risk-cell">
                      <Badge tone={riskTone(s)}>
                        {s.probability === undefined ? '—' : `${Math.round(s.probability * 100)}%`}{' '}
                        {s.probability === undefined ? 'Unavailable' : s.risk}
                      </Badge>
                    </div>
                    {s.forecast?.synthetic && <small>Illustrative estimate</small>}
                  </td>
                  <td>
                    <Badge
                      tone={
                        s.recognition.stage
                          ? 'danger'
                          : s.recognition.status === 'Insufficient data'
                            ? 'neutral'
                            : 'teal'
                      }
                    >
                      {s.recognition.stage
                        ? `Observed · stage ${s.recognition.stage}`
                        : s.recognition.status === 'Insufficient data'
                          ? 'Insufficient data'
                          : 'Not observed'}
                    </Badge>
                  </td>
                  <td>
                    <strong className="lab-value">{cr?.value.toFixed(2) ?? '—'}</strong>
                    <span className="unit-text"> mg/dL</span>
                    <small>{cr ? formatTime(cr.at) : 'Not measured'}</small>
                  </td>
                  <td>
                    <div className="completeness-cell">
                      <Progress value={s.completeness} />
                      <span>{s.completeness}%</span>
                    </div>
                    <small>Core types · last 12h</small>
                  </td>
                  <td>
                    <button
                      className="icon-button row-open"
                      aria-label={`Open ${s.patient.id}`}
                      onClick={() => navigate(`/patients/${s.patient.id}`)}
                    >
                      <ArrowUpRight size={18} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <Empty
          title="No matching ICU stays"
          description="Try another stay ID or adjust the filters."
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setSearch('');
                onSource?.('All sources');
                onRisk?.('All risks');
                onStatus?.('All statuses');
              }}
            >
              Clear filters
            </Button>
          }
        />
      )}
      <div className="table-pagination">
        <span>
          Showing {filtered.length ? currentPage * size + 1 : 0}–
          {Math.min((currentPage + 1) * size, filtered.length)} of {filtered.length} stays
        </span>
        <div>
          <Button
            variant="secondary"
            disabled={currentPage === 0}
            aria-label="Previous page"
            onClick={() => setPage(currentPage - 1)}
          >
            <ChevronLeft size={15} />
          </Button>
          <span>
            Page {currentPage + 1} of {maxPage + 1}
          </span>
          <Button
            variant="secondary"
            disabled={currentPage === maxPage}
            aria-label="Next page"
            onClick={() => setPage(currentPage + 1)}
          >
            <ChevronRight size={15} />
          </Button>
        </div>
      </div>
    </Panel>
  );
}

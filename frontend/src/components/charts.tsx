import { useState } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  ReferenceLine,
  ReferenceDot,
} from 'recharts';
import { useStore } from '../lib/store';
import { atHour, hourOf, snapshot, visibleReadings, formatTime, labels, units } from '../lib/clinical';
import type { Patient, MeasurementKey } from '../lib/types';
import { Empty, Button } from './ui';
import { forecastHistory } from '../lib/forecast-history';
const grid = '#e8edeb';
const tick = { fontSize: 13, fill: '#6e7b80' };
export function CohortChart() {
  const { data, hour, threshold } = useStore();
  const points = Array.from({ length: Math.floor(hour / 6) + 1 }, (_, i) => {
    const h = i * 6;
    const s = (data?.patients || []).map((p) => snapshot(p, h, threshold));
    return {
      hour: h,
      observed: s.filter((v) => v.recognition.stage > 0).length,
      elevated: s.filter((v) => v.risk === 'High').length,
    };
  });
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 15, right: 10, bottom: 0, left: -25 }}>
          <defs>
            <linearGradient id="tealArea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#267da3" stopOpacity={0.1} />
              <stop offset="100%" stopColor="#267da3" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={grid} vertical={false} />
          <XAxis
            dataKey="hour"
            tick={tick}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}h`}
            minTickGap={15}
          />
          <YAxis allowDecimals={false} tick={tick} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ borderRadius: 10, border: '1px solid #e8e8ed', fontSize: 12 }}
            labelFormatter={(v) => `ICU hour ${v}`}
          />
          <Area
            type="stepAfter"
            dataKey="elevated"
            name="Elevated risk"
            stroke="#267da3"
            strokeWidth={2.5}
            fill="url(#tealArea)"
            isAnimationActive={false}
          />
          <Area
            type="stepAfter"
            dataKey="observed"
            name="Observed AKI"
            stroke="#40c1b2"
            strokeWidth={2}
            fill="transparent"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
export function RiskDonut({ counts }: { counts: { name: string; value: number; color: string }[] }) {
  const total = counts.reduce((s, c) => s + c.value, 0);
  if (!total)
    return (
      <Empty title="No stays in this view" description="Change your filters to view the risk distribution." />
    );
  return (
    <div className="donut-wrap">
      <div className="donut-graphic">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={counts.filter((c) => c.value)}
              dataKey="value"
              innerRadius="71%"
              outerRadius="92%"
              paddingAngle={3}
              startAngle={90}
              endAngle={-270}
              stroke="none"
              isAnimationActive={false}
            >
              {counts
                .filter((c) => c.value)
                .map((c) => (
                  <Cell key={c.name} fill={c.color} />
                ))}
            </Pie>
            <Tooltip contentStyle={{ borderRadius: 9, fontSize: 12 }} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-label">
          <strong>{total}</strong>
          <span>ICU stays</span>
        </div>
      </div>
      <div className="donut-legend">
        {counts.map((c) => (
          <div key={c.name}>
            <span>
              <i style={{ background: c.color }} />
              {c.name}
            </span>
            <b>{c.value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}
export function MeasurementChart({
  patient,
  hour,
  measurement,
  retrospective = false,
  stroke,
}: {
  patient: Patient;
  hour: number;
  measurement: MeasurementKey;
  retrospective?: boolean;
  stroke?: string;
}) {
  const at = atHour(patient, hour);
  const visible = visibleReadings(patient, at).filter((r) => r.key === measurement);
  if (!visible.length)
    return (
      <Empty
        title="No measurements available"
        description="No observations for this measurement were available at the selected ICU time."
      />
    );
  const reads = retrospective ? patient.readings.filter((r) => r.key === measurement) : visible;
  const rows = reads.map((r) => ({
    hour: hourOf(patient, r.at),
    at: r.at,
    observed: r.at <= at && r.availableAt <= at ? r.value : null,
    retrospective: r.at > at ? r.value : null,
  }));
  // Insert explicit gaps when observations are more than 12 hours apart.
  for (let i = rows.length - 1; i > 0; i--)
    if (rows[i].hour - rows[i - 1].hour > 12)
      rows.splice(i, 0, {
        hour: rows[i - 1].hour + 0.01,
        at: atHour(patient, rows[i - 1].hour + 0.01),
        observed: null,
        retrospective: null,
      });
  const onset = retrospective ? snapshot(patient, patient.durationHours).recognition.onsetAt : undefined;
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 15, right: 20, bottom: 0, left: -15 }}>
          <CartesianGrid stroke={grid} vertical={false} />
          <XAxis
            type="number"
            dataKey="hour"
            domain={[0, retrospective ? patient.durationHours : Math.max(12, hour)]}
            tick={tick}
            tickFormatter={(v) => `${v}h`}
            axisLine={false}
            tickLine={false}
          />
          <YAxis domain={['auto', 'auto']} tick={tick} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ borderRadius: 10, fontSize: 12 }}
            labelFormatter={(v) => formatTime(atHour(patient, Number(v)))}
          />
          <Line
            name={`${labels[measurement]} (${units[measurement]})`}
            dataKey="observed"
            stroke={
              stroke ??
              (measurement === 'map' ? '#b67961' : measurement === 'urineOutput' ? '#397e9d' : '#398275')
            }
            strokeWidth={2.3}
            dot={{ r: 3, fill: '#fff', strokeWidth: 2 }}
            connectNulls={false}
            isAnimationActive={false}
          />
          {retrospective && (
            <Line
              name="Retrospective observations"
              dataKey="retrospective"
              stroke="#ad7d3d"
              strokeDasharray="5 5"
              dot={{ r: 3 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}
          <ReferenceLine x={hour} stroke="#b1b1b7" strokeDasharray="4 4" />
          {onset && (
            <ReferenceLine
              x={hourOf(patient, onset)}
              stroke="#a66767"
              strokeDasharray="4 4"
              label={{
                value: 'Retrospective AKI',
                fontSize: 12,
                fill: '#9a5656',
                position: 'insideTopRight',
              }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
export function RiskChart({ patient, hour }: { patient: Patient; hour: number }) {
  const { threshold } = useStore();
  const [zoom, setZoom] = useState(false);
  const history = forecastHistory(patient, hour, threshold);
  const { rows, latest: last, firstAlert, min, max, current } = history;
  if (!last || min === null || max === null)
    return (
      <Empty
        title="No eligible forecasts"
        description="Risk estimates appear only when supplied for an eligible prediction time."
      />
    );
  const padding = Math.max(1, (max - min) * 0.15);
  const domain: [number, number] = zoom
    ? [Math.max(0, Math.floor(min - padding)), Math.min(100, Math.ceil(max + padding))]
    : [0, 100];
  const reason =
    current.eligibility ||
    (!current.forecast ? 'No current forecast was supplied, or the latest one is over six hours old.' : null);
  return (
    <div className="risk-history">
      <div className="risk-history-toolbar">
        <div>
          <span>Latest recorded forecast</span>
          <strong className="risk-history-latest">{last.risk.toFixed(2)}%</strong>
          <small>
            ICU hour {last.hour} · {history.points.length} forecast{' '}
            {history.points.length === 1 ? 'update' : 'updates'}
          </small>
        </div>
        <Button
          variant="secondary"
          aria-label="Zoom risk axis"
          aria-pressed={zoom}
          onClick={() => setZoom(!zoom)}
        >
          {zoom ? 'Show 0–100% scale' : 'Zoom to changes'}
        </Button>
      </div>
      {zoom && (
        <p className="risk-axis-note">
          Zoomed Y-axis: {domain[0]}–{domain[1]}%. Alert threshold: {(threshold * 100).toFixed(0)}%.
        </p>
      )}
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows} margin={{ top: 15, left: -18, right: 15 }}>
            <CartesianGrid stroke={grid} vertical={false} />
            <XAxis
              type="number"
              dataKey="hour"
              domain={[0, Math.max(12, hour)]}
              tick={tick}
              tickFormatter={(v) => `${v}h`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={domain}
              allowDataOverflow
              tickFormatter={(v) => `${v}%`}
              tick={tick}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{ borderRadius: 10, fontSize: 13 }}
              labelFormatter={(v) => `ICU hour ${v} · ${formatTime(atHour(patient, Number(v)))}`}
              formatter={(v, _name, entry) => [
                `${Number(v).toFixed(2)}%`,
                entry.payload?.synthetic ? 'Simulated 24-hour forecast' : 'Model 24-hour forecast',
              ]}
            />
            <Area
              type="stepAfter"
              name="24-hour estimate"
              dataKey="risk"
              stroke="#267da3"
              fill="#f0f6ff"
              strokeWidth={2}
              connectNulls={false}
              dot={{ r: 3, fill: '#fff', strokeWidth: 1.8 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
            <ReferenceLine
              y={threshold * 100}
              stroke="#aaaab0"
              strokeDasharray="4 4"
              label={{ value: 'Alert threshold', fontSize: 12, fill: '#86868b', position: 'insideTopLeft' }}
            />
            {firstAlert && (
              <ReferenceDot
                x={firstAlert.hour}
                y={firstAlert.risk}
                r={4}
                fill="#1d1d1f"
                stroke="#fff"
                label={{
                  value: firstAlert.synthetic ? 'Simulated alert' : 'Alert',
                  fontSize: 12,
                  fill: '#6e6e73',
                  position: firstAlert.hour > Math.max(12, hour) * 0.75 ? 'left' : 'top',
                }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="risk-history-context">
        <p>
          {history.points.length === 1
            ? 'One forecast is available; more updates are needed to show a trend.'
            : `Recorded range: ${min.toFixed(2)}–${max.toFixed(2)}%.`}{' '}
          Each point is a supplied forecast; replay time alone does not calculate a new estimate.
        </p>
        {firstAlert && (
          <p>
            The alert marker stays at ICU hour {firstAlert.hour}, the first supplied estimate at or above{' '}
            {(threshold * 100).toFixed(0)}%.
          </p>
        )}
        {reason && (
          <p className="risk-history-unavailable">
            <strong>Historical forecasts.</strong> Current estimate unavailable: {reason}
          </p>
        )}
      </div>
    </div>
  );
}
export function EvaluationChart({ points, name }: { points: { x: number; y: number }[]; name: string }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <CartesianGrid stroke={grid} />
          <XAxis type="number" dataKey="x" domain={[0, 1]} tick={tick} />
          <YAxis domain={[0, 1]} tick={tick} />
          <Tooltip />
          <Line dataKey="y" name={name} stroke="#267da3" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

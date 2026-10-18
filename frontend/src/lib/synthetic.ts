import { atHour } from './clinical';
import type { Patient, PlatformData, MeasurementKey } from './types';
export function syntheticData(): PlatformData {
  const patients: Patient[] = Array.from({ length: 12 }, (_, i) => {
    const p: Patient = {
      id: `SYN-${i % 2 ? 'E' : 'M'}-${String(1001 + i)}`,
      age: [67, 54, 72, 46, 63, 81, 59, 38, 70, 56, 65, 42][i],
      sex: i % 3 ? 'Male' : 'Female',
      source: i % 2 ? 'eICU-CRD' : 'MIMIC-IV',
      unit: ['Medical ICU', 'Surgical ICU', 'Cardiac ICU'][i % 3],
      admission: [
        'Sepsis / infection',
        'Postoperative monitoring',
        'Cardiac observation',
        'Respiratory support',
      ][i % 4],
      admittedAt: '2025-02-14T06:00:00.000Z',
      durationHours: [72, 72, 60, 24, 48, 66, 54, 30, 72, 36, 72, 42][i],
      weightKg: i === 8 ? undefined : 65 + i * 2,
      esrd: i === 10,
      chronicDialysis: false,
      readings: [],
      forecasts: [],
      synthetic: true,
    };
    // Fictional terminal outcomes are independent of the illustrative AKI estimates.
    if (i !== 8)
      p.outcome = {
        status: [2, 5, 9].includes(i) ? 'died' : 'discharged_alive',
        at: atHour(p, p.durationHours),
        availableAt: atHour(p, p.durationHours + ([5, 9].includes(i) ? 6 : 0)),
      };
    for (let h = 0; h <= p.durationHours; h += 6) {
      if (i === 8 && h > 6) continue;
      const base = 0.7 + i * 0.035;
      const cr =
        base +
        (i === 2 || i === 6
          ? h * 0.019
          : i === 0
            ? Math.max(0, h - 24) * 0.017
            : Math.sin(h / 10 + i) * 0.035 + h * 0.001);
      const values: Partial<Record<MeasurementKey, number>> = {
        creatinine: Math.round(cr * 100) / 100,
        bun: Math.round(14 + i + h * (i === 2 ? 0.6 : 0.12)),
        map: Math.round(82 - i * 0.6 + Math.sin(h / 8 + i) * 8),
        heartRate: Math.round(76 + i + Math.sin(h / 5) * 7),
        spo2: Math.round(97 + Math.sin(h / 8)),
        potassium: Math.round((3.7 + i * 0.06 + h * 0.002) * 10) / 10,
        bicarbonate: Math.round(25 - i * 0.3),
        lactate: Math.round((1.1 + i * 0.08) * 10) / 10,
        urineOutput: Math.round((0.9 - i * 0.025 + Math.cos(h / 10) * 0.08) * 100) / 100,
      };
      for (const [key, value] of Object.entries(values)) {
        if (
          (i === 4 && ['lactate', 'bicarbonate', 'potassium'].includes(key)) ||
          (i === 7 && h > 12 && ['bun', 'urineOutput'].includes(key))
        )
          continue;
        const at = atHour(p, h);
        p.readings.push({
          id: `${p.id}-${h}-${key}`,
          at,
          availableAt: at,
          key: key as MeasurementKey,
          value,
          intervalHours: key === 'urineOutput' && h > 0 ? 6 : undefined,
        });
      }
      if (h >= 12 && h < p.durationHours)
        p.forecasts.push({
          at: atHour(p, h),
          availableAt: atHour(p, h),
          probability: Math.min(
            0.88,
            Math.max(
              0.04,
              [0.64, 0.12, 0.72, 0.18, 0.38, 0.56, 0.68, 0.09, 0.2, 0.29, 0.17, 0.08][i] +
                Math.sin(h / 15) * 0.035,
            ),
          ),
          horizonHours: 24,
          synthetic: true,
          modelVersion: 'illustrative-scenario-v1',
        });
    }
    return p;
  });
  return {
    patients,
    evaluations: [],
    model: {
      state: 'unavailable',
      description:
        'No trained model connected. Probabilities in synthetic mode illustrate the interface only.',
    },
    provenance:
      'Entirely fictional, locally generated ICU histories. Source labels describe schema scenarios; no MIMIC-IV or eICU-CRD patient records are included.',
  };
}

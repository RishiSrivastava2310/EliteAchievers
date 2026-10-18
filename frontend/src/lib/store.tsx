import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { api, apiBase, localAuth } from './api';
import { syntheticData } from './synthetic';
import { snapshot, atHour } from './clinical';
import type { PlatformData, Session, Patient, Reading, ResearchAlert, OutcomeUpdate } from './types';
import { applyOutcomes } from './outcomes';
interface Store {
  session: Session | null;
  login: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  data: PlatformData | null;
  loading: boolean;
  error: string;
  mode: 'synthetic' | 'backend';
  reload: () => void;
  useSynthetic: () => void;
  hour: number;
  setHour: (hour: number) => void;
  threshold: number;
  setThreshold: (value: number) => void;
  alerts: ResearchAlert[];
  acknowledged: string[];
  acknowledge: (id: string) => void;
  addPatient: (p: Patient) => void;
  addReadings: (id: string, readings: Reading[]) => Promise<void>;
  saveOutcomes: (updates: OutcomeUpdate[]) => void;
  toast: (message: string) => void;
}
const Context = createContext<Store | null>(null);
export function useStore() {
  const c = useContext(Context);
  if (!c) throw new Error('Missing application provider.');
  return c;
}
function readSession(): Session | null {
  try {
    return JSON.parse(sessionStorage.getItem('taki-session') || 'null');
  } catch {
    return null;
  }
}
export function Provider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(readSession);
  const [data, setData] = useState<PlatformData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'synthetic' | 'backend'>(() => (apiBase() ? 'backend' : 'synthetic'));
  const [hour, setHour] = useState(24);
  const [threshold, saveThreshold] = useState(Number(localStorage.getItem('taki-threshold')) || 0.5);
  const [acknowledged, setAcknowledged] = useState<string[]>(() =>
    JSON.parse(localStorage.getItem('taki-acknowledged') || '[]'),
  );
  const [message, setMessage] = useState('');
  const toast = useCallback((text: string) => setMessage(text), []);
  useEffect(() => {
    if (message) {
      const t = setTimeout(() => setMessage(''), 4500);
      return () => clearTimeout(t);
    }
  }, [message]);
  const reload = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError('');
    try {
      setData(mode === 'synthetic' ? syntheticData() : await api.load(session.token, session.user.role));
    } catch (e) {
      setData(null);
      setError(e instanceof Error ? e.message : 'Unable to load data.');
    } finally {
      setLoading(false);
    }
  }, [session, mode]);
  useEffect(() => {
    void reload();
  }, [reload]);
  async function login(email: string, password: string, name?: string) {
    const s = apiBase()
      ? await (name ? api.register(name, email, password) : api.login(email, password))
      : await localAuth(email, password, name);
    if (!s.user || !['doctor', 'researcher', 'admin'].includes(s.user.role) || !s.token)
      throw new Error('Invalid authentication response.');
    setSession(s);
    sessionStorage.setItem('taki-session', JSON.stringify(s));
    setMode(apiBase() ? 'backend' : 'synthetic');
  }
  function logout() {
    setSession(null);
    setData(null);
    sessionStorage.removeItem('taki-session');
  }
  function setThreshold(v: number) {
    saveThreshold(v);
    localStorage.setItem('taki-threshold', String(v));
  }
  function acknowledge(id: string) {
    setAcknowledged((old) => {
      const next = old.includes(id) ? old : old.concat(id);
      localStorage.setItem('taki-acknowledged', JSON.stringify(next));
      return next;
    });
  }
  function addPatient(p: Patient) {
    if (mode !== 'synthetic') throw new Error('Create stays through the backend before importing readings.');
    if (data?.patients.some((existing) => existing.id === p.id))
      throw new Error('A stay with this ID already exists. Choose a unique fictional ID.');
    setData((old) => (old ? { ...old, patients: [p, ...old.patients] } : old));
    toast('Synthetic stay added to this session.');
  }
  async function addReadings(id: string, readings: Reading[]) {
    const existing = data?.patients.find((p) => p.id === id);
    if (mode === 'synthetic' && existing?.outcome && readings.some((r) => r.at > existing.outcome!.at))
      throw new Error('A measurement cannot be recorded after the terminal ICU outcome.');
    if (mode === 'backend') {
      const patient = await api.addReadings(id, readings, session!.token);
      setData((old) =>
        old ? { ...old, patients: old.patients.map((p) => (p.id === id ? patient : p)) } : old,
      );
    } else
      setData((old) =>
        old
          ? {
              ...old,
              patients: old.patients.map((p) =>
                p.id === id
                  ? {
                      ...p,
                      forecasts: [],
                      readings: p.readings.concat(readings).sort((a, b) => a.at.localeCompare(b.at)),
                    }
                  : p,
              ),
            }
          : old,
      );
    toast('Readings saved. Existing illustrative forecasts were cleared after data changes.');
  }
  function saveOutcomes(updates: OutcomeUpdate[]) {
    if (mode !== 'synthetic' || !data)
      throw new Error('Outcome entry is available only for the local synthetic cohort.');
    const patients = applyOutcomes(data.patients, updates);
    setData({ ...data, patients });
    toast(
      `${updates.length} ICU outcome record${updates.length === 1 ? '' : 's'} saved. The fatality graph has been updated.`,
    );
  }
  const alerts: ResearchAlert[] = (data?.patients || [])
    .flatMap((p) => {
      const s = snapshot(p, hour, threshold);
      const result: ResearchAlert[] = [];
      if (s.recognition.onsetAt)
        result.push({
          id: `${p.id}-aki`,
          patientId: p.id,
          at: s.recognition.onsetAt,
          title: `AKI observed · stage ${s.recognition.stage}`,
          detail:
            'Recorded measurements meet research recognition criteria. Future new-onset prediction is ineligible.',
          severity: 'critical',
          synthetic: p.synthetic,
        });
      if (s.risk === 'High')
        result.push({
          id: `${p.id}-risk-${s.forecast!.at}`,
          patientId: p.id,
          at: s.forecast!.at,
          title: p.synthetic ? 'Illustrative elevated risk' : 'Elevated model risk',
          detail: `24-hour estimate: ${Math.round(s.probability! * 100)}%. Review measurements and model provenance.`,
          severity: 'warning',
          synthetic: p.synthetic,
        });
      const completed =
        p.outcome && p.outcome.at <= atHour(p, hour) && p.outcome.availableAt <= atHour(p, hour);
      if (s.completeness < 60 && !completed)
        result.push({
          id: `${p.id}-missing`,
          patientId: p.id,
          at: atHour(p, hour),
          title: 'Incomplete recent measurements',
          detail: `${s.completeness}% of the nine core measurement types recorded in the last 12 hours.`,
          severity: 'info',
          synthetic: p.synthetic,
        });
      return result;
    })
    .sort((a, b) => b.at.localeCompare(a.at));
  return (
    <Context.Provider
      value={{
        session,
        login,
        logout,
        data,
        loading,
        error,
        mode,
        reload: () => void reload(),
        useSynthetic: () => {
          setMode('synthetic');
        },
        hour,
        setHour,
        threshold,
        setThreshold,
        alerts,
        acknowledged,
        acknowledge,
        addPatient,
        addReadings,
        saveOutcomes,
        toast,
      }}
    >
      {children}
      {message && (
        <div className="toast" role="status">
          {message}
          <button aria-label="Dismiss notification" onClick={() => setMessage('')}>
            ×
          </button>
        </div>
      )}
    </Context.Provider>
  );
}

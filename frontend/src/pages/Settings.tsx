import { useState, type FormEvent } from 'react';
import {
  Save,
  Wifi,
  UserRound,
  ShieldCheck,
  LogOut,
  RefreshCw,
  SlidersHorizontal,
  Database,
  Bell,
} from 'lucide-react';
import { useStore } from '../lib/store';
import { apiBase } from '../lib/api';
import { PageTitle, Panel, PanelHead, Button, Badge, Notice, Modal } from '../components/ui';
export function Settings() {
  const { session, logout, data, mode, threshold, setThreshold, reload, toast } = useStore();
  const [base, setBase] = useState(apiBase());
  const [testing, setTesting] = useState(false);
  const [connection, setConnection] = useState('');
  const [error, setError] = useState('');
  const [draft, setDraft] = useState(threshold);
  const [reset, setReset] = useState(false);
  const [name, setName] = useState(session!.user.name);
  function validateBase() {
    if (!base.trim()) return '';
    const url = new URL(base);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      throw new Error('Use an HTTP(S) API URL without credentials, query or fragment.');
    return base.trim().replace(/\/$/, '');
  }
  async function test() {
    setError('');
    setConnection('');
    setTesting(true);
    try {
      const url = validateBase();
      if (!url) {
        setConnection('No API URL configured. Synthetic local mode is available.');
        return;
      }
      const response = await fetch(url + '/health', { signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error(`Health endpoint returned ${response.status}.`);
      const body = await response.json();
      if (body.status !== 'ok') throw new Error('Health response must contain status: ok.');
      setConnection('Backend health check passed. Save to connect on your next sign-in.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed.');
    } finally {
      setTesting(false);
    }
  }
  function saveConnection() {
    try {
      localStorage.setItem('taki-api-base', validateBase());
      logout();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invalid API URL.');
    }
  }
  function saveProfile(e: FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) return;
    const next = { ...session!, user: { ...session!.user, name: name.trim() } };
    sessionStorage.setItem('taki-session', JSON.stringify(next));
    if (mode === 'synthetic') {
      const accounts = JSON.parse(localStorage.getItem('taki-accounts') || '[]');
      localStorage.setItem(
        'taki-accounts',
        JSON.stringify(
          accounts.map((a: { email: string }) =>
            a.email === next.user.email ? { ...a, name: name.trim() } : a,
          ),
        ),
      );
    }
    toast('Display name saved for this session.');
    window.location.reload();
  }
  return (
    <>
      <PageTitle
        eyebrow="WORKSPACE SETTINGS"
        title="Settings"
        icon={SlidersHorizontal}
        description="Manage your profile, research alert threshold and backend connection."
      />
      <div className="settings-grid">
        <Panel className="settings-profile">
          <PanelHead
            title="Research profile"
            subtitle="Your role controls the workspace navigation"
            icon={UserRound}
          />
          <form className="settings-form" onSubmit={saveProfile}>
            <div className="profile-intro">
              <span className="profile-large">
                <UserRound size={28} />
              </span>
              <div>
                <strong>{session!.user.name}</strong>
                <Badge tone="teal">{session!.user.role}</Badge>
              </div>
            </div>
            <label>
              Display name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                minLength={2}
                maxLength={80}
                required
              />
            </label>
            <label>
              Email address
              <input value={session!.user.email} readOnly />
            </label>
            <div className="profile-role">
              <ShieldCheck size={16} />
              Role: <b>{session!.user.role}</b>
              <span>Managed by your administrator</span>
            </div>
            <div className="settings-actions">
              <Button type="submit">
                <Save size={15} />
                Save display name
              </Button>
              <Button variant="ghost" type="button" onClick={logout}>
                <LogOut size={15} />
                Sign out
              </Button>
            </div>
          </form>
        </Panel>
        <Panel className="settings-threshold">
          <PanelHead
            title="Research alert threshold"
            icon={Bell}
            subtitle="Configure the elevated-risk display threshold"
          />
          <div className="settings-form">
            <div className="threshold-value">
              {Math.round(draft * 100)}
              <span>%</span>
            </div>
            <input
              type="range"
              aria-label="Elevated risk threshold"
              min="0.1"
              max="0.9"
              step="0.05"
              value={draft}
              onChange={(e) => setDraft(Number(e.target.value))}
            />
            <div className="slider-labels">
              <span>10%</span>
              <span>50%</span>
              <span>90%</span>
            </div>
            <Notice>
              This changes research display categories and alerts. It does not recalibrate the model or
              establish a clinically validated operating point. Moderate risk begins at half this threshold.
            </Notice>
            <Button
              onClick={() => {
                setThreshold(draft);
                toast('Research display threshold updated.');
              }}
            >
              <Save size={15} />
              Save threshold
            </Button>
          </div>
        </Panel>
        <Panel className="connection-panel">
          <PanelHead
            title="Backend connection"
            icon={Wifi}
            subtitle="FastAPI integration · configurable base URL"
            action={
              <Badge tone={mode === 'backend' ? 'teal' : 'warning'}>
                {mode === 'backend' ? 'Backend mode' : 'Synthetic mode'}
              </Badge>
            }
          />
          <div className="settings-form">
            {session!.user.role === 'admin' ? (
              <>
                <label>
                  API base URL
                  <input
                    type="url"
                    placeholder="http://127.0.0.1:8000"
                    value={base}
                    onChange={(e) => {
                      setBase(e.target.value);
                      setConnection('');
                      setError('');
                    }}
                  />
                </label>
                <p className="caption">
                  Test your research server before saving. Your connection applies after you sign in again.
                </p>
                {connection && <Notice tone="success">{connection}</Notice>}
                {error && <Notice tone="danger">{error}</Notice>}
                <div className="settings-actions">
                  <Button variant="secondary" onClick={() => void test()} disabled={testing}>
                    <Wifi size={15} />
                    {testing ? 'Testing…' : 'Test connection'}
                  </Button>
                  <Button onClick={saveConnection}>Save connection & sign out</Button>
                </div>
              </>
            ) : (
              <>
                <Notice>
                  Backend configuration is managed by an Admin. You can refresh the currently loaded cohort.
                </Notice>
                <Button variant="secondary" onClick={reload}>
                  <RefreshCw size={15} />
                  Refresh research data
                </Button>
              </>
            )}
            <div className="connection-details">
              <div>
                <span>Model status</span>
                <b>{data?.model.state === 'ready' ? data.model.version : 'No trained model connected'}</b>
              </div>
              <div>
                <span>Data provenance</span>
                <p>{data?.provenance || 'No cohort loaded.'}</p>
              </div>
              <div>
                <span>Timestamp display</span>
                <b>UTC · historical ICU time</b>
              </div>
            </div>
          </div>
        </Panel>
        <Panel className="settings-storage">
          <PanelHead
            title="Browser workspace"
            subtitle="Local data and research preferences"
            icon={Database}
          />
          <div className="settings-form">
            <p>
              Synthetic stays and edited measurements are held in memory and reset when the page reloads.
              Accounts, thresholds and review markers are stored locally. Session tokens are cleared on
              sign-out.
            </p>
            <Notice>
              Local authentication demonstrates frontend flows. Production access control and patient-data
              governance must be enforced by the backend.
            </Notice>
            <Button variant="secondary" onClick={() => setReset(true)}>
              <RefreshCw size={15} />
              Reset local research preferences
            </Button>
          </div>
        </Panel>
      </div>
      <Modal
        open={reset}
        onOpenChange={setReset}
        title="Reset local research preferences?"
        description="This clears your saved threshold and alert review markers. Your account and API configuration are retained."
      >
        <div className="modal-actions">
          <Button variant="secondary" onClick={() => setReset(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => {
              localStorage.removeItem('taki-threshold');
              localStorage.removeItem('taki-acknowledged');
              window.location.reload();
            }}
          >
            Reset preferences
          </Button>
        </div>
      </Modal>
    </>
  );
}

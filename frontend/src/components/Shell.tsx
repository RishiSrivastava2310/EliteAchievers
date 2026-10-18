import { useState } from 'react';
import { NavLink, useLocation, useNavigate, Outlet } from 'react-router-dom';
import { Search, Bell, LogOut, CircleHelp, Menu, X } from 'lucide-react';
import { useStore } from '../lib/store';
import { Button, Modal } from './ui';
import { Brand } from './Brand';

const navigation = [
  { path: '/', label: 'Overview', short: 'Overview' },
  { path: '/patients', label: 'Patient directory', short: 'Patients' },
  { path: '/predictions', label: 'AKI predictions', short: 'Predictions' },
  { path: '/alerts', label: 'Alerts', short: 'Alerts' },
  { path: '/analytics', label: 'Model analytics', short: 'Analytics', research: true },
  { path: '/validation', label: 'Cross-hospital validation', short: 'Validation', research: true },
  { path: '/quality', label: 'Data quality', short: 'Data quality' },
  { path: '/settings', label: 'Settings & profile', short: 'Settings' },
];

export function Shell() {
  const { session, logout, mode, alerts, acknowledged } = useStore();
  const [mobile, setMobile] = useState(false);
  const [help, setHelp] = useState(false);
  const [search, setSearch] = useState('');
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const unread = alerts.filter((a) => !acknowledged.includes(a.id)).length;
  const research = ['/analytics', '/validation'].includes(pathname);
  const initials = session!.user.name
    .replace('Dr. ', '')
    .split(' ')
    .map((n) => n[0])
    .slice(0, 2)
    .join('');
  const canResearch = session!.user.role !== 'doctor';

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="global-bar">
          <Brand />
          <nav className="workspace-areas" aria-label="Workspace areas">
            <button
              className={!research && pathname !== '/quality' && pathname !== '/settings' ? 'selected' : ''}
              onClick={() => navigate('/')}
            >
              Monitoring
            </button>
            {canResearch && (
              <button className={research ? 'selected' : ''} onClick={() => navigate('/analytics')}>
                Research
              </button>
            )}
            <button
              className={pathname === '/quality' ? 'selected' : ''}
              onClick={() => navigate('/quality')}
            >
              Data
            </button>
          </nav>
          <div className="header-tools">
            <form
              className="global-search"
              onSubmit={(e) => {
                e.preventDefault();
                navigate(`/patients?q=${encodeURIComponent(search)}`);
                setSearch('');
              }}
            >
              <Search size={16} />
              <input
                aria-label="Search ICU stays"
                placeholder="Search stays"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </form>
            <button
              className="icon-button header-help"
              aria-label="About AKI NATOR"
              onClick={() => setHelp(true)}
            >
              <CircleHelp size={18} />
            </button>
            <button
              className="notification-button icon-button"
              aria-label={`Open alerts, ${unread} unreviewed`}
              onClick={() => navigate('/alerts')}
            >
              <Bell size={18} />
            </button>
            <button className="top-avatar" aria-label="Open profile" onClick={() => navigate('/settings')}>
              {initials}
            </button>
            <button
              className="icon-button header-logout"
              aria-label="Sign out"
              title="Sign out"
              onClick={logout}
            >
              <LogOut size={17} />
            </button>
            <button
              className="icon-button mobile-menu"
              aria-label={mobile ? 'Close navigation' : 'Open navigation'}
              aria-expanded={mobile}
              aria-controls="workspace-navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={21} /> : <Menu size={21} />}
            </button>
          </div>
        </div>
        <div className={`local-bar ${mobile ? 'navigation-open' : ''}`}>
          <span className="local-label">
            {research
              ? 'Research'
              : pathname === '/quality'
                ? 'Data quality'
                : pathname === '/settings'
                  ? 'Your account'
                  : 'Workspace'}
          </span>
          <nav id="workspace-navigation" className="workspace-nav" aria-label="Main navigation">
            {navigation
              .filter((n) => !n.research || canResearch)
              .map((n) => (
                <NavLink
                  key={n.path}
                  end={n.path === '/'}
                  to={n.path}
                  aria-label={n.label}
                  onClick={() => setMobile(false)}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                  {n.short}
                  {n.path === '/alerts' && unread > 0 && <span className="nav-count">{unread}</span>}
                </NavLink>
              ))}
          </nav>
        </div>
      </header>
      <div className="main-shell">
        <main data-view={pathname === '/' ? 'overview' : pathname.split('/')[1]}>
          <Outlet />
        </main>
      </div>
      <Modal
        open={help}
        onOpenChange={setHelp}
        title="About AKI NATOR"
        description="A workspace for adult ICU kidney injury research."
      >
        <div className="explanation-list">
          <p>
            <b>Research prototype.</b> Not a medical device or clinical decision system.
          </p>
          <p>
            <b>{mode === 'synthetic' ? 'Synthetic demonstration.' : 'Connected research backend.'}</b>{' '}
            {mode === 'synthetic'
              ? 'Fictional source scenarios and illustrative estimates. No trained model is connected.'
              : 'Review model and dataset provenance before interpretation.'}
          </p>
          <p>
            <b>Replay the clinical record.</b> Select an ICU hour to see measurements available by that time.
            Later outcomes stay in a separate retrospective view.
          </p>
          <p>
            <b>Keep prediction and recognition separate.</b> A future model estimates new AKI in the next 24
            hours. Recognition checks evidence already observed. The forecast horizon is not a guaranteed
            warning time.
          </p>
          <p>
            <b>Compare across hospitals.</b> Analytics and validation show only evaluation results supplied by
            the backend.
          </p>
        </div>
        <Button onClick={() => setHelp(false)}>Back to workspace</Button>
      </Modal>
    </div>
  );
}

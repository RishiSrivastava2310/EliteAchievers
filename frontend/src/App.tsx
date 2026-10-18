import { Component, type ReactNode } from 'react';
import { Routes, Route, Navigate, Outlet, Link } from 'react-router-dom';
import { Provider, useStore } from './lib/store';
import { Shell } from './components/Shell';
import { Auth } from './pages/Auth';
import { Dashboard } from './pages/Dashboard';
import { Patients } from './pages/Patients';
import { PatientDetail } from './pages/PatientDetail';
import { Predictions } from './pages/Predictions';
import { Alerts } from './pages/Alerts';
import { Analytics, Validation } from './pages/Analytics';
import { DataQuality } from './pages/DataQuality';
import { Settings } from './pages/Settings';
import { Button, Empty, Loading, Notice } from './components/ui';
function RequireAuth() {
  const { session } = useStore();
  return session ? <Shell /> : <Navigate to="/login" replace />;
}
function DataGate() {
  const { data, loading, error, reload, useSynthetic } = useStore();
  if (loading) return <Loading />;
  if (error)
    return (
      <div className="api-error">
        <Notice tone="danger">{error}</Notice>
        <Empty
          title="The research backend is unavailable"
          description="Your workspace is preserved. Retry the connection, open Settings to correct the API URL, or explicitly load fictional demonstration data."
          action={
            <div className="error-actions">
              <Button onClick={reload}>Retry connection</Button>
              <Button variant="secondary" onClick={useSynthetic}>
                Use synthetic demonstration
              </Button>
              <Link className="text-link" to="/settings">
                Open Settings
              </Link>
            </div>
          }
        />
      </div>
    );
  return data ? <Outlet /> : <Loading />;
}
function ResearchOnly() {
  const { session } = useStore();
  return session?.user.role === 'doctor' ? (
    <Empty
      title="Research workspace access required"
      description="Model analytics and cross-hospital evaluation are available to Researcher and Admin accounts."
      action={<Link to="/">Back to overview</Link>}
    />
  ) : (
    <Outlet />
  );
}
class ErrorBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <div className="fatal-error">
        <Empty
          title="The workspace could not be displayed"
          description="Reload to restore the workspace. In-memory synthetic edits will be reset."
          action={<Button onClick={() => window.location.reload()}>Reload application</Button>}
        />
      </div>
    ) : (
      this.props.children
    );
  }
}
export function App() {
  return (
    <ErrorBoundary>
      <Provider>
        <Routes>
          <Route path="/login" element={<Auth />} />
          <Route element={<RequireAuth />}>
            <Route path="/settings" element={<Settings />} />
            <Route element={<DataGate />}>
              <Route index element={<Dashboard />} />
              <Route path="patients" element={<Patients />} />
              <Route path="patients/:id" element={<PatientDetail />} />
              <Route path="predictions" element={<Predictions />} />
              <Route path="alerts" element={<Alerts />} />
              <Route path="quality" element={<DataQuality />} />
              <Route element={<ResearchOnly />}>
                <Route path="analytics" element={<Analytics />} />
                <Route path="validation" element={<Validation />} />
              </Route>
            </Route>
            <Route
              path="*"
              element={
                <Empty
                  title="Page not found"
                  description="This page is not part of your research workspace."
                  action={<Link to="/">Back to overview</Link>}
                />
              }
            />
          </Route>
        </Routes>
      </Provider>
    </ErrorBoundary>
  );
}

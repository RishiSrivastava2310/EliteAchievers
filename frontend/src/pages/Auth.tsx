import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Eye, EyeOff, ArrowRight, ShieldCheck } from 'lucide-react';
import { useStore } from '../lib/store';
import { Button, Notice } from '../components/ui';
import { passwordError } from '../lib/api';
import { Brand } from '../components/Brand';
export function Auth() {
  const { session, login } = useStore();
  const [signup, setSignup] = useState(false);
  const [visible, setVisible] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (session) return <Navigate to="/" replace />;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (signup && passwordError(password)) {
      setError(passwordError(password));
      return;
    }
    if (signup && name.trim().length < 2) {
      setError('Enter your full name.');
      return;
    }
    setBusy(true);
    try {
      await login(email, password, signup ? name.trim() : undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sign in failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <header className="auth-header">
        <Brand href="#/login" />
        <span>Research workspace</span>
      </header>
      <section className="auth-form-side">
        <aside className="auth-cover" aria-label="AKI NATOR research platform">
          <div className="auth-cover-content">
            <img
              className="auth-cover-mark"
              src={`${import.meta.env.BASE_URL}aki-nator-mark.svg`}
              alt=""
              width={105}
              height={55}
            />
            <h1>
              Acute kidney injury
              <br />
              research.
            </h1>
            <p>
              Historical ICU observations.
              <br />
              Cross-hospital evaluation.
            </p>
          </div>
          <div className="auth-cover-caption">
            <span>AKI NATOR</span>
            <span>Adult ICU research platform</span>
          </div>
        </aside>
        <div className="auth-form-wrap">
          <h2>{signup ? 'Create your account' : 'Sign in'}</h2>
          <p>{signup ? 'Set up your research account.' : 'Continue to your AKI NATOR workspace.'}</p>
          <form onSubmit={submit}>
            {signup && (
              <label>
                Full name
                <input
                  required
                  autoComplete="name"
                  placeholder="Your full name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={80}
                />
              </label>
            )}
            <label>
              Work email
              <input
                type="email"
                required
                autoComplete="email"
                placeholder="you@hospital.org"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={160}
              />
            </label>
            <label>
              Password
              <div className="password-field">
                <input
                  aria-label="Password"
                  aria-describedby={signup ? 'password-requirements' : undefined}
                  type={visible ? 'text' : 'password'}
                  required
                  minLength={signup ? 10 : 1}
                  autoComplete={signup ? 'new-password' : 'current-password'}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  maxLength={128}
                />
                <button
                  type="button"
                  aria-label={visible ? 'Hide password' : 'Show password'}
                  onClick={() => setVisible(!visible)}
                >
                  {visible ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
              {signup && (
                <small id="password-requirements">10+ characters, uppercase, lowercase and a number.</small>
              )}
            </label>
            {error && <Notice tone="danger">{error}</Notice>}
            <Button className="auth-submit" disabled={busy} type="submit">
              {busy ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}
              <ArrowRight size={17} />
            </Button>
          </form>
          <div className="auth-switch">
            {signup ? 'Already have an account?' : 'New to AKI NATOR?'}{' '}
            <button
              onClick={() => {
                setSignup(!signup);
                setError('');
              }}
            >
              {signup ? 'Sign in' : 'Create an account'}
            </button>
          </div>
          <div className="auth-disclaimer">
            <ShieldCheck size={18} />
            <p>A research prototype. Not a medical device or clinical decision system.</p>
          </div>
        </div>
      </section>
      <div className="auth-copyright">AKI NATOR · Adult ICU research</div>
    </div>
  );
}

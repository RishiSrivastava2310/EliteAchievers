import type { PlatformData, Patient, Reading, Session, Evaluation, ModelStatus, Role } from './types';
import { normalizePatient } from './validation';
export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
export function apiBase() {
  return (localStorage.getItem('taki-api-base') ?? import.meta.env.VITE_API_BASE_URL ?? '').replace(
    /\/$/,
    '',
  );
}
export async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Number(import.meta.env.VITE_API_TIMEOUT_MS) || 8000);
  try {
    const response = await fetch(apiBase() + path, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(
        typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`,
        response.status,
      );
    }
    return (await response.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(
      e instanceof Error && e.name === 'AbortError'
        ? 'The API request timed out.'
        : 'Cannot reach the backend. Check the API URL, server and CORS settings.',
    );
  } finally {
    clearTimeout(timeout);
  }
}
export const api = {
  login: (email: string, password: string) =>
    request<Session>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (name: string, email: string, password: string) =>
    request<Session>('/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) }),
  health: () => request<{ status: string }>('/health'),
  async load(token: string, role: Role): Promise<PlatformData> {
    const [patients, model, evaluations] = await Promise.all([
      request<Patient[]>('/patients', {}, token),
      request<ModelStatus>('/models/status', {}, token),
      role === 'doctor'
        ? Promise.resolve([] as Evaluation[])
        : request<Evaluation[]>('/analytics/evaluations', {}, token),
    ]);
    if (
      !Array.isArray(patients) ||
      !Array.isArray(evaluations) ||
      !model ||
      !['ready', 'unavailable'].includes(model.state)
    )
      throw new ApiError('Backend response does not match the frontend API contract.');
    return {
      patients: patients.map(normalizePatient),
      model,
      evaluations,
      provenance:
        'Connected backend. Dataset access, de-identification and validation are managed by the research team.',
    };
  },
  addReadings: (id: string, readings: Reading[], token: string) =>
    request<Patient>(
      `/patients/${encodeURIComponent(id)}/readings`,
      { method: 'POST', body: JSON.stringify({ readings }) },
      token,
    ).then(normalizePatient),
};
interface StoredAccount {
  id: string;
  name: string;
  email: string;
  role: Role;
  salt: string;
  hash: string;
}
async function hash(password: string, salt: string) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: new TextEncoder().encode(salt), iterations: 100000, hash: 'SHA-256' },
    key,
    256,
  );
  return Array.from(new Uint8Array(bits), (b) => b.toString(16).padStart(2, '0')).join('');
}
const seeds = [
  { email: 'doctor@akinator.org', name: 'Dr. Alex Morgan', role: 'doctor' as const },
  { email: 'researcher@akinator.org', name: 'Jordan Patel', role: 'researcher' as const },
  { email: 'admin@akinator.org', name: 'Sam Rivera', role: 'admin' as const },
];
export function passwordError(password: string) {
  return password.length < 10
    ? 'Use at least 10 characters.'
    : !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/[0-9]/.test(password)
      ? 'Include uppercase, lowercase and a number.'
      : '';
}
export async function localAuth(email: string, password: string, name?: string): Promise<Session> {
  email = email.trim().toLowerCase();
  const seedEmail = email.replace(/@transportaki\.org$/, '@akinator.org');
  const accounts: StoredAccount[] = JSON.parse(localStorage.getItem('taki-accounts') || '[]');
  let account = accounts.find((a) => a.email === email);
  if (name) {
    if (account || seeds.some((s) => s.email === seedEmail))
      throw new Error('An account with this email already exists.');
    const error = passwordError(password);
    if (error) throw new Error(error);
    const salt = crypto.randomUUID();
    account = {
      id: crypto.randomUUID(),
      name,
      email,
      role: 'doctor',
      salt,
      hash: await hash(password, salt),
    };
    accounts.push(account);
    localStorage.setItem('taki-accounts', JSON.stringify(accounts));
  } else if (!account) {
    const seed = seeds.find((s) => s.email === seedEmail);
    if (!seed || !['AkiNator!2026', 'TransportAKI!2026'].includes(password))
      throw new Error('Email or password is incorrect.');
    const salt = crypto.randomUUID();
    account = { ...seed, id: seed.role, salt, hash: await hash(password, salt) };
  }
  if (!account || account.hash !== (await hash(password, account.salt)))
    throw new Error('Email or password is incorrect.');
  const { id, role } = account;
  return { user: { id, name: account.name, email, role }, token: crypto.randomUUID(), mode: 'synthetic' };
}

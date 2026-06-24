// frontend/lib/api.ts
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
export const TOKEN_KEY = 'project_evolve_access_token';

let tokenRequest: Promise<string> | null = null;

export function getAuthToken() {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function setAuthToken(token: string) {
  if (typeof window !== 'undefined') localStorage.setItem(TOKEN_KEY, token);
}

export function clearAuthToken() {
  if (typeof window !== 'undefined') localStorage.removeItem(TOKEN_KEY);
}

async function fetchBackendToken() {
  const res = await fetch('/api/auth/backend-token', {
    method: 'POST',
    cache: 'no-store',
  });

  if (!res.ok) throw new Error('Backend token request failed');

  const data = await res.json();
  if (!data?.access_token) throw new Error('Backend token missing');

  setAuthToken(data.access_token);
  return data.access_token as string;
}

export async function ensureBackendToken() {
  const existingToken = getAuthToken();
  if (existingToken) return existingToken;

  if (!tokenRequest) {
    tokenRequest = fetchBackendToken().finally(() => {
      tokenRequest = null;
    });
  }

  return tokenRequest;
}

async function attachToken(init: RequestInit = {}) {
  const token = await ensureBackendToken();
  const headers = new Headers(init.headers || {});
  headers.set('x-access-token', token);
  return { ...init, headers };
}

export async function apiFetch(input: string, init: RequestInit = {}) {
  let res = await fetch(input, await attachToken(init));

  // If the backend token expired or localStorage was cleared, get a fresh token
  // through the authenticated Next.js route and retry once before returning to login.
  if (res.status === 401 && typeof window !== 'undefined') {
    clearAuthToken();

    try {
      res = await fetch(input, await attachToken(init));
    } catch {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.href = `/login?next=${encodeURIComponent(next)}`;
    }
  }

  return res;
}

export async function loginBackendWithPassword(password: string) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error('Backend login failed');
  const data = await res.json();
  if (data?.access_token) setAuthToken(data.access_token);
  return data;
}

// Accept optional search/filter params
export async function getPaginatedFaculties(
  page: number = 1,
  limit: number = 15,
  filters?: { search?: string; min_score?: number; max_score?: number }
) {
  const params = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString(),
  });
  if (filters?.search) params.append('search', filters.search);
  if (filters?.min_score !== undefined) params.append('min_score', filters.min_score.toString());
  if (filters?.max_score !== undefined) params.append('max_score', filters.max_score.toString());

  const res = await apiFetch(`${API_BASE}/faculties?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch faculties: ${res.status}`);
  return res.json();
}

export async function evaluateFaculty(faculty_id: number) {
  const res = await apiFetch(`${API_BASE}/evaluate/${faculty_id}`);
  if (!res.ok) throw new Error('Faculty not found');
  return res.json();
}

export async function getExplanation(faculty_id: number) {
  const res = await apiFetch(`${API_BASE}/explanation/${faculty_id}`);
  if (!res.ok) throw new Error('Explanation not found');
  return res.json();
}

export async function getAudit(faculty_id: number) {
  const res = await apiFetch(`${API_BASE}/audit/${faculty_id}`);
  if (!res.ok) throw new Error('Audit not found');
  return res.json();
}

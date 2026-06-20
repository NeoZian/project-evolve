// frontend/lib/api.ts
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
export const TOKEN_KEY = 'project_evolve_access_token';

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

export async function apiFetch(input: string, init: RequestInit = {}) {
  const token = getAuthToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set('x-access-token', token);

  const res = await fetch(input, { ...init, headers });

  // If the Vercel login cookie exists but the backend token is missing/expired,
  // send the user back to login so both frontend and Render API are unlocked again.
  if (res.status === 401 && typeof window !== 'undefined') {
    clearAuthToken();
    const next = `${window.location.pathname}${window.location.search}`;
    window.location.href = `/login?next=${encodeURIComponent(next)}`;
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

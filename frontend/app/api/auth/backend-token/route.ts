import { NextRequest, NextResponse } from 'next/server';

const SITE_PASSWORD = process.env.APP_PASSWORD || process.env.SITE_PASSWORD || 'ProjectEvolve@2026';
const AUTH_COOKIE = 'project_evolve_auth';
const AUTH_VALUE = 'authenticated';
const API_BASE = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

export async function POST(request: NextRequest) {
  const isAuthenticated = request.cookies.get(AUTH_COOKIE)?.value === AUTH_VALUE;

  if (!isAuthenticated) {
    return NextResponse.json({ message: 'Login required' }, { status: 401 });
  }

  try {
    const backendResponse = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: SITE_PASSWORD }),
      cache: 'no-store',
    });

    if (!backendResponse.ok) {
      return NextResponse.json(
        { message: 'Backend login failed' },
        { status: backendResponse.status }
      );
    }

    const data = await backendResponse.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { message: 'Backend API is not reachable' },
      { status: 503 }
    );
  }
}

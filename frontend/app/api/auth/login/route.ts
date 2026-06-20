import { NextRequest, NextResponse } from 'next/server';

const SITE_PASSWORD = process.env.APP_PASSWORD || process.env.SITE_PASSWORD || 'ProjectEvolve@2026';
const AUTH_COOKIE = 'project_evolve_auth';

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const password = typeof body.password === 'string' ? body.password : '';

  if (password !== SITE_PASSWORD) {
    return NextResponse.json({ message: 'Incorrect password' }, { status: 401 });
  }

  const response = NextResponse.json({ message: 'Authenticated' });
  response.cookies.set(AUTH_COOKIE, 'authenticated', {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 60 * 60 * 8,
  });

  return response;
}

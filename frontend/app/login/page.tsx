'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Eye, EyeOff, Lock, ShieldCheck } from 'lucide-react';
import { ensureBackendToken } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [nextPath, setNextPath] = useState('/');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = params.get('next');
    if (next && next.startsWith('/')) {
      setNextPath(next);
    }
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });

      if (!response.ok) {
        setError('Incorrect password. Please try again.');
        return;
      }

      // Navigate as soon as the Vercel/Next auth cookie is set.
      // The dashboard will fetch or refresh the Render API token while its data loaders run.
      router.replace(nextPath);
      router.refresh();

      // Warm the backend token in the background so the dashboard data starts loading sooner.
      // Do not block navigation on a cold Render instance.
      void ensureBackendToken().catch(() => {
        // apiFetch will retry this when the dashboard requests data.
      });
    } catch {
      setError('Unable to verify the password right now. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen gradient-mesh flex items-center justify-center px-6 py-16">
      <div className="w-full max-w-md animate-fade-in-up">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 shadow-lg shadow-blue-500/25">
            <ShieldCheck className="h-8 w-8 text-white" strokeWidth={2.5} />
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 dark:text-white">
            Project Evolve
          </h1>
          <p className="mt-3 text-base font-medium text-gray-600 dark:text-gray-400">
            Enter the access password to open the faculty evaluation dashboard.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="rounded-3xl border border-gray-100 bg-white p-8 shadow-xl dark:border-white/5 dark:bg-[#12121a]">
          <label htmlFor="site-password" className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300">
            <Lock className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            Website Password
          </label>

          <div className="relative">
            <input
              id="site-password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter password"
              required
              autoFocus
              className="w-full rounded-2xl border-2 border-gray-200 bg-gray-50 py-4 pl-5 pr-14 text-base font-semibold text-gray-900 outline-none transition-all duration-200 placeholder:text-gray-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 dark:border-white/10 dark:bg-white/[0.03] dark:text-white dark:placeholder:text-gray-500"
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              className="absolute right-4 top-1/2 -translate-y-1/2 rounded-lg p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
            </button>
          </div>

          {error && (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="mt-6 flex w-full items-center justify-center rounded-2xl bg-gradient-to-r from-blue-500 to-purple-600 px-6 py-4 text-base font-bold text-white shadow-lg shadow-blue-500/30 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? 'Checking Password...' : 'Enter Dashboard'}
          </button>
        </form>
      </div>
    </div>
  );
}

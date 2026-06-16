'use client';

import { useEffect, useState } from 'react';
import { Lock, Loader2, LogOut } from 'lucide-react';
import { clearAuthToken, getAuthToken, loginWithPassword } from '@/lib/api';

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setAuthenticated(Boolean(getAuthToken()));
    setReady(true);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await loginWithPassword(password);
      setAuthenticated(true);
      setPassword('');
    } catch {
      setError('Incorrect password. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-[#030712]">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-blue-50 px-6 dark:from-[#030712] dark:via-[#0a0a0f] dark:to-[#111827]">
        <form onSubmit={submit} className="w-full max-w-md rounded-3xl border border-gray-200 bg-white p-8 shadow-2xl dark:border-white/10 dark:bg-[#12121a]">
          <div className="mb-6 flex items-center gap-4">
            <div className="rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 p-4 shadow-lg shadow-blue-500/25">
              <Lock className="h-7 w-7 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-black text-gray-900 dark:text-white">Project Evolve Login</h1>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Enter the shared site password to continue.</p>
            </div>
          </div>

          <label className="mb-2 block text-sm font-bold uppercase tracking-wider text-gray-600 dark:text-gray-300">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter access password"
            className="mb-4 w-full rounded-2xl border-2 border-gray-200 bg-gray-50 px-5 py-4 font-semibold text-gray-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 dark:border-white/10 dark:bg-white/[0.03] dark:text-white"
            required
          />

          {error && <p className="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm font-semibold text-red-700 dark:bg-red-950/30 dark:text-red-300">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-3 rounded-2xl bg-gradient-to-r from-blue-500 to-purple-600 px-5 py-4 font-bold text-white shadow-lg shadow-blue-500/25 transition hover:-translate-y-0.5 disabled:opacity-60"
          >
            {loading && <Loader2 className="h-5 w-5 animate-spin" />}
            Login
          </button>

          <p className="mt-5 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            No registration is needed. The backend verifies the password and the browser stores a temporary access token.
          </p>
        </form>
      </div>
    );
  }

  return (
    <>
      <button
        onClick={() => { clearAuthToken(); setAuthenticated(false); }}
        className="fixed bottom-5 right-5 z-50 inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white/90 px-4 py-2 text-xs font-bold text-gray-600 shadow-lg backdrop-blur transition hover:text-red-600 dark:border-white/10 dark:bg-[#12121a]/90 dark:text-gray-300"
        title="Logout"
      >
        <LogOut className="h-4 w-4" /> Logout
      </button>
      {children}
    </>
  );
}

'use client';

import { usePathname } from 'next/navigation';
import Navbar from '@/components/Navbar';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLoginPage = pathname === '/login';

  if (isLoginPage) {
    return <>{children}</>;
  }

  return (
    <>
      <Navbar />

      <main className="min-h-screen bg-gradient-to-br from-gray-50/50 via-white to-gray-50/30 transition-colors duration-300 dark:from-[#030712] dark:via-[#0a0a0f] dark:to-[#030712]">
        {children}
      </main>

      <footer className="border-t border-gray-200/50 bg-white/50 backdrop-blur-sm transition-colors duration-300 dark:border-white/5 dark:bg-[#0a0a0f]/50">
        <div className="mx-auto max-w-[1400px] px-6 py-8 lg:px-8">
          <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-purple-600">
                <span className="text-xs font-bold text-white">PE</span>
              </div>

              <span className="text-sm font-semibold text-gray-600 dark:text-gray-400">
                Project Evolve v2.0
              </span>
            </div>

            <p className="text-sm font-medium text-gray-500 dark:text-gray-500">
              AI-Powered • Explainable • Blockchain Secured • Fair & Transparent
            </p>

            <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
              <div className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
              All Systems Operational
            </div>
          </div>
        </div>
      </footer>
    </>
  );
}

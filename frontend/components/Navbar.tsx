'use client';
import { useTheme } from 'next-themes';
import { Sun, Moon, BookOpen, Menu, X, LogOut } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { clearAuthToken } from '@/lib/api';

export default function Navbar() {
  const router = useRouter();
  const { setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
    
    // Handle scroll effect for navbar
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  if (!mounted) return null;


  const handleLogout = async () => {
    clearAuthToken();
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (err) {
      console.error('Logout request failed:', err);
    } finally {
      setMobileMenuOpen(false);
      router.replace('/login');
      router.refresh();
    }
  };

  const navLinks = [
    { href: '/', label: 'Dashboard' },
    { href: '/fairness', label: 'Fairness' },
    { href: '/audit', label: 'Blockchain Audit' },
    { href: '/validation', label: 'Validation' },
    { href: '/feedback', label: 'Feedback' },
    { href: '/ethics', label: 'Ethics' },
  ];

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
      scrolled 
        ? 'glass shadow-lg shadow-black/5 dark:shadow-black/20' 
        : 'bg-transparent'
    }`}>
      <div className="max-w-[1400px] mx-auto px-6 lg:px-8">
        <div className="flex items-center justify-between h-18 lg:h-20">
          
          {/* Logo & Brand */}
          <Link href="/" className="flex items-center gap-3 group">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl blur opacity-25 group-hover:opacity-40 transition-opacity" />
              <div className="relative bg-gradient-to-br from-blue-500 to-purple-600 p-2.5 rounded-xl shadow-lg shadow-blue-500/25">
                <BookOpen className="w-6 h-6 text-white" strokeWidth={2.5} />
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-xl font-bold tracking-tight text-gray-900 dark:text-white group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-blue-600 group-hover:to-purple-600 transition-all duration-300">
                Project Evolve
              </span>
              <span className="text-[10px] font-medium text-gray-500 dark:text-gray-400 uppercase tracking-widest -mt-0.5">
                AI-Powered Evaluation
              </span>
            </div>
          </Link>

          {/* Desktop Navigation */}
          <div className="hidden lg:flex items-center gap-1">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="relative px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white rounded-lg hover:bg-gray-100/80 dark:hover:bg-white/5 transition-all duration-200 group"
              >
                {link.label}
                <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-0 h-0.5 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full group-hover:w-4/5 transition-all duration-300" />
              </Link>
            ))}
          </div>

          {/* Right Section */}
          <div className="flex items-center gap-4">
            
            {/* Blockchain Status Badge */}
            <div className="hidden xl:flex items-center gap-2 px-4 py-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200/50 dark:border-emerald-500/20 rounded-full">
              <div className="relative">
                <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                <div className="absolute inset-0 w-2 h-2 bg-emerald-500 rounded-full animate-ping opacity-75" />
              </div>
              <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                Blockchain Verified
              </span>
            </div>

            {/* Theme Toggle Button */}
            <button
              type="button"
              onClick={() => {
                setTheme(resolvedTheme === 'dark' ? 'light' : 'dark');
              }}
              className="relative cursor-pointer rounded-xl border border-gray-200 bg-gray-100 p-2.5 transition-all duration-300 hover:scale-110 hover:bg-gray-200 active:scale-95 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10"
              aria-label={resolvedTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              title={resolvedTheme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {resolvedTheme === 'dark' ? (
                <Sun className="h-5 w-5 text-yellow-500 transition-all duration-300" strokeWidth={2} />
              ) : (
                <Moon className="h-5 w-5 text-gray-700 transition-all duration-300" strokeWidth={2} />
              )}
            </button>

            {/* Logout Button */}
            <button
              type="button"
              onClick={handleLogout}
              className="hidden sm:flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm font-bold text-red-600 transition-all duration-300 hover:scale-105 hover:bg-red-100 active:scale-95 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300 dark:hover:bg-red-500/20"
              aria-label="Logout"
              title="Logout"
            >
              <LogOut className="h-5 w-5" strokeWidth={2.2} />
              <span className="hidden xl:inline">Logout</span>
            </button>

            {/* Mobile Menu Toggle */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="lg:hidden p-2.5 rounded-xl bg-gray-100 dark:bg-white/5 hover:bg-gray-200 dark:hover:bg-white/10 border border-gray-200 dark:border-white/10 transition-all duration-300"
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? (
                <X className="w-5 h-5 text-gray-700 dark:text-gray-300" />
              ) : (
                <Menu className="w-5 h-5 text-gray-700 dark:text-gray-300" />
              )}
            </button>
          </div>
        </div>

        {/* Mobile Navigation Menu */}
        {mobileMenuOpen && (
          <div className="lg:hidden pb-6 animate-fade-in-up">
            <div className="glass-dark rounded-2xl p-4 space-y-1 mt-4">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-4 py-3 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100/50 dark:hover:bg-white/5 rounded-xl transition-all duration-200"
                >
                  {link.label}
                </Link>
              ))}
              
              <button
                type="button"
                onClick={handleLogout}
                className="mt-3 flex w-full items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-bold text-red-600 transition-all duration-200 hover:bg-red-100 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300 dark:hover:bg-red-500/20"
              >
                <LogOut className="h-4 w-4" strokeWidth={2.2} />
                Logout
              </button>
              
              {/* Mobile Blockchain Status */}
              <div className="pt-3 mt-3 border-t border-gray-200 dark:border-white/10">
                <div className="flex items-center gap-2 px-4 py-2">
                  <div className="relative">
                    <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                    <div className="absolute inset-0 w-2 h-2 bg-emerald-500 rounded-full animate-ping opacity-75" />
                  </div>
                  <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
                    Verified on Blockchain
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
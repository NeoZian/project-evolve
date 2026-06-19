import './globals.css';
import { Inter } from 'next/font/google';
import ThemeProvider from '@/components/ThemeProvider';
import AppShell from '@/components/AppShell';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata = {
  title: 'Project Evolve | Fair Faculty Evaluation System',
  description:
    'AI-Powered, Explainable, and Blockchain-Secured Transparent Faculty Evaluation Platform with Real-time Analytics and Bias Detection',
  keywords: [
    'faculty evaluation',
    'AI',
    'explainable AI',
    'blockchain',
    'fairness',
    'academic assessment',
  ],
  authors: [{ name: 'Project Evolve Team' }],
  openGraph: {
    title: 'Project Evolve | Fair Faculty Evaluation',
    description: 'Transparent AI-powered faculty evaluation with blockchain security',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${inter.className} bg-white text-gray-900 transition-colors duration-300 dark:bg-[#030712] dark:text-gray-100`}
      >
        <ThemeProvider>
          <AppShell>{children}</AppShell>
        </ThemeProvider>
      </body>
    </html>
  );
}

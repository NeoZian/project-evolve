'use client';

import { API_BASE, apiFetch } from '@/lib/api';
import { useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, CheckCircle, Play, Scale, ShieldAlert, Users } from 'lucide-react';

interface FairnessReport {
  timestamp: string;
  threshold: number;
  score_threshold: number;
  bias_alert: boolean;
  alert_message: string;
  fairness_metrics: {
    demographic_parity_difference: number;
    demographic_parity_ratio: number;
    equalized_odds_difference: number | null;
    equalized_odds_note?: string;
    mean_score_by_gender: Record<string, number>;
    count_by_gender: Record<string, number>;
    mean_score_by_department?: Record<string, number>;
  };
  injected_bias_analysis: {
    bias_detected: boolean;
    message: string;
    target_group_mean_peer: number;
    control_group_mean_peer: number;
    difference: number;
  };
  plot_path: string;
}

type DeptFairness = {
  department: string;
  score_gap: number;
  method: string;
  groups: Array<{
    gender: string;
    department: string;
    avg_final_score: number;
    avg_peer_score: number;
    avg_student_feedback: number;
    count: number;
  }>;
};

export default function FairnessPage() {
  const [report, setReport] = useState<FairnessReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [departments, setDepartments] = useState<string[]>([]);
  const [selectedDept, setSelectedDept] = useState('');
  const [deptData, setDeptData] = useState<DeptFairness | null>(null);

  const fetchLatestReport = async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/fairness/latest`);
      if (res.ok) {
        setReport(await res.json());
        setError(null);
      } else if (res.status === 404) {
        setError('No fairness report found. Click "Run Fairness Audit" to generate one.');
      } else {
        throw new Error('Failed to load report');
      }
    } catch {
      setError('Could not connect to backend. Make sure FastAPI is running.');
    } finally {
      setLoading(false);
    }
  };

  const fetchDepartments = async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/fairness/departments`);
      if (res.ok) setDepartments((await res.json()).departments || []);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchDepartmentData = async (department: string) => {
    const query = department ? `?department=${encodeURIComponent(department)}` : '';
    const res = await apiFetch(`${API_BASE}/api/fairness/department${query}`);
    if (res.ok) setDeptData(await res.json());
  };

  const runFairnessAudit = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await apiFetch(`${API_BASE}/api/fairness/run`, { method: 'POST' });
      if (!res.ok) throw new Error((await res.text()) || 'Fairness audit failed');
      setReport(await res.json());
      await fetchDepartmentData(selectedDept);
    } catch (err: any) {
      setError(err.message || 'Error running fairness audit');
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    fetchLatestReport();
    fetchDepartments();
    fetchDepartmentData('');
  }, []);

  useEffect(() => {
    fetchDepartmentData(selectedDept);
  }, [selectedDept]);

  if (loading) return <div className="min-h-screen gradient-mesh flex items-center justify-center pt-28"><div className="animate-pulse text-xl font-bold text-gray-600 dark:text-gray-300">Loading fairness report...</div></div>;

  return (
    <div className="min-h-screen gradient-mesh">
      <div className="mx-auto max-w-[1400px] px-6 pb-16 pt-28 lg:px-8">
        <div className="mb-10 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex items-center gap-5">
            <div className="rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 p-4 shadow-lg shadow-blue-500/25">
              <BarChart3 className="h-8 w-8 text-white" />
            </div>
            <div>
              <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 dark:text-white lg:text-5xl">Fairness & Bias Audit</h1>
              <p className="mt-2 text-lg font-medium text-gray-600 dark:text-gray-400">Audits score gaps by gender and lets users inspect department-wise fairness.</p>
            </div>
          </div>
          <button onClick={runFairnessAudit} disabled={running} className="inline-flex items-center justify-center gap-3 rounded-2xl bg-gradient-to-r from-blue-500 to-purple-600 px-7 py-4 text-sm font-bold text-white shadow-lg shadow-blue-500/25 transition hover:-translate-y-0.5 disabled:opacity-60">
            {running ? <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> : <Play className="h-5 w-5" />}
            {running ? 'Running Analysis...' : 'Run Fairness Audit'}
          </button>
        </div>

        {report && <p className="mb-6 flex items-center gap-2 text-sm font-medium text-gray-500 dark:text-gray-400"><Scale className="h-4 w-4" /> Last updated: {new Date(report.timestamp).toLocaleString()}</p>}

        {error && !report && (
          <div className="mb-8 rounded-2xl border-l-4 border-red-500 bg-red-50 p-6 text-red-800 dark:bg-red-950/30 dark:text-red-300"><strong>No Data Available:</strong> {error}</div>
        )}

        {report && (
          <>
            <div className={`mb-8 rounded-2xl border-l-[6px] p-6 shadow-lg ${report.bias_alert ? 'border-red-500 bg-red-50 dark:bg-red-950/30' : 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30'}`}>
              <div className="flex items-start gap-4">
                {report.bias_alert ? <ShieldAlert className="h-8 w-8 text-red-600" /> : <CheckCircle className="h-8 w-8 text-emerald-600" />}
                <div>
                  <h3 className="text-xl font-black text-gray-900 dark:text-white">{report.bias_alert ? 'Bias Alert / Human Review Needed' : 'No Critical Bias Alert'}</h3>
                  <p className="mt-1 font-medium text-gray-700 dark:text-gray-300">{report.alert_message || 'All configured fairness alerts are within range.'}</p>
                </div>
              </div>
            </div>

            <div className="mb-10 grid grid-cols-1 gap-6 md:grid-cols-3">
              <Metric title="Demographic Parity Difference" value={report.fairness_metrics.demographic_parity_difference} note={`Alert threshold: ${report.threshold}`} />
              <Metric title="Demographic Parity Ratio" value={report.fairness_metrics.demographic_parity_ratio} note="Common target: above 0.8" />
              <Metric title="Equalized Odds" value="N/A" note={report.fairness_metrics.equalized_odds_note || 'Deferred until real expert labels are available.'} />
            </div>

            <section className="mb-10 rounded-3xl border border-indigo-200/60 bg-white p-8 shadow-lg dark:border-indigo-800/30 dark:bg-[#12121a]">
              <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="flex items-center gap-3 text-2xl font-black text-gray-900 dark:text-white"><Users className="h-6 w-6 text-indigo-600" /> Department-wise Visualization</h2>
                  <p className="mt-1 text-sm font-medium text-gray-500 dark:text-gray-400">Choose a department to generate the corresponding fairness bars instead of only viewing CS/Engineering.</p>
                </div>
                <select value={selectedDept} onChange={(e) => setSelectedDept(e.target.value)} className="rounded-2xl border-2 border-gray-200 bg-gray-50 px-4 py-3 font-bold text-gray-800 outline-none focus:border-indigo-500 dark:border-white/10 dark:bg-white/5 dark:text-white">
                  <option value="">All Departments</option>
                  {departments.map((dept) => <option key={dept} value={dept}>{dept}</option>)}
                </select>
              </div>

              {deptData && (
                <div>
                  <div className="mb-5 rounded-2xl bg-indigo-50 p-4 text-sm font-medium text-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-200">
                    <strong>{deptData.department}</strong> — score gap by gender: <strong>{Number(deptData.score_gap).toFixed(4)}</strong>. {deptData.method}
                  </div>
                  <div className="space-y-4">
                    {deptData.groups.map((g, i) => (
                      <div key={`${g.department}-${g.gender}-${i}`} className="rounded-2xl border border-gray-100 p-5 dark:border-white/5">
                        <div className="mb-2 flex items-center justify-between gap-4">
                          <div>
                            <p className="font-black text-gray-900 dark:text-white">{g.gender} — {g.department}</p>
                            <p className="text-xs font-medium text-gray-500">{g.count} records · Peer avg {Number(g.avg_peer_score).toFixed(2)} · Student avg {Number(g.avg_student_feedback).toFixed(2)}</p>
                          </div>
                          <span className="text-2xl font-black text-indigo-600 dark:text-indigo-400">{Number(g.avg_final_score).toFixed(2)}</span>
                        </div>
                        <div className="h-3 overflow-hidden rounded-full bg-gray-100 dark:bg-white/5"><div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-purple-600" style={{ width: `${Math.min((Number(g.avg_final_score) / 5) * 100, 100)}%` }} /></div>
                      </div>
                    ))}
                    {!deptData.groups.length && <p className="text-center text-gray-500">No records for this selection.</p>}
                  </div>
                </div>
              )}
            </section>

            <section className="mb-10 rounded-3xl border border-purple-200/60 bg-white p-8 shadow-lg dark:border-purple-800/30 dark:bg-[#12121a]">
              <h2 className="mb-6 text-2xl font-black text-gray-900 dark:text-white">Mean Scores by Gender</h2>
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                {Object.entries(report.fairness_metrics.mean_score_by_gender).map(([gender, score]) => (
                  <div key={gender} className="rounded-2xl border border-purple-100 p-6 dark:border-purple-800/20">
                    <div className="mb-2 flex items-baseline justify-between"><h3 className="text-xl font-black capitalize text-gray-900 dark:text-white">{gender}</h3><span className="text-4xl font-black text-purple-600 dark:text-purple-400">{score.toFixed(3)}</span></div>
                    <div className="h-3 overflow-hidden rounded-full bg-gray-100 dark:bg-white/5"><div className="h-full rounded-full bg-gradient-to-r from-purple-500 to-pink-500" style={{ width: `${(score / 5) * 100}%` }} /></div>
                    <p className="mt-3 text-sm font-medium text-gray-500">{report.fairness_metrics.count_by_gender[gender]} records</p>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-3xl border border-amber-200/60 bg-white p-8 shadow-lg dark:border-amber-800/30 dark:bg-[#12121a]">
              <h2 className="mb-4 flex items-center gap-3 text-2xl font-black text-gray-900 dark:text-white"><AlertTriangle className="h-6 w-6 text-amber-600" /> Injected Bias Detection</h2>
              <p className="mb-6 font-medium text-gray-700 dark:text-gray-300">{report.injected_bias_analysis.message}</p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <Metric title="Female CS/Eng Peer Avg" value={report.injected_bias_analysis.target_group_mean_peer ?? 'N/A'} note="Synthetic target group" />
                <Metric title="Male CS/Eng Peer Avg" value={report.injected_bias_analysis.control_group_mean_peer ?? 'N/A'} note="Control group" />
                <Metric title="Difference" value={report.injected_bias_analysis.difference ?? 'N/A'} note="Score gap" />
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function Metric({ title, value, note }: { title: string; value: any; note: string }) {
  return (
    <div className="rounded-3xl border border-gray-100 bg-white p-7 shadow-sm dark:border-white/5 dark:bg-[#12121a]">
      <p className="text-xs font-bold uppercase tracking-wider text-gray-500 dark:text-gray-400">{title}</p>
      <p className="mt-3 text-4xl font-black text-gray-900 dark:text-white">{typeof value === 'number' ? Number(value).toFixed(4).replace(/\.0000$/, '') : value}</p>
      <p className="mt-2 text-sm font-medium text-gray-500 dark:text-gray-400">{note}</p>
    </div>
  );
}

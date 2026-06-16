'use client';

import { API_BASE, apiFetch } from '@/lib/api';
import { useEffect, useState } from 'react';
import { CheckCircle, Eye, Loader2, MessageSquare, Send, ThumbsDown, ThumbsUp } from 'lucide-react';

type FeedbackItem = {
  id: number;
  faculty_id: number;
  faculty_name: string;
  department: string;
  understandability_score: number;
  trust_score: number;
  comment: string | null;
  xai_viewed: boolean;
  submitted_at: string;
};

type FeedbackPayload = {
  feedback: FeedbackItem[];
  summary: {
    total: number;
    avg_understandability: number | null;
    avg_trust: number | null;
    xai_viewed_count: number | null;
  };
};

export default function FeedbackPage() {
  const [facultyId, setFacultyId] = useState('');
  const [understandability, setUnderstandability] = useState(3);
  const [trust, setTrust] = useState(3);
  const [comment, setComment] = useState('');
  const [xaiViewed, setXaiViewed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error'>('success');
  const [feedbackData, setFeedbackData] = useState<FeedbackPayload | null>(null);

  const loadFeedback = async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/feedback?limit=25`);
      if (res.ok) setFeedbackData(await res.json());
    } catch (err) {
      console.error('Could not load feedback list', err);
    }
  };

  useEffect(() => {
    loadFeedback();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setMessage('');

    try {
      const res = await apiFetch(`${API_BASE}/api/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          faculty_id: parseInt(facultyId),
          understandability_score: understandability,
          trust_score: trust,
          comment: comment || null,
          xai_viewed: xaiViewed,
        }),
      });

      if (!res.ok) throw new Error('Submission failed');

      setMessageType('success');
      setMessage('✅ Feedback submitted and stored in the database.');
      setFacultyId('');
      setUnderstandability(3);
      setTrust(3);
      setComment('');
      setXaiViewed(false);
      await loadFeedback();
    } catch {
      setMessageType('error');
      setMessage('❌ Error submitting feedback. Please check your connection and try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen gradient-mesh">
      <div className="mx-auto max-w-5xl px-6 pb-16 pt-28 lg:px-8">
        <div className="mb-10 animate-fade-in-up">
          <div className="flex items-center gap-5 mb-4">
            <div className="relative bg-gradient-to-br from-violet-500 to-purple-600 p-4 rounded-2xl shadow-lg shadow-violet-500/25">
              <MessageSquare className="w-8 h-8 text-white" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="text-4xl lg:text-5xl font-extrabold tracking-tight text-gray-900 dark:text-white">Faculty Feedback</h1>
              <p className="text-lg text-gray-600 dark:text-gray-400 mt-2 font-medium">
                Feedback is stored live and used to measure system trust, not to change faculty ratings.
              </p>
            </div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mb-10 animate-fade-in-up delay-200 rounded-3xl border border-gray-100 bg-white shadow-xl dark:border-white/5 dark:bg-[#12121a]">
          <div className="border-b border-gray-100 px-8 py-6 dark:border-white/5">
            <div className="flex items-center gap-3 text-sm font-bold uppercase tracking-wider text-violet-700 dark:text-violet-300">
              <Send className="w-5 h-5" /> Submit Evaluation-System Feedback
            </div>
          </div>

          <div className="space-y-8 p-8">
            <div>
              <label className="mb-2 block text-sm font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300">Faculty ID *</label>
              <input
                type="number"
                required
                value={facultyId}
                onChange={(e) => setFacultyId(e.target.value)}
                placeholder="Enter faculty ID"
                className="w-full rounded-2xl border-2 border-gray-200 bg-gray-50 px-5 py-4 font-semibold text-gray-900 outline-none focus:border-violet-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-white"
              />
            </div>

            <RatingBlock label="Understandability of AI evaluation" value={understandability} setValue={setUnderstandability} color="blue" />
            <RatingBlock label="Trust in AI evaluation system" value={trust} setValue={setTrust} color="emerald" />

            <div>
              <label className="mb-2 block text-sm font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300">Additional Comments</label>
              <textarea
                rows={4}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Suggestions, concerns, or feedback about the evaluation process..."
                className="w-full resize-none rounded-2xl border-2 border-gray-200 bg-gray-50 px-5 py-4 font-medium text-gray-900 outline-none focus:border-amber-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-white"
              />
            </div>

            <label className="flex cursor-pointer items-start gap-4 rounded-2xl border-2 border-purple-200/50 bg-purple-50/60 p-5 dark:border-purple-800/20 dark:bg-purple-950/20">
              <input type="checkbox" checked={xaiViewed} onChange={(e) => setXaiViewed(e.target.checked)} className="mt-1 h-5 w-5" />
              <div>
                <span className="flex items-center gap-2 font-bold text-gray-900 dark:text-white"><Eye className="h-5 w-5" /> I viewed the XAI explanation before giving feedback</span>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">This supports H2 by measuring whether explanations increase trust.</p>
              </div>
            </label>

            <button type="submit" disabled={submitting} className="flex w-full items-center justify-center gap-3 rounded-2xl bg-gradient-to-r from-violet-500 via-purple-500 to-indigo-600 py-5 text-lg font-bold text-white shadow-xl shadow-purple-500/25 transition hover:-translate-y-0.5 disabled:opacity-60">
              {submitting ? <Loader2 className="h-6 w-6 animate-spin" /> : <Send className="h-6 w-6" />}
              {submitting ? 'Submitting...' : 'Submit Feedback'}
            </button>

            {message && (
              <div className={`rounded-2xl border-2 p-5 ${messageType === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800/30 dark:bg-emerald-950/20 dark:text-emerald-200' : 'border-red-200 bg-red-50 text-red-800 dark:border-red-800/30 dark:bg-red-950/20 dark:text-red-200'}`}>
                <div className="flex items-start gap-3"><CheckCircle className="h-5 w-5" /><p className="font-semibold">{message}</p></div>
              </div>
            )}
          </div>
        </form>

        <section className="animate-fade-in-up rounded-3xl border border-gray-100 bg-white p-8 shadow-xl dark:border-white/5 dark:bg-[#12121a]">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-2xl font-black text-gray-900 dark:text-white">Stored Feedback Responses</h2>
              <p className="mt-1 text-sm font-medium text-gray-500 dark:text-gray-400">Recent database records from the live feedback table.</p>
            </div>
            <button onClick={loadFeedback} className="rounded-xl bg-gray-100 px-4 py-2 text-sm font-bold text-gray-700 hover:bg-gray-200 dark:bg-white/5 dark:text-gray-200">Refresh</button>
          </div>

          {feedbackData?.summary && (
            <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-4">
              <Summary label="Total" value={feedbackData.summary.total ?? 0} />
              <Summary label="Avg Understandability" value={Number(feedbackData.summary.avg_understandability || 0).toFixed(2)} />
              <Summary label="Avg Trust" value={Number(feedbackData.summary.avg_trust || 0).toFixed(2)} />
              <Summary label="Viewed XAI" value={feedbackData.summary.xai_viewed_count ?? 0} />
            </div>
          )}

          <div className="overflow-hidden rounded-2xl border border-gray-100 dark:border-white/5">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wider text-gray-500 dark:bg-white/5 dark:text-gray-400">
                <tr>
                  <th className="px-4 py-3">Faculty</th>
                  <th className="px-4 py-3">Understandability</th>
                  <th className="px-4 py-3">Trust</th>
                  <th className="px-4 py-3">XAI</th>
                  <th className="px-4 py-3">Comment</th>
                  <th className="px-4 py-3">Submitted</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-white/5">
                {(feedbackData?.feedback || []).map((item) => (
                  <tr key={item.id} className="text-gray-700 dark:text-gray-300">
                    <td className="px-4 py-3 font-semibold">#{item.faculty_id}<br/><span className="text-xs font-medium text-gray-500">{item.faculty_name}</span></td>
                    <td className="px-4 py-3">{item.understandability_score}/5</td>
                    <td className="px-4 py-3">{item.trust_score}/5</td>
                    <td className="px-4 py-3">{item.xai_viewed ? 'Yes' : 'No'}</td>
                    <td className="max-w-xs px-4 py-3">{item.comment || '—'}</td>
                    <td className="px-4 py-3 text-xs">{new Date(item.submitted_at).toLocaleString()}</td>
                  </tr>
                ))}
                {!feedbackData?.feedback?.length && (
                  <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">No feedback submitted yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

function RatingBlock({ label, value, setValue, color }: { label: string; value: number; setValue: (v: number) => void; color: 'blue' | 'emerald' }) {
  return (
    <div>
      <label className="mb-3 block text-sm font-bold uppercase tracking-wider text-gray-700 dark:text-gray-300">{label}</label>
      <div className="flex gap-3">
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            key={score}
            type="button"
            onClick={() => setValue(score)}
            className={`flex-1 rounded-2xl py-4 text-lg font-black transition hover:scale-105 ${value === score ? (color === 'blue' ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/25' : 'bg-emerald-600 text-white shadow-lg shadow-emerald-500/25') : 'bg-gray-100 text-gray-600 dark:bg-white/5 dark:text-gray-300'}`}
          >
            {score}
          </button>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-xs font-medium text-gray-500"><span><ThumbsDown className="inline h-3 w-3" /> Low</span><span>High <ThumbsUp className="inline h-3 w-3" /></span></div>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-2xl bg-gray-50 p-4 dark:bg-white/5"><p className="text-xs font-bold uppercase tracking-wider text-gray-500">{label}</p><p className="mt-1 text-2xl font-black text-gray-900 dark:text-white">{value}</p></div>;
}

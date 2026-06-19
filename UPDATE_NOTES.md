# Project Evolve Update Notes

## Changes made

1. Added website password protection for the Next.js frontend.
   - Password: `ProjectEvolve@2026`
   - Added `/login` password page.
   - Added show/hide password toggle.
   - Added server-side auth cookie through `/api/auth/login`.
   - Added route protection through `frontend/proxy.ts` for Next.js 16.

2. Added faculty feedback database display.
   - Added `GET /api/feedback` in the FastAPI backend.
   - The feedback page now fetches stored feedback from the database.
   - Feedback is displayed in a table below the submission form.
   - The table includes faculty ID/name, department, understandability score, trust score, XAI viewed status, comment, and submitted date.
   - A refresh button reloads the latest database records.

## Deployment notes

- On Vercel, optionally set `SITE_PASSWORD=ProjectEvolve@2026` in Environment Variables. The code also has this as a fallback.
- Keep `NEXT_PUBLIC_API_URL` pointed to your Render backend URL.
- Keep `CORS_ALLOW_ORIGINS` on Render set to your Vercel frontend URL.

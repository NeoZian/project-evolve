# Fetch/Auth Fix Notes

This version keeps the working feedback implementation and fixes the other tabs that were failing after password protection was added.

## Root cause
The Feedback page was already using `apiFetch`, which attaches the backend `x-access-token` returned by Render `/api/auth/login`.

Other pages were still using plain `fetch(...)`, so after the backend password gate was added, Render rejected those requests with 401/failed fetch:

- Fairness tab
- Blockchain Audit tab
- Validation tab
- Dashboard analytics charts
- Faculty LIME report loading
- Faculty PDF export

## Fix
The affected pages/components now use the shared authenticated `apiFetch` helper from `frontend/lib/api.ts`.

A Logout button was also added to the navbar. It clears:

- the Vercel auth cookie via `/api/auth/logout`
- the backend access token stored in browser localStorage

## Changed files

- `frontend/lib/api.ts`
- `frontend/app/fairness/page.tsx`
- `frontend/app/audit/page.tsx`
- `frontend/app/validation/page.tsx`
- `frontend/app/faculty/[id]/page.tsx`
- `frontend/components/AnalyticsCharts.tsx`
- `frontend/components/Navbar.tsx`

## Deployment reminder
After deploying this version, log out once or clear site data, then log in again with the password so the browser stores a fresh backend API token.

# Project Evolve Feature Patch Notes

## Login Access
- Added password-only login gate for the frontend.
- No registration is required.
- Backend verifies `APP_PASSWORD` through `POST /api/auth/login` and returns an access token.
- All API routes are protected with `x-access-token`, except `/`, `/health`, `/api/auth/login`, and `/reports/*`.
- Default demo password: `ProjectEvolve@2026`.
- Set Render env var `APP_PASSWORD` to change it.

## Fairness Department Selector
- Added backend endpoints:
  - `GET /api/fairness/departments`
  - `GET /api/fairness/department?department=...`
- Fairness page now lets users select a department and view gender-wise average final score, peer score, student feedback, count, and score gap.

## Feedback Display
- Added `GET /api/feedback`.
- Feedback page now displays stored feedback records below the form, including faculty, understandability, trust, XAI viewed, comments, and timestamp.

## Value Methodology Notes
- Individual faculty report now includes a short “How These Values Are Generated” section for:
  - final score
  - student feedback
  - NLP sentiment
  - peer review
  - performance
  - course quality
  - AI summary / XAI
  - recommendations

## Deployment Notes
- On Render backend, add/update:
  - `APP_PASSWORD=your-password`
- On Vercel frontend, keep:
  - `NEXT_PUBLIC_API_URL=https://your-render-backend-url`
- After deploy, users must log in with the configured password before accessing the site.

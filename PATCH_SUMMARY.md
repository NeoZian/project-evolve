# Project Evolve Patch Summary

This version was patched to better match the R&D requirements for Responsible AI, XAI, fairness validation, blockchain auditability, secure configuration, cloud-readiness, and dashboard usability.

## Backend changes

### `src/api/main.py`
- Replaced hardcoded SQLAlchemy `URL.create(...)` credentials with `.env`-based `DATABASE_URL`.
- Added `ensure_runtime_tables()` to create `faculty_feedback`, `shap_explanations`, and `blockchain_audit_logs` if missing.
- Prevented FastAPI from crashing when Ganache is not running.
- Added `.env`-based `WEB3_PROVIDER_URL`, `CONTRACT_ADDRESS`, and `CORS_ALLOW_ORIGINS`.
- Replaced unsafe string-built SQL in `/faculties`, `/evaluate`, `/explanation`, `/audit`, `/verify`, and `/export_pdf` with parameterized SQL.
- Fixed `/verify/{faculty_id}` so it no longer hashes a fresh `datetime.utcnow()` timestamp.
- Made `/api/stats`, `/audit/{faculty_id}`, `/api/audit/all`, and `/health` degrade gracefully if blockchain tables are missing.
- Made `/api/feedback/analysis` safe when there are too few feedback responses for a t-test.

### `src/xai/precompute_shap.py`
- Rewritten to use `.env` configuration.
- Removed invalid SHAP row-index mapping from perturbed samples to original `gender` and `department`.
- SHAP now explains only evaluation factors: student feedback, peer review, grade performance, NLP sentiment, and course quality.

### `src/xai/generate_lime.py`
- Rewritten to use `.env` configuration.
- Removed invalid LIME row-index mapping from perturbed samples to original `gender` and `department`.
- Added missing faculty-ID handling.

### `src/fairness/audit.py`
- Rewritten to use `.env` configuration.
- Fixed missing SQLAlchemy import and wrong `send_alert(report)` call.
- Removed misleading equalized-odds calculation because the prototype does not have real expert ground-truth labels.
- Added department and intersectional fairness summaries.
- Added clearer fairness methodology note to JSON/HTML reports.

### `src/validation/hypothesis_testing.py`
- Switched database connection to `.env`-based `DATABASE_URL`.
- Added explicit note that expert validation is simulated in the current prototype.

## Frontend changes

### `frontend/app/globals.css`
- Added Tailwind CSS v4 class-based dark-mode variant:
  `@custom-variant dark (&:where(.dark, .dark *));`

### `frontend/components/ThemeProvider.tsx`
- Added a dedicated client-side `next-themes` provider.

### `frontend/app/layout.tsx`
- Removed manual theme-changing script from `<head>`.
- Wrapped app with the new `ThemeProvider`.
- Set stable class-based dark/light mode behavior.

### `frontend/components/Navbar.tsx`
- Replaced the complex theme toggle button with a simpler and reliable `next-themes` toggle.
- Removed unused `theme` variable.

### Frontend API URL changes
Updated these files to use `NEXT_PUBLIC_API_URL` via `API_BASE` instead of hardcoded `http://localhost:8000`:
- `frontend/lib/api.ts`
- `frontend/app/page.tsx`
- `frontend/app/audit/page.tsx`
- `frontend/app/fairness/page.tsx`
- `frontend/app/feedback/page.tsx`
- `frontend/app/validation/page.tsx`
- `frontend/app/faculty/[id]/page.tsx`
- `frontend/components/AnalyticsCharts.tsx`

### `frontend/app/fairness/page.tsx`
- Updated equalized-odds card to display `N/A` with a methodological explanation instead of comparing an invalid metric.

## New files added

- `.env.example`
- `.gitignore`
- `requirements.txt`
- `database/schema.sql`
- `contracts/EvaluationAudit.sol`
- `docs/DATASET_SUMMARY.md`
- `README.md`
- `PATCH_SUMMARY.md`

## Notes

- Python files were syntax-checked with `python -m py_compile`.
- Frontend build was not executed because `node_modules` was not included in the uploaded ZIP. Run `npm install` inside `frontend/` before `npm run build`.

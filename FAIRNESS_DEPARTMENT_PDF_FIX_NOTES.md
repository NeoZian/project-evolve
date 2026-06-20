# Fairness Department Selector + Audit PDF Fix

## Changed files

- `src/api/main.py`
- `src/fairness/audit.py`
- `frontend/app/fairness/page.tsx`

## What changed

1. Added `GET /api/fairness/departments` so the frontend can load real department names from `evaluation_results`.
2. Updated `POST /api/fairness/run` to accept `?department=<department name>`.
3. Updated the fairness audit generator so the peer-score boxplot is no longer hardcoded to CS/Engineering.
4. Added a department selector above **Run Fairness Audit**.
5. The generated report now includes `selected_department`, `available_departments`, and department-specific peer-score gap analysis.
6. Updated PDF download headers to prevent cached old PDF downloads and changed the filename to `project_evolve_complete_audit_<faculty_id>.pdf`.

## Deployment note

This requires redeploying both:

- Render, because `src/api/main.py` and `src/fairness/audit.py` changed.
- Vercel, because `frontend/app/fairness/page.tsx` changed.

After deployment, log out and log in again, then choose a department and click **Run Fairness Audit**.

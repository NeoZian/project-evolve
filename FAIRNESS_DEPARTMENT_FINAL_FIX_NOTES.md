# Fairness Department Selector Final Fix

This update fixes the department dropdown being stuck on Loading departments.

## Root cause
The dropdown was waiting for the backend department endpoint. That endpoint depended on database inspection/querying before using the bundled demo data. On free Render/Supabase deployments, that path can fail or hang. The old graph was produced from the project's generated `evaluation_results` data, so the selector should use the same source.

## Fix
- Added the full department fallback list from `evolve_db_dump.sql` to the frontend, so the selector is usable immediately.
- Changed `GET /api/fairness/departments` to read `evolve_db_dump.sql` first instead of waiting on Supabase.
- Added SQL-dump fallback loading to `src/fairness/audit.py` so selected-department graph generation works even if the live database is unavailable.
- The graph title now uses the selected department directly instead of hardcoding CS/Engineering.

## Deployment
Push the changed files and redeploy both Render and Vercel.

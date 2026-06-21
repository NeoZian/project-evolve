# Fairness graph and metrics final fix

This update fixes the last fairness issue where selecting a department changed the dropdown but the report still appeared to show the old CS/Engineering visualization and unchanged metric cards.

## Changes

- `src/api/main.py` now runs the fairness audit in-process and returns the exact report generated for the selected department instead of launching a subprocess and guessing the latest report file.
- `src/fairness/audit.py` now computes displayed fairness metrics from the selected department subset.
- `src/fairness/audit.py` now uses the selected department for both visualization panels:
  - Final score distribution by gender in the selected department
  - Peer score by gender in the selected department
- `frontend/app/fairness/page.tsx` adds a cache-busting query string to the visualization image so browsers do not keep showing an older CS/Engineering PNG.

## Deployment

Redeploy both Render and Vercel after pushing these files.

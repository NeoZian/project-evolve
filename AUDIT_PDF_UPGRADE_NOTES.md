# Audit PDF Export Upgrade

Updated `src/api/main.py` so the `Download Complete Audit PDF` export now includes:

- Faculty overview
- Evaluation factors for the selected faculty member
- Explainable AI / SHAP summary when available
- Blockchain audit details
- Transaction Hash
- Result Hash
- Audit timestamp and status
- Actionable recommendations based on the faculty member's metrics

Only the backend export endpoint was changed for this upgrade. Redeploy Render after pushing this file.

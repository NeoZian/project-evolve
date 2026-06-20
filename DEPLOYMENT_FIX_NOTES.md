# Deployment fix notes

This patch fixes feedback table loading against the existing Supabase dump schema.

The original deployed `faculty_feedback` table uses:

- `feedback_id`
- `created_at`

The newer local runtime schema used:

- `id`
- `submitted_at`

The API now detects which columns exist and returns a normalized response to the frontend, so `/api/feedback` works with both schemas.

The password route now also supports either environment variable:

- `APP_PASSWORD`
- `SITE_PASSWORD`

Recommended Vercel variable:

```text
APP_PASSWORD=ProjectEvolve@2026
```

After pushing this update to GitHub:

1. Redeploy the Render backend.
2. Redeploy the Vercel frontend.
3. Test the backend directly in the browser:
   `/api/feedback?limit=20` on your Render API URL.

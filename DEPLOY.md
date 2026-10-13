# Deploying FarmIQ on free tiers

Render's free web service sleeps after 15 minutes, has 512 MB RAM and cold-starts PyTorch slowly. Split the app instead:
the frontend is static files and belongs on a CDN; the backend is a Docker container that needs about 1 GB RAM for
PyTorch and a persistent disk for the cache.

## 1. Backend: Hugging Face Space (Docker, free CPU, 16 GB RAM)

1. Create a Space at https://huggingface.co/new-space, SDK **Docker**, hardware **CPU basic (free)**.
2. Push this repository to the Space (only `app/`, `web/`, `Dockerfile`, `requirements.txt` are needed), with the
   Space README front matter from `deploy/hf-space/README.md` (it sets `app_port: 8000`).
3. In the Space settings add secrets: `GEMINI_API_KEY`, `DATA_GOV_API_KEY`, and `ALLOWED_ORIGINS=https://<your-vercel-domain>`.
4. The backend URL is `https://<user>-<space>.hf.space`. Check `https://<user>-<space>.hf.space/api/health`.

Free Spaces sleep after 48 hours without traffic and wake in about 30 seconds on the next request; that is far better than
Render's 15 minutes. If you want no sleeping at all, Google Cloud Run's free tier (2 million requests/month, scale to
zero, ~10 s cold start) also runs the same `Dockerfile` unchanged:

```bash
gcloud run deploy farmiq --source . --region asia-south1 --memory 2Gi --allow-unauthenticated \
  --set-env-vars FARMIQ_ENV=production,ALLOWED_ORIGINS=https://<your-vercel-domain>
```

## 2. Frontend: Vercel (static, free, global CDN)

1. Edit `web/vercel.json` and replace `YOUR-BACKEND-HOST` with the backend host from step 1 (no trailing slash).
   The rewrites proxy `/api/*` and `/uploads/*` to the backend, so the app stays same-origin and needs no CORS.
2. Deploy the `web/` folder:

```bash
cd web
vercel login
vercel --prod
```

Or connect the GitHub repository in the Vercel dashboard with **Root Directory = `web`** and framework **Other**.

Cloudflare Pages or Netlify work the same way; only the rewrite syntax differs (`_redirects` file:
`/api/* https://<backend>/api/:splat 200`).

## 3. Verify before you announce it

- `GET /api/health` on the backend returns `"vision_ready": true` and the crop count.
- Open the Vercel URL, set a plot, run a season, scan a leaf, load prices. The browser network tab should show
  `/api/...` calls answered with status 200 from the Vercel domain.
- Run `pytest -q` locally before every push; the suite is offline and takes 20 s.

## What each service costs at zero traffic

| Piece | Service | Sleeps? | Limit |
| --- | --- | --- | --- |
| Frontend | Vercel Hobby | never | 100 GB bandwidth/month |
| Backend | HF Space CPU basic | after 48 h idle, 30 s wake | 16 GB RAM, 50 GB disk |
| Backend alternative | Cloud Run | scale-to-zero, ~10 s wake | 2M requests/month free |
| Database | SQLite on the container disk | n/a | community posts only; use Neon Postgres (free) via `DATABASE_URL` for durability |

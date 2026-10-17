# Ripple Deployment Guide (Zero-Cost & Production-Ready)

This repository is configured for an **all-in-one, zero-cost, automated deployment** tailored for the FalkorDB Hackathon.

---

## 1. Architecture Overview

```
                         Internet / Judges
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │        Render Web Service ($0 Free Tier)     │
        │                                              │
        │   ┌──────────────────────────────────────┐   │
        │   │ FastAPI Backend (Uvicorn :8000)      │   │
        │   │  • /api/*   -> Business Logic & Agent│   │
        │   │  • /health  -> Health Check Probe    │   │
        │   │  • /*       -> Serves React Static   │   │
        │   │                Assets (frontend/dist)│   │
        │   └──────────────────────────────────────┘   │
        └──────────────────────┬───────────────────────┘
                               │ Redis Protocol + TLS
                               ▼
                   [FalkorDB Cloud Instance]
```

### Key Advantages:
- **Zero Cost (\$0)**: Runs entirely within Render's free tier.
- **Zero CORS / Domain Issues**: Frontend and Backend share the exact same domain and port (`https://<app>.onrender.com`).
- **Zero Maintenance**: Single service to monitor and single place for secrets.
- **Automated CI/CD**: Pushing to `main` verifies build/tests and triggers an instant zero-downtime re-deploy via GitHub Actions.

---

## 2. Setting Up Render (5 Minutes, Free)

1. Sign up / Log in to [Render](https://render.com).
2. Click **New +** $\rightarrow$ **Blueprint** (or **Web Service**).
3. Connect your GitHub repository: `jaybhanushali3166/ripple-graph-hackathon`.
4. Render will automatically detect [`render.yaml`](file:///Users/jaybhanushali/Desktop/Projects/Personal/AI/graph-hackathon/render.yaml).
5. Fill in your environment variables in the Render dashboard:
   - `FALKORDB_HOST`: Your FalkorDB Cloud host (e.g. `xyz.falkordb.cloud`)
   - `FALKORDB_PORT`: `6379` (or your cloud port)
   - `FALKORDB_PASSWORD`: Your FalkorDB Cloud instance password
   - `RIPPLE_GRAPH_NAME`: `ripple_demo`
   - `LLM_API_KEY`: Your Gemini or OpenAI API key
   - `LLM_MODEL`: `gemini-2.5-flash`
   - `CORS_ORIGINS`: `*`
6. Click **Apply / Deploy**.

---

## 3. Configuring the GitHub Action for Auto-Deployment

Once your Render service is created:

1. In your Render Dashboard, go to your service $\rightarrow$ **Settings** $\rightarrow$ scroll to **Deploy Hook**.
2. Click **Create Deploy Hook** and copy the URL (looks like `https://api.render.com/deploy/srv-xxxxxxx?key=yyyyyyy`).
3. In your GitHub repository, go to:
   **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions** $\rightarrow$ **New repository secret**.
4. Create the secret:
   - **Name**: `RENDER_DEPLOY_HOOK_URL`
   - **Value**: *(paste your Render deploy hook URL)*

### How it works:
Whenever code is pushed to `main` (or via **Actions** $\rightarrow$ **Run workflow**):
1. GitHub Actions checks out the code.
2. Builds and validates the React frontend (`npm run build`).
3. Runs the test suite.
4. If everything passes, triggers the Render Deploy Hook. Render pulls the new commit and rebuilds the container with zero manual intervention.

---

## 4. Preventing Cold Starts During Hackathon Evaluation

> [!TIP]
> Free-tier Render services enter sleep mode after 15 minutes of inactivity. When a judge accesses the page, waking up takes ~40 seconds.
> To keep your service 100% warm and instantaneous during the judging window:
> 1. Go to [UptimeRobot](https://uptimerobot.com) (free) or [cron-job.org](https://cron-job.org).
> 2. Create an HTTP monitor that pings your health check endpoint every 10 minutes:
>    `https://<your-app>.onrender.com/api/health`

---

## 5. Local Docker Testing

You can build and test the exact fullstack production container locally at any time:

```bash
# Build the unified container
docker build -t ripple-app .

# Run with your FalkorDB Cloud credentials
docker run -p 8000:8000 \
  -e FALKORDB_HOST="your-falkordb-host" \
  -e FALKORDB_PORT="6379" \
  -e FALKORDB_PASSWORD="your-password" \
  -e RIPPLE_GRAPH_NAME="ripple_demo" \
  -e LLM_API_KEY="your-api-key" \
  ripple-app
```
Then visit `http://localhost:8000` to interact with the full application!

---

## 6. Optional: Deploying Standalone Frontend to Vercel

If you ever wish to deploy the frontend to Vercel separately in addition to Render:
1. Add secrets in GitHub Actions:
   - `VERCEL_TOKEN`
   - `VERCEL_ORG_ID`
   - `VERCEL_PROJECT_ID`
2. The GitHub Action in [`.github/workflows/deploy.yml`](file:///Users/jaybhanushali/Desktop/Projects/Personal/AI/graph-hackathon/.github/workflows/deploy.yml) will automatically run the `deploy-vercel` job as well.


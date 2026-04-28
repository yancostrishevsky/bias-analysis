# Railway Hobby Deployment

This repository is prepared for a two-service Railway deployment:

- `backend/` as one FastAPI service
- `frontend/` as one Angular static web service

The backend is the only service that needs persistent storage.

## Service Layout

Create two Railway services from the same GitHub repository:

1. Backend service
   - Root directory: `backend`
   - Dockerfile: `Dockerfile` inside `backend/`
2. Frontend service
   - Root directory: `frontend`
   - Dockerfile: `Dockerfile` inside `frontend/`

Railway uses a `Dockerfile` at the root of each service source directory by default, so no extra build tooling is required if you point each service at the matching folder.

## Backend Service

Attach a Railway Volume to the backend service and mount it at:

```text
/data
```

Set these backend variables in Railway:

Required for Railway deployment:

- `APP_ENV=production`
- `DATABASE_PATH=/data/app.db`
- `RUN_ARTIFACTS_DIR=/data/run_artifacts`
- `CORS_ALLOWED_ORIGINS=https://<your-frontend-domain>`

Optional but recommended:

- `LOG_LEVEL=info`
- `OPENROUTER_SITE_URL=https://<your-frontend-domain>`

Required only if you want `llm_audit` runs:

- `OPENROUTER_API_KEY=...`

Optional provider credentials:

- `OPENALEX_API_KEY=...`
- `SEMANTIC_SCHOLAR_API_KEY=...`
- `SCOPUS_API_KEY=...`
- `SCOPUS_INSTTOKEN=...`
- `CORE_API_KEY=...`

Notes:

- The backend also accepts `ARTIFACTS_DIR=/data/run_artifacts` as an alias, but `RUN_ARTIFACTS_DIR` is the canonical variable used by the repo.
- Railway injects `PORT` automatically at runtime. The backend container reads it and binds to `0.0.0.0`.
- Runtime volume paths are used only after the container starts. Nothing depends on `/data` during image build.

Healthcheck path:

```text
/health
```

## Frontend Service

Set this frontend variable in Railway:

- `API_BASE_URL=https://<your-backend-domain>`

The frontend container writes `app-config.js` from `API_BASE_URL` at runtime, so you do not need to rebuild the app manually when the backend URL changes.

Healthcheck path:

```text
/health
```

## Deployment Order

1. Deploy the backend service.
2. Attach the backend volume at `/data`.
3. Set backend variables, especially:
   - `APP_ENV=production`
   - `DATABASE_PATH=/data/app.db`
   - `RUN_ARTIFACTS_DIR=/data/run_artifacts`
4. Deploy the backend again if you added the volume or changed variables after first deploy.
5. Copy the backend public URL from Railway.
6. Set `API_BASE_URL` on the frontend service to that backend public URL.
7. Deploy the frontend service.
8. Copy the frontend public URL from Railway.
9. Update backend `CORS_ALLOWED_ORIGINS` to the frontend public URL if it is not already set correctly.
10. Redeploy the backend service once more after the final frontend URL is known.

## Persistence Guarantees In This Repo

For production mode, the backend defaults to:

- `DATABASE_PATH=/data/app.db`
- `RUN_ARTIFACTS_DIR=/data/run_artifacts`

That means:

- SQLite lives on the Railway Volume
- run artifacts live on the Railway Volume
- restarts and redeploys continue using the mounted volume paths as long as those environment variables remain set

The app does not rely on build-time writes to the volume. Database initialization and artifact writes happen at runtime only.

## Hobby-Safe Defaults

This setup is intentionally minimal:

- one backend process
- one frontend container
- SQLite instead of a separate managed database
- no background worker service
- no autoscaling assumptions in the repo

Recommended Railway settings for a short-lived small deployment:

- keep a single replica for backend and frontend
- keep default resource limits unless you observe memory pressure
- set a usage hard limit in Railway before sharing the app

## Usage Limit / Budget Controls

Railway’s current cost-control docs describe usage limits at the workspace usage page, including a custom email alert and a hard limit that shuts workloads down when reached. After deployment, set this manually in the Railway UI for the workspace that owns the project.

If you want extra protection against accidental overuse, also review per-service replica limits in the Railway UI.

## Verification Checklist

After deployment:

1. Open backend `/health`
2. Open frontend `/health`
3. Open the frontend app
4. Create a small scholarly run
5. Confirm a SQLite file exists at `/data/app.db`
6. Confirm run artifacts are created under `/data/run_artifacts`
7. Restart the backend service and verify previous runs are still visible

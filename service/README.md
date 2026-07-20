# PPT Master Remote API

This service wraps the existing PPT Master Agent workflow without changing its serial gates.
Each task is isolated under `runtime/jobs/<UUID>/` and keeps one resumable Codex thread.

## Components

- `service.app`: authenticated FastAPI service
- `service.worker`: Redis worker and Codex SDK thread runner
- PostgreSQL: tasks, events, confirmations, uploads, and artifacts
- Redis: queued and in-progress task identifiers
- Caddy: public HTTPS endpoint

## Deployment

Recommended host: Ubuntu 24.04 x86_64, 4 CPU cores, 8 GB RAM, 50 GB free disk,
Docker Engine 27 or newer, and Docker Compose v2. The host must allow outbound HTTPS and inbound
ports 80/443. Point `PPT_API_DOMAIN` to the host before starting Caddy.

The worker image contains Python 3.12, the official Codex Python SDK with its pinned runtime,
LibreOffice, Pandoc, Poppler, Playwright Chromium, and Noto CJK fonts. It runs as UID 10001 rather
than root. `runtime_data` stores task files, while `codex_data` stores resumable Codex thread state
across container restarts.

Set these values in `.env`:

```dotenv
PPT_API_DOMAIN=ppt.example.com
PPT_POSTGRES_PASSWORD=<random-database-password>
OPENAI_API_KEY=<worker-model-key>
PPT_IMAGE_API_KEY=<image-provider-key>
PPT_IMAGE_BASE_URL=https://prism.example.com/v1
PPT_IMAGE_MODEL=gpt_image2
PPT_IMAGE_SIZE=2048x1536
PPT_SESSION_DAYS=30
PPT_JOB_LEASE_SECONDS=30
PPT_JOB_HEARTBEAT_SECONDS=5
```

Start storage services first:

```bash
docker compose up -d postgres redis
```

Review the complete migration SQL, then apply it explicitly:

```bash
docker compose run --rm api python -m service.migrate --show
docker compose run --rm api python -m service.migrate --apply --confirm APPLY
```

Create the first administrator from the server console. Public first-user registration is not
available:

```bash
docker compose run --rm api python -m service.admin create --username admin
```

Start the API, worker, and HTTPS proxy:

```bash
docker compose up -d api worker caddy
```

Check the deployment:

```bash
docker compose ps
curl https://ppt.example.com/health
```

The health response reports `worker: ok` after the worker publishes its first heartbeat. The Codex
SDK thread uses native web search for topic research. Arbitrary shell networking remains disabled.
Image generation runs through the task-scoped `ppt_images` MCP tool, which keeps provider
credentials outside the model's command environment.

## Create A Task

The web application signs in with a username and password and keeps the session in an `HttpOnly`
cookie. Create a personal API key from the account menu for server-to-server access. The plaintext
key is shown once; PostgreSQL stores only its SHA-256 digest.

`POST /v1/jobs` accepts `multipart/form-data`, so topic-only and file-based tasks use the same
endpoint.

```bash
curl https://ppt.example.com/v1/jobs \
  -H "Authorization: Bearer $PPT_USER_API_KEY" \
  -F "prompt=Create a 10-slide product presentation" \
  -F "route=generate_pptx" \
  -F "files=@brief.pdf" \
  -F "references=@visual-style.png"
```

Use `files` for factual source material and `references` for visual direction. Reference files
may influence layout, typography, color behavior, and image treatment, but never presentation
facts. The Strategist may also select up to two cases from the built-in reviewed catalog. Selected
case ids and uploaded references are recorded in `control/references.json` and emitted as a
`references` task event.

Use `GET /v1/jobs/{id}/events` for SSE progress. Submit the blocking Strategist decision through
`POST /v1/jobs/{id}/confirmation`, then download outputs from the artifact endpoints.

## Task Recovery

Workers renew a Redis lease while processing a task. A task whose lease expires is returned to the
pending queue and resumes from its saved Codex thread and existing workspace. Queue insertion is
idempotent, so repeated API requests cannot create duplicate executions for the same task.

`GET /health` reports API storage health and whether at least one worker heartbeat is active.

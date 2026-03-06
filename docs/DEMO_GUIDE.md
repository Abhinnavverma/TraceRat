# TraceRat – Demo Guide

Run the full blast-radius prediction pipeline locally against any public
GitHub repository.  No production infrastructure or paid API keys required.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker & Docker Compose | v2+ | `docker compose version` |
| Python | 3.11+ | For the seeder / injector CLI tools |
| Git | any | To clone TraceRat itself |
| (optional) Node.js | 18+ | Only for live webhook tunnel via smee.io |

---

## 1. Clone & Configure

```bash
git clone https://github.com/<you>/TraceRat.git
cd TraceRat
cp .env.example .env
```

Edit `.env` and fill in at minimum:

| Variable | Where to get it |
|----------|-----------------|
| `LLM_API_KEY` | Free key from [Google AI Studio](https://aistudio.google.com/app/apikey) |

> **GitHub App** fields (`GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`) are only
> needed for live webhook mode.  The demo injector bypasses this entirely.

---

## 2. Install Seeder Dependencies

```bash
pip install -r tools/requirements.txt
```

---

## 3. Start the Stack

```bash
make up-build        # first time – builds all images
# or
make demo-up         # builds, waits, seeds in one command
```

Wait ~30 s for healthchecks.  Verify:

```bash
docker compose ps    # all containers should be "running" or "healthy"
```

### Service URLs

| Service | URL |
|---------|-----|
| API Gateway | http://localhost:8000/docs |
| Kafka UI | http://localhost:8080 |
| Neo4j Browser | http://localhost:7474 (neo4j / tracerat_dev) |
| Qdrant Dashboard | http://localhost:6333/dashboard |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / tracerat) |

---

## 4. Seed the Dependency Graph (Neo4j)

Pick any public Python repo.  FastAPI is a good default:

```bash
python tools/seed_repo.py --repo tiangolo/fastapi
```

This fetches the repo tree from the GitHub API, parses `import` statements
with `ast`, builds a module-level dependency graph, and writes `Component`
nodes + `DEPENDS_ON` edges into Neo4j with synthetic traffic weights.

Verify in Neo4j Browser:

```cypher
MATCH (n:Component) RETURN n LIMIT 25;
```

---

## 5. Seed Historical PRs (Qdrant)

```bash
python tools/seed_prs.py --repo tiangolo/fastapi --count 30
```

This fetches the last 30 closed/merged PRs, generates embeddings with a
local SentenceTransformer model, and upserts vectors + metadata into the
`pr-embeddings` collection in Qdrant.

Verify at http://localhost:6333/dashboard → Collections → `pr-embeddings`.

> First run downloads the `all-MiniLM-L6-v2` model (~80 MB).

---

## 6. Trigger a Prediction

### Option A – Inject a simulated event (no GitHub App needed)

```bash
python tools/inject_event.py --repo tiangolo/fastapi --pr 12345
```

This publishes a `PREvent` directly to the Kafka `pr-events` topic.
The diff-fetching-service will pull the diff from the public GitHub API
(no auth required for public repos).

Watch activity in:
- **Kafka UI** → Topics → `pr-events`, `diff-metadata`, `diff-content`,
  `delta-graph`, `pr-context`, `prediction-results`, `llm-prompts`
- **Grafana** → TraceRat dashboard → Kafka message counters
- **API Gateway** → `GET /results` or `GET /results/<event_id>`

### Option B – Live webhook (requires GitHub App)

1. Register a free GitHub App at https://github.com/settings/apps
   - Webhook URL: `https://smee.io/<your-channel>`
   - Permissions: Pull Requests → Read
   - Events: Pull request
2. Download the PEM key → `./secrets/github-app.pem`
3. Set `GITHUB_APP_ID` and `GITHUB_WEBHOOK_SECRET` in `.env`
4. Install the App on the target repo
5. Start a webhook tunnel:
   ```bash
   npx smee-client -u https://smee.io/<your-channel> -t http://localhost:8000/webhook
   ```
6. Open a real PR on the repo — the pipeline triggers automatically.

---

## 7. View Results

### API

```bash
# List all results
curl http://localhost:8000/results | python -m json.tool

# Single result
curl http://localhost:8000/results/<event_id> | python -m json.tool
```

### Grafana Dashboard

Open http://localhost:3000 → **TraceRat** dashboard.

Panels include:
- Service health (up/down)
- Kafka message rates (produced / consumed)
- HTTP request latency (p95)
- Prediction duration (p50 / p95 / p99)
- GitHub API request rate
- Pipeline flow overview

---

## 8. Teardown

```bash
make down          # stop containers, keep data
make down-clean    # stop containers and delete all volumes
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Kafka consumers not picking up messages | Check `docker compose logs kafka` — broker might still be starting. Wait for healthcheck. |
| `seed_repo.py` fails with 403 | GitHub API rate limit. Set `GITHUB_TOKEN` env var or wait. |
| Embeddings take forever | First run downloads the model. Subsequent runs are instant. |
| Neo4j connection refused | Wait for healthcheck: `docker compose ps neo4j`. |
| LLM service returns errors | Verify `LLM_API_KEY` in `.env`. Free Gemini keys have a quota (~15 RPM). |

---

## Makefile Cheat-Sheet

```bash
make up-build          # build + start everything
make demo-up           # build, start, wait, seed
make seed-graph        # seed Neo4j only  (SEED_REPO=owner/repo)
make seed-prs          # seed Qdrant only (SEED_REPO=owner/repo)
make seed-all          # seed both
make demo-trigger      # inject a test PR event
make test-all          # run all 298 tests across 7 services
make logs              # tail all logs
make logs-llm-service  # tail one service
make down-clean        # full teardown
```

Override the target repo:

```bash
make seed-all SEED_REPO=pallets/flask SEED_PR_COUNT=50
```

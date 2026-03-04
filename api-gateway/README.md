# API Gateway

Entry point for the TraceRat blast radius prediction system.

## Responsibilities

- Receive GitHub webhook events (PR opened/updated)
- Verify webhook signatures (GitHub App)
- Publish PR events to Kafka
- Post prediction results as PR comments

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /webhook | Receive GitHub webhooks |
| POST | /results | Receive prediction results (internal) |
| GET | /health | Health check |
| GET | /ready | Readiness check |
| GET | /metrics | Prometheus metrics |

## Running

```bash
cd api-gateway
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

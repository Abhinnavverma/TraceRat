"""GitHub webhook endpoint.

Receives GitHub PR webhooks, verifies signatures,
filters for relevant PR events, and publishes to Kafka.
"""

import uuid

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.dependencies import get_github_auth, get_kafka_producer
from app.models import PRAction, PREvent, WebhookPayload
from shared.logging import get_logger
from shared.metrics import webhook_events_total

logger = get_logger("webhook")

router = APIRouter(tags=["webhook"])

# PR actions we process
RELEVANT_ACTIONS = {PRAction.OPENED, PRAction.SYNCHRONIZE, PRAction.REOPENED}


@router.post(
    "/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive GitHub webhook events",
)
async def handle_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    """Process an incoming GitHub webhook.

    1. Verify the HMAC-SHA256 signature using the webhook secret.
    2. Filter for pull_request events with relevant actions.
    3. Build a PREvent and publish it to Kafka.
    4. Return 202 Accepted.
    """
    body = await request.body()

    # --- Signature verification ---
    github_auth = get_github_auth()
    if not x_hub_signature_256:
        logger.warning("Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature header",
        )

    if not github_auth.verify_signature(body, x_hub_signature_256):
        logger.warning("Invalid webhook signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    # --- Event filtering ---
    if x_github_event != "pull_request":
        logger.info("Ignoring non-PR event", event_type=x_github_event)
        webhook_events_total.labels(
            event_type=x_github_event or "unknown", action="ignored"
        ).inc()
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ignored", "reason": f"Event type '{x_github_event}' not processed"},
        )

    # --- Parse payload ---
    try:
        payload = WebhookPayload.model_validate_json(body)
    except Exception as e:
        logger.error("Failed to parse webhook payload", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid payload",
        )

    action = payload.action
    webhook_events_total.labels(event_type="pull_request", action=action).inc()

    if action not in {a.value for a in RELEVANT_ACTIONS}:
        logger.info("Ignoring PR action", action=action)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "ignored", "reason": f"Action '{action}' not processed"},
        )

    # --- Build internal event ---
    if not payload.pull_request or not payload.repository:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing pull_request or repository in payload",
        )

    installation_id = payload.installation.id if payload.installation else 0

    pr_event = PREvent(
        event_id=x_github_delivery or str(uuid.uuid4()),
        repo_full_name=payload.repository.full_name,
        repo_id=payload.repository.id,
        pr_number=payload.pull_request.number,
        pr_title=payload.pull_request.title,
        action=action,
        author=payload.pull_request.user.login,
        head_sha=payload.pull_request.head.sha,
        base_ref=payload.pull_request.base.ref,
        head_ref=payload.pull_request.head.ref,
        diff_url=payload.pull_request.diff_url,
        html_url=payload.pull_request.html_url,
        installation_id=installation_id,
        changed_files=payload.pull_request.changed_files,
        additions=payload.pull_request.additions,
        deletions=payload.pull_request.deletions,
    )

    # --- Publish to Kafka ---
    producer = get_kafka_producer()
    await producer.send_pr_event(pr_event.model_dump())

    logger.info(
        "PR event published to Kafka",
        repo=pr_event.repo_full_name,
        pr_number=pr_event.pr_number,
        action=action,
        event_id=pr_event.event_id,
    )

    return {
        "status": "accepted",
        "event_id": pr_event.event_id,
        "pr": f"{pr_event.repo_full_name}#{pr_event.pr_number}",
    }

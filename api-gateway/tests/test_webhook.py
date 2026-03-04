"""Tests for the webhook endpoint."""

import json

from tests.conftest import make_signature, sample_pr_webhook_payload


class TestWebhookSignatureVerification:
    """Test webhook signature validation."""

    def test_missing_signature_returns_401(self, client):
        """Webhook without signature header should be rejected."""
        payload = json.dumps(sample_pr_webhook_payload()).encode()
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401
        assert "Missing signature" in response.json()["detail"]

    def test_invalid_signature_returns_401(self, client):
        """Webhook with wrong signature should be rejected."""
        payload = json.dumps(sample_pr_webhook_payload()).encode()
        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]

    def test_valid_signature_accepted(self, client):
        """Webhook with correct signature should be accepted."""
        payload_dict = sample_pr_webhook_payload()
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Delivery": "test-delivery-123",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "octocat/hello-world#42" in data["pr"]


class TestWebhookEventFiltering:
    """Test event type and action filtering."""

    def test_non_pr_event_ignored(self, client):
        """Non-pull_request events should be ignored."""
        payload = json.dumps({"action": "created"}).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_irrelevant_pr_action_ignored(self, client):
        """PR actions like 'closed' should be ignored."""
        payload_dict = sample_pr_webhook_payload(action="closed")
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_opened_action_accepted(self, client):
        """PR 'opened' action should be processed."""
        payload_dict = sample_pr_webhook_payload(action="opened")
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202

    def test_synchronize_action_accepted(self, client):
        """PR 'synchronize' action should be processed."""
        payload_dict = sample_pr_webhook_payload(action="synchronize")
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202

    def test_reopened_action_accepted(self, client):
        """PR 'reopened' action should be processed."""
        payload_dict = sample_pr_webhook_payload(action="reopened")
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202


class TestWebhookKafkaPublishing:
    """Test that webhook publishes correct events to Kafka."""

    def test_pr_event_published_to_kafka(self, client, mock_kafka_producer):
        """Accepted PR event should be published to Kafka."""
        payload_dict = sample_pr_webhook_payload()
        payload = json.dumps(payload_dict).encode()
        signature = make_signature(payload)

        response = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Delivery": "delivery-001",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202

        # Verify Kafka producer was called
        mock_kafka_producer.send_pr_event.assert_called_once()

        # Verify the event payload
        call_args = mock_kafka_producer.send_pr_event.call_args[0][0]
        assert call_args["repo_full_name"] == "octocat/hello-world"
        assert call_args["pr_number"] == 42
        assert call_args["action"] == "opened"
        assert call_args["head_sha"] == "abc123def456"
        assert call_args["author"] == "octocat"
        assert call_args["installation_id"] == 99999

    def test_ignored_event_not_published(self, client, mock_kafka_producer):
        """Ignored events should NOT be published to Kafka."""
        payload = json.dumps({"action": "created"}).encode()
        signature = make_signature(payload)

        client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": signature,
                "Content-Type": "application/json",
            },
        )

        mock_kafka_producer.send_pr_event.assert_not_called()

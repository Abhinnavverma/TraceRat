"""Tests for the SignalCorrelator — in-memory two-stream join buffer."""



from app.services.correlator import SignalCorrelator

from tests.conftest import SAMPLE_DELTA_GRAPH, SAMPLE_PR_CONTEXT


class TestIngest:
    """Tests for SignalCorrelator.ingest()."""

    def test_first_signal_returns_none(self):
        """Ingesting the first signal should return None (waiting for pair)."""
        c = SignalCorrelator(ttl_seconds=60)
        result = c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)
        assert result is None
        assert c.buffer_size == 1

    def test_second_signal_completes_bundle(self):
        """Ingesting the second signal should return the complete bundle."""
        c = SignalCorrelator(ttl_seconds=60)
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)
        bundle = c.ingest("pr-context", "evt-1", SAMPLE_PR_CONTEXT)

        assert bundle is not None
        assert bundle.event_id == "evt-1"
        assert bundle.delta_graph == SAMPLE_DELTA_GRAPH
        assert bundle.pr_context == SAMPLE_PR_CONTEXT
        assert bundle.degraded is False
        assert c.buffer_size == 0  # removed from buffer

    def test_reverse_order_completes_bundle(self):
        """pr-context first, delta-graph second should also work."""
        c = SignalCorrelator(ttl_seconds=60)
        c.ingest("pr-context", "evt-2", SAMPLE_PR_CONTEXT)
        bundle = c.ingest("delta-graph", "evt-2", SAMPLE_DELTA_GRAPH)

        assert bundle is not None
        assert bundle.delta_graph == SAMPLE_DELTA_GRAPH
        assert bundle.pr_context == SAMPLE_PR_CONTEXT

    def test_duplicate_signal_ignored(self):
        """A duplicate delta-graph for the same event should return None."""
        c = SignalCorrelator(ttl_seconds=60)
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)
        result = c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)
        assert result is None
        assert c.buffer_size == 1

    def test_duplicate_pr_context_ignored(self):
        """A duplicate pr-context for the same event should return None."""
        c = SignalCorrelator(ttl_seconds=60)
        c.ingest("pr-context", "evt-1", SAMPLE_PR_CONTEXT)
        result = c.ingest("pr-context", "evt-1", SAMPLE_PR_CONTEXT)
        assert result is None
        assert c.buffer_size == 1

    def test_independent_events_tracked_separately(self):
        """Different event_ids should not interfere."""
        c = SignalCorrelator(ttl_seconds=60)
        c.ingest("delta-graph", "evt-A", SAMPLE_DELTA_GRAPH)
        c.ingest("pr-context", "evt-B", SAMPLE_PR_CONTEXT)
        assert c.buffer_size == 2

        bundle = c.ingest("pr-context", "evt-A", SAMPLE_PR_CONTEXT)
        assert bundle is not None
        assert bundle.event_id == "evt-A"
        assert c.buffer_size == 1  # evt-B still pending


class TestSweepExpired:
    """Tests for SignalCorrelator.sweep_expired()."""

    def test_returns_expired_bundles(self):
        """Bundles older than TTL should be swept."""
        c = SignalCorrelator(ttl_seconds=0)  # immediate expiration
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)

        expired = c.sweep_expired()
        assert len(expired) == 1
        assert expired[0].event_id == "evt-1"
        assert expired[0].degraded is True
        assert "pr-context" in expired[0].missing_signals
        assert c.buffer_size == 0

    def test_non_expired_entries_remain(self):
        """Bundles younger than TTL should not be swept."""
        c = SignalCorrelator(ttl_seconds=3600)
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)

        expired = c.sweep_expired()
        assert len(expired) == 0
        assert c.buffer_size == 1

    def test_missing_signals_populated_for_delta_graph_only(self):
        """When only delta-graph arrived, missing should list pr-context."""
        c = SignalCorrelator(ttl_seconds=0)
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)

        expired = c.sweep_expired()
        assert expired[0].missing_signals == ["pr-context"]
        assert expired[0].delta_graph is not None
        assert expired[0].pr_context is None

    def test_missing_signals_populated_for_context_only(self):
        """When only pr-context arrived, missing should list delta-graph."""
        c = SignalCorrelator(ttl_seconds=0)
        c.ingest("pr-context", "evt-1", SAMPLE_PR_CONTEXT)

        expired = c.sweep_expired()
        assert expired[0].missing_signals == ["delta-graph"]
        assert expired[0].delta_graph is None
        assert expired[0].pr_context is not None

    def test_empty_buffer_returns_empty(self):
        """Sweeping an empty buffer should return nothing."""
        c = SignalCorrelator(ttl_seconds=0)
        assert c.sweep_expired() == []

    def test_buffer_size_property(self):
        """buffer_size should reflect the number of pending entries."""
        c = SignalCorrelator(ttl_seconds=60)
        assert c.buffer_size == 0
        c.ingest("delta-graph", "evt-1", SAMPLE_DELTA_GRAPH)
        assert c.buffer_size == 1
        c.ingest("delta-graph", "evt-2", SAMPLE_DELTA_GRAPH)
        assert c.buffer_size == 2

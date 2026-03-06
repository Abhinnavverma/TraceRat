"""Tests for the SkipFilter service."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.skip_filter import SkipFilter
from tests.conftest import SAMPLE_DEGRADED_PREDICTION, SAMPLE_PREDICTION


class TestSkipFilter:
    """Tests for SkipFilter.should_skip()."""

    def setup_method(self):
        self.skip_filter = SkipFilter()

    def test_does_not_skip_normal_prediction(self):
        assert self.skip_filter.should_skip(SAMPLE_PREDICTION) is False

    def test_skips_degraded_prediction(self):
        assert self.skip_filter.should_skip(SAMPLE_DEGRADED_PREDICTION) is True

    def test_does_not_skip_when_degraded_false(self):
        prediction = {"event_id": "evt-x", "degraded": False}
        assert self.skip_filter.should_skip(prediction) is False

    def test_does_not_skip_when_degraded_missing(self):
        prediction = {"event_id": "evt-y"}
        assert self.skip_filter.should_skip(prediction) is False

    def test_skips_when_degraded_true(self):
        prediction = {"event_id": "evt-z", "degraded": True, "missing_signals": ["delta-graph"]}
        assert self.skip_filter.should_skip(prediction) is True

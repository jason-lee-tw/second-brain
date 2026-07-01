from unittest.mock import AsyncMock, MagicMock

import pytest
from ragas.metrics.result import MetricResult


@pytest.fixture
def mock_metric():
    """Factory fixture: mock_metric(0.85) -> MagicMock with .ascore returning
    that value."""

    def _make(value: float) -> MagicMock:
        metric = MagicMock()
        metric.ascore = AsyncMock(return_value=MetricResult(value=value))
        return metric

    return _make

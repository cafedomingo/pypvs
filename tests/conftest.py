import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def clock(monkeypatch):
    """Stands in for time.monotonic(); move time forward with clock.now += s."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(time, "monotonic", lambda: clock.now)
    return clock

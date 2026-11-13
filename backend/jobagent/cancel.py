"""Cooperative cancellation for background tasks.

The task runner gives each thread a stop event. Long loops call `requested()` between units of work (one source,
one job, one application) and wind down cleanly, so a stop never interrupts a half-filled form or a DB write.
Outside a task (CLI runs) there is no event and `requested()` is always False.
"""

from __future__ import annotations

import threading

_local = threading.local()


def bind(event: threading.Event | None) -> None:
    _local.event = event


def requested() -> bool:
    ev: threading.Event | None = getattr(_local, "event", None)
    return bool(ev and ev.is_set())

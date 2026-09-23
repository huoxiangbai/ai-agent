"""Pin the process timezone for all unit tests.

The Java reference serializes ``LocalDateTime.atZone(ZoneId.systemDefault())``
epoch millis; the recorded golden was captured under ``Asia/Shanghai`` (R-07).
Deterministic tests must not depend on the host timezone.
"""

from __future__ import annotations

import os
import time


def pytest_configure() -> None:
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()

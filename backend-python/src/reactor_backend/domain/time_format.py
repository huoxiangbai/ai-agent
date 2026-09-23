"""Jackson-compatible time serialization.

Java serializes ``LocalDateTime`` through Jackson's default ``ISO_LOCAL_DATE_TIME``
shape and ``long`` epoch millis through ``String.valueOf``. Both are contract data:
zero-millisecond timestamps omit the fraction, non-zero milliseconds use exactly
three digits. ``datetime.isoformat()`` emits microseconds and must not be used.
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_local_datetime(value: datetime | None) -> str | None:
    """Serialize a naive LocalDateTime the way Jackson does (ISO-8601)."""
    if value is None:
        return None
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    micros = value.microsecond
    if micros == 0:
        return base
    # The ledger stores DATETIME(3); Jackson therefore always sees millisecond
    # precision and emits exactly three fraction digits. Truncate — never round
    # up to a 6-digit ``isoformat()`` shape.
    millis = micros // 1000
    return f"{base}.{millis:03d}"


def epoch_millis_string(value: datetime | None, *, now: datetime | None = None) -> str:
    """``String.valueOf(localDateTime.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli())``.

    ``ZoneId.systemDefault()`` is the JVM default; the Python process must run with
    ``TZ=Asia/Shanghai`` to match the recorded golden (R-07). Naive values are
    interpreted in the local timezone via ``astimezone`` semantics of aware
    conversion — callers pass naive datetimes and we attach the local zone.
    """
    if value is None:
        fallback = now if now is not None else datetime.now(tz=UTC)
        return str(int(fallback.timestamp() * 1000))
    if value.tzinfo is None:
        local = datetime.now(tz=UTC).astimezone().tzinfo
        value = value.replace(tzinfo=local)
    return str(int(value.timestamp() * 1000))

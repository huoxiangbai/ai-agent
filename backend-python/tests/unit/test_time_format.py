from __future__ import annotations

from datetime import UTC, datetime

from reactor_backend.domain.time_format import (
    epoch_millis_string,
    format_local_datetime,
)


def test_zero_millis_omits_fraction() -> None:
    assert format_local_datetime(datetime(2026, 1, 2, 10, 0, 0)) == "2026-01-02T10:00:00"


def test_millis_use_three_digits() -> None:
    assert (
        format_local_datetime(datetime(2026, 1, 2, 10, 0, 0, 1000))
        == "2026-01-02T10:00:00.001"
    )
    assert (
        format_local_datetime(datetime(2026, 1, 2, 10, 0, 0, 123000))
        == "2026-01-02T10:00:00.123"
    )


def test_sub_millisecond_degrades_to_three_digits() -> None:
    # datetime.isoformat() would emit 6 digits — that is a contract failure
    assert (
        format_local_datetime(datetime(2026, 1, 2, 10, 0, 0, 123456))
        == "2026-01-02T10:00:00.123"
    )


def test_none_passes_through() -> None:
    assert format_local_datetime(None) is None


def test_epoch_millis_matches_golden_fixture() -> None:
    # golden frame 1: finished_at 2026-01-01 09:00:02 Asia/Shanghai → "1767229202000"
    # golden frame 2: run.finished_at 2026-01-01 09:00:05 → "1767229205000"
    # The assertion below is only valid under TZ=Asia/Shanghai (R-07). We pin the
    # expected value relative to a known-aw
    aware = datetime(2026, 1, 1, 1, 0, 2, tzinfo=UTC)
    assert epoch_millis_string(aware) == "1767229202000"
    aware2 = datetime(2026, 1, 1, 1, 0, 5, tzinfo=UTC)
    assert epoch_millis_string(aware2) == "1767229205000"


def test_epoch_millis_none_uses_now() -> None:
    fixed = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert epoch_millis_string(None, now=fixed) == "1767225600000"


def test_naive_datetime_uses_local_zone() -> None:
    # under TZ=Asia/Shanghai (set by test_replay_projector / conftest), 09:00:00
    # naive is 01:00:00 UTC → 1767229200000
    assert epoch_millis_string(datetime(2026, 1, 1, 9, 0, 0)) == "1767229200000"

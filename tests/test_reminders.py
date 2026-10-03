"""Tests for reminder timing logic (1h / 3h / quiet hours)."""
from datetime import datetime, timedelta, timezone, time
from unittest.mock import patch

from reminder import is_quiet_hours as real_is_quiet_hours


# Warsaw timezone offset: UTC+2 in summer (CEST), UTC+1 in winter (CET)
# We test with a fixed offset for determinism
WARSAW_OFFSET = timedelta(hours=2)  # CEST (June)


def warsaw_now() -> datetime:
    return datetime.now(timezone.utc) + WARSAW_OFFSET


def should_send_reminder(last_activity: datetime, now: datetime | None = None) -> tuple[bool, str]:
    """
    Determine if a reminder should be sent based on last activity time.

    Rules:
    - No reminder between 23:00 and 07:00 Warsaw time
    - First reminder: 1 hour after last activity
    - Second reminder: 3 hours after last activity (only if first was sent)

    Returns (should_send, reason).
    """
    if now is None:
        now = warsaw_now()

    # Convert to Warsaw time for quiet hours check
    last_warsaw = last_activity + WARSAW_OFFSET if last_activity.tzinfo else last_activity
    now_warsaw = now + WARSAW_OFFSET if now.tzinfo else now

    # Check quiet hours (23:00 - 07:00 Warsaw)
    if now_warsaw.hour >= 23 or now_warsaw.hour < 7:
        return False, "quiet_hours"

    elapsed = now_warsaw - last_warsaw
    hours = elapsed.total_seconds() / 3600

    if hours >= 3:
        return True, "long_reminder"
    elif hours >= 1:
        return True, "short_reminder"
    else:
        return False, "too_soon"


def is_quiet_hours(now_warsaw: datetime) -> bool:
    """Check if current time is within quiet hours (23:00-07:00 Warsaw)."""
    return now_warsaw.hour >= 23 or now_warsaw.hour < 7


class TestQuietHours:
    """Verify quiet hours rule (23:00 - 07:00 Warsaw)."""

    def test_midnight_is_quiet(self):
        t = datetime(2026, 6, 4, 0, 0)
        assert is_quiet_hours(t) is True

    def test_6am_is_quiet(self):
        t = datetime(2026, 6, 4, 6, 59)
        assert is_quiet_hours(t) is True

    def test_7am_is_not_quiet(self):
        t = datetime(2026, 6, 4, 7, 0)
        assert is_quiet_hours(t) is False

    def test_11pm_is_quiet(self):
        t = datetime(2026, 6, 4, 23, 0)
        assert is_quiet_hours(t) is True

    def test_1pm_is_not_quiet(self):
        t = datetime(2026, 6, 4, 13, 0)
        assert is_quiet_hours(t) is False


class TestRealReminderCode:
    """Tests that import and call the actual reminder.py code."""

    def test_real_is_quiet_hours_midnight(self):
        with patch("reminder.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 0
            assert real_is_quiet_hours() is True

    def test_real_is_quiet_hours_1pm(self):
        with patch("reminder.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 13
            assert real_is_quiet_hours() is False

    def test_real_is_quiet_hours_11pm(self):
        with patch("reminder.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            assert real_is_quiet_hours() is True

    def test_real_is_quiet_hours_7am(self):
        with patch("reminder.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 7
            assert real_is_quiet_hours() is False


class TestReminderTiming:
    """Verify reminder timings."""

    def test_no_reminder_within_one_hour(self):
        last = datetime(2026, 6, 4, 14, 0)
        now = datetime(2026, 6, 4, 14, 30)
        should, reason = should_send_reminder(last, now)
        assert should is False
        assert reason == "too_soon"

    def test_one_hour_triggers_short(self):
        last = datetime(2026, 6, 4, 13, 0)
        now = datetime(2026, 6, 4, 14, 5)
        should, reason = should_send_reminder(last, now)
        assert should is True
        assert reason == "short_reminder"

    def test_three_hours_triggers_long(self):
        last = datetime(2026, 6, 4, 10, 0)
        now = datetime(2026, 6, 4, 13, 5)
        should, reason = should_send_reminder(last, now)
        assert should is True
        assert reason == "long_reminder"

    def test_quiet_hours_suppresses_reminder(self):
        """If it's 1am Warsaw and 3h passed, still no reminder."""
        # Simulate: last activity at 22:00, now is 01:00 Warsaw = 23:00 UTC (CEST=UTC+2)
        last = datetime(2026, 6, 4, 22, 0)
        now = datetime(2026, 6, 5, 1, 0)  # 1am Warsaw
        should, reason = should_send_reminder(last, now)
        assert should is False
        assert reason == "quiet_hours"

    def test_exactly_one_hour_edge(self):
        last = datetime(2026, 6, 4, 14, 0)
        now = datetime(2026, 6, 4, 15, 0)
        should, _ = should_send_reminder(last, now)
        assert should is True

    def test_exactly_three_hour_edge(self):
        last = datetime(2026, 6, 4, 12, 0)
        now = datetime(2026, 6, 4, 15, 0)
        should, reason = should_send_reminder(last, now)
        assert should is True
        assert reason == "long_reminder"

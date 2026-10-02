"""Tests for business-hours response time calculation."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from crm_analysis import CrmChannel, CrmMessage, compute_channel_response_times
from crm_response_time import (
    WorkSchedule,
    is_on_calendar_day,
    is_work_moment,
    working_seconds_between,
    _get_tz,
)

SCHEDULE = WorkSchedule()
TB = _get_tz("Asia/Tbilisi")


def _tb(y, m, d, h, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=TB)


class TestCrmResponseTime(unittest.TestCase):
    def test_is_work_moment_weekday(self):
        self.assertTrue(is_work_moment(_tb(2026, 7, 14, 12, 0), SCHEDULE))
        self.assertFalse(is_work_moment(_tb(2026, 7, 14, 9, 59), SCHEDULE))
        self.assertFalse(is_work_moment(_tb(2026, 7, 14, 18, 0), SCHEDULE))

    def test_is_work_moment_weekend(self):
        self.assertFalse(is_work_moment(_tb(2026, 7, 18, 12, 0), SCHEDULE))

    def test_friday_to_monday_working_seconds(self):
        client = _tb(2026, 7, 17, 17, 55)
        manager = _tb(2026, 7, 20, 10, 5)
        self.assertEqual(working_seconds_between(client, manager, SCHEDULE), 600.0)

    def test_saturday_to_monday(self):
        client = _tb(2026, 7, 18, 12, 0)
        manager = _tb(2026, 7, 20, 10, 30)
        self.assertEqual(working_seconds_between(client, manager, SCHEDULE), 1800.0)

    def test_same_day_within_shift(self):
        client = _tb(2026, 7, 14, 10, 0)
        manager = _tb(2026, 7, 14, 10, 2)
        self.assertEqual(working_seconds_between(client, manager, SCHEDULE), 120.0)

    def test_is_on_calendar_day(self):
        self.assertTrue(is_on_calendar_day(_tb(2026, 8, 5, 11, 0), date(2026, 8, 5), SCHEDULE))
        self.assertFalse(is_on_calendar_day(_tb(2026, 8, 4, 23, 0), date(2026, 8, 5), SCHEDULE))


class TestDayScopedResponsePairs(unittest.TestCase):
    def _channel(self) -> CrmChannel:
        # Three client→manager pairs across days; long historical pause on Aug 1.
        msgs = [
            CrmMessage("1", "hi old", "FRIEND_MESSAGE", _tb(2026, 8, 1, 10, 0), "c1", "T", "FB"),
            CrmMessage("2", "reply old", "YOUR_MESSAGE", _tb(2026, 8, 3, 12, 0), "c1", "T", "FB"),
            CrmMessage("3", "hi work", "FRIEND_MESSAGE", _tb(2026, 8, 5, 11, 0), "c1", "T", "FB"),
            CrmMessage("4", "ok", "YOUR_MESSAGE", _tb(2026, 8, 5, 11, 1), "c1", "T", "FB"),
            CrmMessage("5", "hi night", "FRIEND_MESSAGE", _tb(2026, 8, 5, 20, 0), "c1", "T", "FB"),
            CrmMessage("6", "ok2", "YOUR_MESSAGE", _tb(2026, 8, 5, 20, 5), "c1", "T", "FB"),
        ]
        return CrmChannel("c1", "Test", "FB", msgs)

    def test_on_date_filters_old_pairs(self):
        pairs, rt = compute_channel_response_times(
            self._channel(), SCHEDULE, on_date=date(2026, 8, 5)
        )
        self.assertEqual(len(pairs), 2)
        self.assertEqual(rt.responses_count, 2)
        # Old multi-day pause must not inflate max
        self.assertLess(rt.max_seconds or 0, 3600)

    def test_work_and_off_buckets_preserved(self):
        pairs, rt = compute_channel_response_times(
            self._channel(), SCHEDULE, on_date=date(2026, 8, 5)
        )
        buckets = {p.bucket for p in pairs}
        self.assertEqual(buckets, {"working", "off_hours"})
        self.assertEqual(rt.responses_count_work, 1)
        self.assertEqual(rt.responses_count_off, 1)
        # Work pair: 60s wall, within SLA 120 → no work SLA breach
        self.assertEqual(rt.over_sla_work, 0)
        # Off pair: 300s wall < 900 → no off SLA breach
        self.assertEqual(rt.over_sla_off, 0)

    def test_without_on_date_includes_history(self):
        pairs, _ = compute_channel_response_times(self._channel(), SCHEDULE)
        self.assertEqual(len(pairs), 3)


if __name__ == "__main__":
    unittest.main()

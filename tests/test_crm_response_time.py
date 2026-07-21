"""Tests for business-hours response time calculation."""

from __future__ import annotations

import unittest
from datetime import datetime

from crm_response_time import WorkSchedule, is_work_moment, working_seconds_between, _get_tz

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


if __name__ == "__main__":
    unittest.main()

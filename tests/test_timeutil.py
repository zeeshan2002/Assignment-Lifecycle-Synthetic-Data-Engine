"""Time-zone engine and lateness rules."""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generator.workflow import lateness, boundary_kinds
from src.timeutil import ZONES, local_to_utc, utc_offset_minutes, utc_to_local

UTC = timezone.utc


class TimeZoneTests(unittest.TestCase):
    def test_us_dst_boundaries_2026(self):
        # DST starts Sun 2026-03-08 02:00 local; ends Sun 2026-11-01 02:00 local
        self.assertEqual(utc_offset_minutes("America/New_York", datetime(2026, 3, 8, 6, 59, tzinfo=UTC)), -300)
        self.assertEqual(utc_offset_minutes("America/New_York", datetime(2026, 3, 8, 7, 0, tzinfo=UTC)), -240)
        self.assertEqual(utc_offset_minutes("America/New_York", datetime(2026, 11, 1, 5, 59, tzinfo=UTC)), -240)
        self.assertEqual(utc_offset_minutes("America/New_York", datetime(2026, 11, 1, 6, 0, tzinfo=UTC)), -300)
        self.assertEqual(utc_offset_minutes("America/Los_Angeles", datetime(2026, 7, 1, tzinfo=UTC)), -420)

    def test_eu_dst_boundaries_2026(self):
        self.assertEqual(utc_offset_minutes("Europe/London", datetime(2026, 3, 29, 0, 59, tzinfo=UTC)), 0)
        self.assertEqual(utc_offset_minutes("Europe/London", datetime(2026, 3, 29, 1, 0, tzinfo=UTC)), 60)
        self.assertEqual(utc_offset_minutes("Europe/London", datetime(2026, 10, 25, 1, 0, tzinfo=UTC)), 0)

    def test_fixed_zones(self):
        self.assertEqual(utc_offset_minutes("Asia/Kolkata", datetime(2026, 7, 1, tzinfo=UTC)), 330)
        self.assertEqual(utc_offset_minutes("UTC", datetime(2026, 7, 1, tzinfo=UTC)), 0)

    def test_local_to_utc_round_trip(self):
        for tz in ZONES:
            for month in (1, 3, 4, 7, 10, 11, 12):
                local = datetime(2026, month, 14, 23, 59, 0)
                self.assertEqual(utc_to_local(tz, local_to_utc(tz, local)), local, (tz, month))

    def test_deadline_one_day_apart_across_dst_is_23_hours(self):
        a = local_to_utc("America/New_York", datetime(2026, 3, 7, 23, 59))
        b = local_to_utc("America/New_York", datetime(2026, 3, 8, 23, 59))
        self.assertEqual(b - a, timedelta(hours=23))

    def test_matches_zoneinfo_when_available(self):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("America/New_York")
        except Exception:
            self.skipTest("system tz database not available")
        for tz in ZONES:
            z = ZoneInfo(tz)
            t = datetime(2026, 1, 1, tzinfo=UTC)
            while t < datetime(2027, 1, 1, tzinfo=UTC):
                self.assertEqual(utc_offset_minutes(tz, t), int(t.astimezone(z).utcoffset().total_seconds() // 60), (tz, t))
                t += timedelta(hours=6)


class LatenessTests(unittest.TestCase):
    D = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    def test_on_time_at_deadline(self):
        self.assertEqual(lateness(self.D, self.D, 0), (False, 0))

    def test_one_second_late(self):
        self.assertEqual(lateness(self.D + timedelta(seconds=1), self.D, 0), (True, 1))

    def test_grace_period(self):
        self.assertEqual(lateness(self.D + timedelta(minutes=10), self.D, 600), (False, 0))
        self.assertEqual(lateness(self.D + timedelta(minutes=10, seconds=1), self.D, 600), (True, 1))

    def test_day_boundaries(self):
        self.assertEqual(lateness(self.D + timedelta(hours=24), self.D, 0), (True, 1))
        self.assertEqual(lateness(self.D + timedelta(hours=24, seconds=1), self.D, 0), (True, 2))
        self.assertEqual(lateness(self.D + timedelta(days=5), self.D, 0), (True, 5))

    def test_boundary_kinds_cover_grace(self):
        self.assertIn("AT_GRACE_EDGE", [k for k, _ in boundary_kinds(600)])
        self.assertNotIn("AT_GRACE_EDGE", [k for k, _ in boundary_kinds(0)])


if __name__ == "__main__":
    unittest.main()

"""
Unit tests for the rule-based layer. Run with:
    python3 -m unittest discover -s tests -v
from the repo root (with app/ on the path, handled below).
"""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import patterns  # noqa: E402


def make_event(activity_type, days_ago, hour=12, duration=30):
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    ts = ts.replace(hour=hour, minute=0, second=0, microsecond=0)
    return {"activity_type": activity_type, "timestamp": ts.isoformat(), "duration_minutes": duration}


class TestStreak(unittest.TestCase):
    def test_current_streak_consecutive_days(self):
        events = [make_event("run", d) for d in range(4)]  # today, -1, -2, -3
        stats = patterns.analyze(events)
        self.assertEqual(stats["activity_types"]["run"]["current_streak_days"], 4)

    def test_streak_broken_by_gap(self):
        events = [make_event("run", 0), make_event("run", 1), make_event("run", 5)]
        stats = patterns.analyze(events)
        self.assertEqual(stats["activity_types"]["run"]["current_streak_days"], 2)

    def test_no_events_no_crash(self):
        stats = patterns.analyze([])
        self.assertEqual(stats["total_events"], 0)
        self.assertEqual(stats["activity_types"], {})


class TestTrend(unittest.TestCase):
    def test_trend_requires_two_full_weeks(self):
        events = [make_event("run", d) for d in range(3)]  # only 3 days of history
        stats = patterns.analyze(events)
        self.assertIsNone(stats["activity_types"]["run"]["trend_week_over_week"])

    def test_trend_detects_increase(self):
        # 6 events in the last 7 days, 2 events in the 7 days before that
        events = [make_event("run", d) for d in range(6)] + [make_event("run", d) for d in (8, 10)]
        stats = patterns.analyze(events)
        trend = stats["activity_types"]["run"]["trend_week_over_week"]
        self.assertIsNotNone(trend)
        self.assertGreater(trend["pct_change"], 0)


class TestAnomalies(unittest.TestCase):
    def test_flags_spike_day(self):
        # 10 quiet days with 1 event, one day with 6 events
        events = [make_event("read", d) for d in range(1, 11)]
        events += [make_event("read", 0, hour=h) for h in range(6)]  # 6 events "today"
        stats = patterns.analyze(events)
        anomalies = stats["activity_types"]["read"]["anomalous_days"]
        self.assertTrue(any(a["count"] == 6 for a in anomalies))


if __name__ == "__main__":
    unittest.main()

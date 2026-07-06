"""
patterns.py
The rule-based half of the system. Takes raw activity events for a user and
computes concrete, verifiable statistics: streaks, trends, time-of-day
behavior, and anomalies. Nothing in here is generated or guessed - every
number is derived directly from the stored events.

This module has zero knowledge of the LLM. It could be unit tested and used
standalone. The LLM layer (llm.py) only ever sees the OUTPUT of this module,
never the raw events - that keeps the "facts" grounded in code, not in a
model's imagination.

CHANGE LOG (post-review):
- trend_week_over_week now includes a `reliable` flag. A percentage change
  computed from a tiny prior-week count (e.g. 1 -> 7 events) is arithmetically
  correct but not a meaningful "trend" - it's noise dressed up as a stat. The
  LLM layer is instructed to ignore pct_change when reliable is False and
  prefer streak/consistency/anomaly facts instead.
- Added occurrence_last_7_days: "X of the last 7 days had at least one event"
  - a much more human-legible consistency signal than a raw event count.
"""
from collections import defaultdict
from datetime import datetime, timedelta
import statistics

# Below this many prior-week events, a week-over-week percentage is
# considered unreliable (e.g. 1 -> 7 events = "600%" but is really just
# "went from almost nothing to something").
MIN_PRIOR_COUNT_FOR_RELIABLE_TREND = 3


def _parse_ts(ts):
    # Accept both "...Z" and naive ISO strings.
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _daily_counts(events):
    """Map date -> count of events on that date."""
    counts = defaultdict(int)
    for e in events:
        d = _parse_ts(e["timestamp"]).date()
        counts[d] += 1
    return counts


def _current_streak(daily_counts):
    """Consecutive days up to the most recent day with at least one event."""
    if not daily_counts:
        return 0
    days = sorted(daily_counts.keys())
    streak = 1
    for i in range(len(days) - 1, 0, -1):
        if (days[i] - days[i - 1]).days == 1:
            streak += 1
        else:
            break
    return streak


def _trend_last_vs_previous_week(daily_counts):
    """% change in event count: most recent 7 days vs the 7 days before that.
    Includes a `reliable` flag - see MIN_PRIOR_COUNT_FOR_RELIABLE_TREND above."""
    if not daily_counts:
        return None
    last_day = max(daily_counts.keys())
    recent_window = [last_day - timedelta(days=i) for i in range(7)]
    prior_window = [last_day - timedelta(days=i) for i in range(7, 14)]
    recent_total = sum(daily_counts.get(d, 0) for d in recent_window)
    prior_total = sum(daily_counts.get(d, 0) for d in prior_window)
    if prior_total == 0:
        return None  # not enough history to call it a trend
    pct_change = ((recent_total - prior_total) / prior_total) * 100
    return {
        "recent_7d_count": recent_total,
        "prior_7d_count": prior_total,
        "pct_change": round(pct_change, 1),
        "reliable": prior_total >= MIN_PRIOR_COUNT_FOR_RELIABLE_TREND,
    }


def _occurrence_in_window(daily_counts, window_days=7):
    """How many of the last `window_days` days (relative to this activity's
    own most recent event) had at least one occurrence. E.g. 'reading
    happened on 6 of the last 8 days' - a plain-language consistency signal
    that's often more useful than a raw count or percentage."""
    if not daily_counts:
        return None
    last_day = max(daily_counts.keys())
    window = [last_day - timedelta(days=i) for i in range(window_days)]
    active = sum(1 for d in window if daily_counts.get(d, 0) > 0)
    return {"active_days": active, "window_days": window_days}


def _time_of_day_profile(events):
    """Mean hour-of-day and whether it has shifted between the first and
    second half of the observed history (a simple, honest 'is this changing'
    signal without needing a real time-series model)."""
    hours = [_parse_ts(e["timestamp"]).hour + _parse_ts(e["timestamp"]).minute / 60 for e in events]
    if not hours:
        return None
    mean_hour = statistics.mean(hours)
    std_hour = statistics.pstdev(hours) if len(hours) > 1 else 0.0

    sorted_events = sorted(events, key=lambda e: e["timestamp"])
    half = len(sorted_events) // 2
    shift = None
    if half >= 3:  # need a reasonable sample on each side
        first_half_hours = [
            _parse_ts(e["timestamp"]).hour + _parse_ts(e["timestamp"]).minute / 60
            for e in sorted_events[:half]
        ]
        second_half_hours = [
            _parse_ts(e["timestamp"]).hour + _parse_ts(e["timestamp"]).minute / 60
            for e in sorted_events[half:]
        ]
        shift = round(statistics.mean(second_half_hours) - statistics.mean(first_half_hours), 1)

    return {
        "mean_hour": round(mean_hour, 1),
        "stddev_hours": round(std_hour, 1),
        "shift_first_half_to_second_half_hours": shift,
    }


def _most_active_weekday(events):
    counts = defaultdict(int)
    for e in events:
        counts[_parse_ts(e["timestamp"]).strftime("%A")] += 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _anomalies(daily_counts):
    """Days where activity count is a statistical outlier (>2 stddev from
    the mean daily count). Flags both spikes and near-total absences."""
    if len(daily_counts) < 5:
        return []
    counts = list(daily_counts.values())
    mean = statistics.mean(counts)
    std = statistics.pstdev(counts)
    if std == 0:
        return []
    out = []
    for d, c in daily_counts.items():
        z = (c - mean) / std
        if abs(z) >= 2:
            out.append({"date": d.isoformat(), "count": c, "z_score": round(z, 2)})
    return sorted(out, key=lambda x: x["date"])


def analyze(events):
    """
    Main entry point. `events` is a list of dicts with at least
    activity_type and timestamp (ISO 8601). Returns a JSON-serializable
    dict of per-activity-type statistics plus an overall summary.
    """
    by_type = defaultdict(list)
    for e in events:
        by_type[e["activity_type"]].append(e)

    result = {"total_events": len(events), "activity_types": {}}

    for activity_type, type_events in by_type.items():
        daily_counts = _daily_counts(type_events)
        durations = [e["duration_minutes"] for e in type_events if e.get("duration_minutes") is not None]

        result["activity_types"][activity_type] = {
            "event_count": len(type_events),
            "first_seen": min(e["timestamp"] for e in type_events),
            "last_seen": max(e["timestamp"] for e in type_events),
            "current_streak_days": _current_streak(daily_counts),
            "active_days": len(daily_counts),
            "occurrence_last_7_days": _occurrence_in_window(daily_counts, 7),
            "avg_duration_minutes": round(statistics.mean(durations), 1) if durations else None,
            "total_duration_minutes": round(sum(durations), 1) if durations else None,
            "avg_duration_hours": round(statistics.mean(durations) / 60, 2) if durations else None,
            "total_duration_hours": round(sum(durations) / 60, 2) if durations else None,
            "trend_week_over_week": _trend_last_vs_previous_week(daily_counts),
            "time_of_day": _time_of_day_profile(type_events),
            "most_active_weekday": _most_active_weekday(type_events),
            "anomalous_days": _anomalies(daily_counts),
        }

    return result
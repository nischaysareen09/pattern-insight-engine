"""
seed_data.py
Generates a synthetic but realistic 30-day activity history for a demo
user, with deliberate patterns baked in so a reviewer can hit /insights
immediately and see something meaningful without waiting on real usage:

  - "coding" sessions: frequency increases in the most recent week, and
    the time-of-day drifts later at night over the month.
  - "workout" sessions: a consistent daily streak for the last 6 days.
  - "reading" sessions: sparse and declining, with one anomalous binge day.

This file is only used by the /demo/<user_id>/seed endpoint. It never
touches the LLM or the pattern engine directly - it just produces the
same shape of input a real client would send to /activities.
"""
import random
from datetime import datetime, timedelta, timezone

random.seed(42)


def generate(user_id):
    events = []
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    # coding: increasing frequency + late-night drift
    for day_offset in range(30):
        day = start + timedelta(days=day_offset)
        # more likely to code as we approach "now" (recent week busier)
        prob = 0.5 if day_offset < 23 else 0.9
        if random.random() < prob:
            # hour drifts from ~14:00 early in the month to ~22:00 recently
            base_hour = 14 + (day_offset / 30) * 8
            hour = int(base_hour + random.uniform(-1, 1))
            hour = max(0, min(23, hour))
            ts = day.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)
            events.append(
                {
                    "activity_type": "coding",
                    "timestamp": ts.isoformat(),
                    "duration_minutes": round(random.uniform(30, 150), 1),
                    "metadata": {"project": random.choice(["backend", "frontend", "scripts"])},
                }
            )

    # workout: consistent streak for the last 6 days only
    for day_offset in range(24, 30):
        day = start + timedelta(days=day_offset)
        ts = day.replace(hour=7, minute=random.randint(0, 30), second=0, microsecond=0)
        events.append(
            {
                "activity_type": "workout",
                "timestamp": ts.isoformat(),
                "duration_minutes": round(random.uniform(20, 45), 1),
                "metadata": {"type": random.choice(["run", "gym", "yoga"])},
            }
        )

    # reading: sparse, declining, with one anomalous binge day
    for day_offset in range(30):
        day = start + timedelta(days=day_offset)
        if day_offset == 5:
            # anomalous binge day: 5 short sessions in one day
            for _ in range(5):
                ts = day.replace(hour=random.randint(18, 23), minute=random.randint(0, 59))
                events.append(
                    {
                        "activity_type": "reading",
                        "timestamp": ts.isoformat(),
                        "duration_minutes": round(random.uniform(10, 30), 1),
                        "metadata": {},
                    }
                )
        else:
            prob = 0.4 if day_offset < 15 else 0.1  # declining over the month
            if random.random() < prob:
                ts = day.replace(hour=random.randint(19, 22), minute=random.randint(0, 59))
                events.append(
                    {
                        "activity_type": "reading",
                        "timestamp": ts.isoformat(),
                        "duration_minutes": round(random.uniform(15, 60), 1),
                        "metadata": {},
                    }
                )

    events.sort(key=lambda e: e["timestamp"])
    return events

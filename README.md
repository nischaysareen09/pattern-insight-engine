
# Personal Pattern Insight Engine

Takes a stream of a user's activity events (workouts, coding sessions,
reading, or any other timestamped activity you want to log) and tells them
something specific about their own behavior that they wouldn't notice by
just glancing at a list of events - a streak, a trend, a shift in when they
do something, or a day that broke pattern.

The system is deliberately generic about *what* the activity is. You decide
the `activity_type` strings when you send data in; the engine doesn't care
if it's "coding", "workout", "screen_time", or "meditation".

## How it works

Two-stage pipeline, run in that order every time an insight is requested:

1. **Rule-based layer** (`app/patterns.py`) - pure Python/stdlib. Computes,
   per activity type: current streak, week-over-week trend, mean time-of-day
   and whether that time is drifting, most active weekday, and statistically
   anomalous days (z-score >= 2 on daily counts). No guessing, no LLM - just
   arithmetic over the stored events.
2. **LLM layer** (`app/llm.py`) - takes *only* the computed stats (never the
   raw events) and asks Claude to write a short, specific, non-generic
   insight grounded in those numbers. Keeping raw events out of the prompt
   means the model can't invent behavior that didn't actually happen.

## Requirements

- Python 3.9+
- No database server needed - uses a local SQLite file created automatically.

## Setup

```bash
cd pattern-insight-engine
pip install -r requirements.txt
cp .env.example .env   # optional - see "Enabling the LLM" below
```

## Running

```bash
cd app
python3 app.py
# Server listens on http://127.0.0.1:5000
```
## Screenshots for demo

<img width="1897" height="902" alt="SSONE" src="https://github.com/user-attachments/assets/b4c405f7-7541-4b2e-91bd-7d3101d28e5c" />
<img width="1895" height="902" alt="SSTWO" src="https://github.com/user-attachments/assets/422cab6f-5f53-40c1-94d3-687924cdbde8" />

## Enabling the LLM

Two providers are supported. If both are configured, Groq is used first.

**Option 1 (recommended, free) - Groq:**

1. Go to https://console.groq.com and sign up (no credit card needed for
   the free tier).
2. Open "API Keys" and create a new key.
3. Set it before starting the server:

```bash
export GROQ_API_KEY=gsk_...
python3 app/app.py
```

**Option 2 (paid) - Anthropic:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 app/app.py
```

Without any key set, `/insights` still returns real output end-to-end, but
the narrative is produced by a deterministic, clearly labeled
`"[fallback] ..."` template in `app/llm.py` instead of a real model call -
see **Known limitations** below.

## Quick demo

With the server running in one terminal:

```bash
./demo.sh
```

This seeds a synthetic 30-day activity history for a demo user, ingests a
couple of real events for a second user, requests an insight, and prints
the raw stats + narrative.

## API

| Method | Path                          | Description                                   |
|--------|-------------------------------|------------------------------------------------|
| GET    | `/health`                     | liveness check                                 |
| POST   | `/users/<user_id>/activities` | ingest one or more events (see body below)     |
| GET    | `/users/<user_id>/activities` | list stored raw events for a user              |
| POST   | `/users/<user_id>/insights`   | run analysis + generate a new insight          |
| GET    | `/users/<user_id>/insights`   | list previously generated insights             |
| POST   | `/demo/<user_id>/seed`        | populate synthetic 30-day demo data            |

**POST `/users/<user_id>/activities` body:**

```json
{
  "events": [
    {
      "activity_type": "coding",
      "timestamp": "2026-07-01T14:30:00",
      "duration_minutes": 45,
      "metadata": {"project": "backend"}
    }
  ]
}
```

Only `activity_type` and `timestamp` (ISO 8601) are required.
`duration_minutes` and `metadata` are optional.

**POST `/users/<user_id>/insights` response (abridged):**

```json
{
  "narrative": "Your 'coding' sessions have drifted from ~2pm to ~10pm over the last month, and this week's count is up 20% versus last week.",
  "llm_used": true,
  "llm_model": "groq:llama-3.3-70b-versatile",
  "stats": { "...": "full rule-based stats object" }
}
```

## Known limitations / what's incomplete

Being upfront, per the assignment's instructions:

- **No auth.** `user_id` is a free-text path parameter with no
  authentication or ownership check. Fine for a take-home; not fine for
  production. Would add token-based auth and scope all queries to the
  authenticated user.
- **LLM fallback is a template, not a model.** If `ANTHROPIC_API_KEY` isn't
  set (or the API call fails), the narrative comes from a deterministic
  rule in `llm.py`, clearly marked with a `"[fallback]"` prefix and
  `llm_used: false` in the response. This exists purely so the system is
  runnable and demonstrable without requiring a reviewer to have an API
  key. It is not a replacement for the real LLM path, which is fully
  implemented and used whenever a key is present.
- **Single-process SQLite.** Fine for a demo; would move to Postgres for
  concurrent writers.
- **No pagination** on `GET` list endpoints - fine at demo data volumes,
  would matter at scale.
- **Anomaly detection is a simple z-score** over daily counts, not a real
  time-series model (no seasonality, no trend decomposition). Documented
  as a deliberate scope cut for a 24-hour window; a fuller version would
  use something like STL decomposition or a rolling robust z-score.


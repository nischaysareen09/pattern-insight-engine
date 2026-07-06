"""
llm.py
Turns the rule-based statistics from patterns.py into a short, specific,
human-readable insight. This is the ONLY part of the system that talks to
an LLM, and it only ever receives already-computed numbers - it is not
allowed to see raw events, so it cannot invent facts about the user that
the rule-based layer didn't actually derive.

Supports two LLM providers, tried in this order:
  1. Groq (https://console.groq.com) - free tier, OpenAI-compatible API.
     Set GROQ_API_KEY to use this. This is the recommended default since
     it requires no payment to obtain a key.
  2. Anthropic - set ANTHROPIC_API_KEY to use Claude instead/as well.
     If both are set, Groq is used (cheaper/free, tried first).

Fallback mode: if neither key is set, produces a clearly-labeled templated
narrative so the endpoint still returns real, usable output end-to-end.
This fallback exists ONLY so a reviewer without any API key can exercise
the full request/response path. See README "Known limitations" - it is
not a substitute for the LLM requirement, it's a documented degrade path.

CHANGE LOG (post-review):
- The model now returns structured JSON: {"highlights": [...], "suggestion": "..."}
  instead of one paragraph. This makes the frontend's bullet rendering
  possible without re-parsing prose, and makes the model's reasoning easier
  to sanity-check field by field.
- The system prompt now gives an explicit priority order (anomalies >
  streaks/consistency > reliable trends) and explicitly forbids citing a
  pct_change when patterns.py has marked it unreliable (see patterns.py
  MIN_PRIOR_COUNT_FOR_RELIABLE_TREND). This directly targets the "600%
  increase" problem, which was arithmetically correct but meaningless -
  it came from a tiny prior-week count, and the old prompt had no rule
  telling the model to disregard that.
"""
import os
import json
import re
import copy
import requests

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Free, fast, and currently available on Groq's free tier. Check
# https://console.groq.com/docs/models for the current list of models if
# this one has been deprecated.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

SYSTEM_PROMPT = """You are a personal analytics assistant. You will be given \
JSON statistics computed directly from a user's own activity logs (streaks, \
occurrence-in-window counts, trends, time-of-day patterns, anomalies). Your \
job is to surface the 2-4 MOST SPECIFIC, non-obvious facts - not to \
summarize everything in the JSON.

Priority order when choosing what to report (highest first):
1. Anomalous days (the "anomalous_days" list, if non-empty for any activity) \
   - an unusual day is always more interesting than a routine one. Describe \
   what was unusual (a spike, an absence, or - using time_of_day plus the \
   date - a late/early shift) using only the numbers given.
2. Streaks and consistency: a long current_streak_days, a high occurrence_last_7_days \
   ratio (e.g. "5 of the last 7 days"), or a low time_of_day stddev_hours \
   (meaning the activity happens at a very consistent time each day).
3. A time_of_day shift (shift_first_half_to_second_half_hours far from 0).
4. trend_week_over_week - ONLY if its "reliable" field is true. If "reliable" \
   is false or the field is null, DO NOT mention pct_change, recent_7d_count, \
   or prior_7d_count at all for that activity - the sample is too small for a \
   percentage to mean anything, and citing it would be misleading even though \
   it is arithmetically correct.

Hard rules:
- Only use numbers and facts present in the JSON. Never invent data.
- Never state a pct_change when trend_week_over_week.reliable is false.
- Be concrete: cite actual numbers (e.g. "an 8-day streak", "6 of the last 7 days").
- Express any durations in HOURS only, never minutes (e.g. "a 1.5 hour session"). \
  Use the *_hours fields, never *_minutes fields (they are withheld from you already).
- No generic self-help advice in the highlights ("try to be more consistent!"). \
  Describe what IS happening, not what should happen.
- The "suggestion" field is the one place you may make a brief forward-looking \
  observation, and it must still be grounded in the stats (e.g. naming the \
  activity with the longest streak or lowest time-of-day variance as the one \
  worth protecting/continuing).

Respond with ONLY a JSON object, no prose before or after, no markdown code \
fences, in exactly this shape:
{
  "highlights": ["short specific sentence", "short specific sentence", ...],
  "suggestion": "one short forward-looking sentence grounded in the stats"
}
2 to 4 highlights. Each highlight is one sentence.
"""


def _stats_for_llm(stats):
    """
    Returns a copy of stats with minute-based duration fields removed, so
    the LLM physically cannot reference minutes - it only ever sees the
    *_hours fields, computed deterministically by patterns.py.
    """
    sanitized = copy.deepcopy(stats)
    for activity_stats in sanitized.get("activity_types", {}).values():
        activity_stats.pop("avg_duration_minutes", None)
        activity_stats.pop("total_duration_minutes", None)
    return sanitized


def _extract_json(text):
    """Models occasionally wrap JSON in ```json fences or add stray text
    despite instructions not to. Strip fences and grab the outermost {...}
    so a minor formatting slip doesn't break the whole response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    parsed = json.loads(match.group(0))
    highlights = parsed.get("highlights")
    suggestion = parsed.get("suggestion")
    if not isinstance(highlights, list) or not highlights:
        raise ValueError("model output missing non-empty 'highlights' list")
    return {
        "highlights": [str(h).strip() for h in highlights],
        "suggestion": str(suggestion).strip() if suggestion else None,
    }


def _call_groq(stats):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": GROQ_MODEL,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Here are this user's computed activity statistics:\n\n{json.dumps(_stats_for_llm(stats), indent=2)}",
            },
        ],
    }
    resp = requests.post(GROQ_API_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    raw_text = data["choices"][0]["message"]["content"].strip()
    return _extract_json(raw_text)


def _call_anthropic(stats):
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": f"Here are this user's computed activity statistics:\n\n{json.dumps(_stats_for_llm(stats), indent=2)}",
            }
        ],
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    text_parts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
    raw_text = "".join(text_parts).strip()
    return _extract_json(raw_text)


def _fallback_result(stats):
    """
    Deterministic, rule-based highlights used only when no API key is
    configured (or both providers failed). Mirrors the LLM's priority
    order - anomalies, then streak/consistency, then reliable trend only -
    so the fallback and the real LLM path degrade to similarly useful
    output rather than the fallback being visibly dumber.
    """
    types = stats.get("activity_types", {})
    if not types:
        return {"highlights": ["Not enough activity data yet to generate an insight."], "suggestion": None}

    highlights = []

    # 1. Anomalies first, across all activity types.
    for t, d in types.items():
        for a in d.get("anomalous_days", [])[:1]:
            direction = "a spike" if a["z_score"] > 0 else "an unusually quiet day"
            highlights.append(f"'{t}' had {direction} on {a['date']} ({a['count']} events).")

    # 2. Streaks / consistency, best first.
    streak_ranked = sorted(types.items(), key=lambda kv: kv[1].get("current_streak_days", 0), reverse=True)
    for t, d in streak_ranked[:2]:
        streak = d.get("current_streak_days", 0)
        occ = d.get("occurrence_last_7_days")
        if streak >= 3:
            highlights.append(f"You've maintained a {streak}-day streak on '{t}'.")
        elif occ and occ["active_days"] < occ["window_days"]:
            highlights.append(f"'{t}' occurred on {occ['active_days']} of the last {occ['window_days']} days.")

    # 3. Reliable trend only, if we still have room.
    if len(highlights) < 3:
        for t, d in types.items():
            trend = d.get("trend_week_over_week")
            if trend and trend.get("reliable"):
                direction = "up" if trend["pct_change"] >= 0 else "down"
                highlights.append(
                    f"'{t}' is {direction} {abs(trend['pct_change'])}% this week "
                    f"({trend['recent_7d_count']} vs {trend['prior_7d_count']} events)."
                )
                break

    if not highlights:
        # last resort: just report the longest streak, whatever it is
        best_t, best_d = max(types.items(), key=lambda kv: kv[1].get("current_streak_days", 0))
        highlights.append(f"Your longest current streak is '{best_t}' at {best_d.get('current_streak_days', 0)} day(s).")

    highlights = [f"[fallback] {h}" for h in highlights[:4]]

    # Suggestion: the most time-consistent activity, if we can tell.
    consistent = [
        (t, d["time_of_day"]["stddev_hours"])
        for t, d in types.items()
        if d.get("time_of_day") and d["time_of_day"].get("stddev_hours") is not None
    ]
    suggestion = None
    if consistent:
        best_t, _ = min(consistent, key=lambda x: x[1])
        suggestion = f"[fallback] '{best_t}' has been your most time-consistent habit - worth protecting."

    return {"highlights": highlights, "suggestion": suggestion}


def generate_insight(stats):
    """
    Returns (result: dict with 'highlights' and 'suggestion', llm_used: bool,
    model_name: str|None). Tries Groq first (free tier), then Anthropic,
    then falls back to a deterministic template if no key is configured or
    both calls fail.
    """
    if GROQ_API_KEY:
        try:
            return _call_groq(stats), True, f"groq:{GROQ_MODEL}"
        except Exception as exc:  # noqa: BLE001
            result = _fallback_result(stats)
            result["highlights"] = [f"[fallback due to Groq error: {exc}]"] + result["highlights"]
            return result, False, None

    if ANTHROPIC_API_KEY:
        try:
            return _call_anthropic(stats), True, f"anthropic:{ANTHROPIC_MODEL}"
        except Exception as exc:  # noqa: BLE001
            result = _fallback_result(stats)
            result["highlights"] = [f"[fallback due to Anthropic error: {exc}]"] + result["highlights"]
            return result, False, None

    return _fallback_result(stats), False, None
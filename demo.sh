#!/usr/bin/env bash
# Quick end-to-end demo against a locally running server (see README to start it).
# Usage: ./demo.sh [base_url]
set -e
BASE_URL="${1:-http://127.0.0.1:5000}"

echo "== health check =="
curl -s "$BASE_URL/health"; echo

echo -e "\n== seeding synthetic 30-day history for user 'alice' =="
curl -s -X POST "$BASE_URL/demo/alice/seed"; echo

echo -e "\n== ingesting a couple of real events for user 'bob' =="
curl -s -X POST "$BASE_URL/users/bob/activities" \
  -H "Content-Type: application/json" \
  -d '{"events":[
        {"activity_type":"run","timestamp":"2026-07-01T08:00:00","duration_minutes":32},
        {"activity_type":"run","timestamp":"2026-07-02T08:05:00","duration_minutes":28}
      ]}'; echo

echo -e "\n== generating insight for alice (rule-based stats + LLM narrative) =="
curl -s -X POST "$BASE_URL/users/alice/insights" | python3 -m json.tool

echo -e "\n== fetching alice's raw activity log =="
curl -s "$BASE_URL/users/alice/activities" | python3 -m json.tool | head -20

echo -e "\n== fetching alice's insight history =="
curl -s "$BASE_URL/users/alice/insights" | python3 -m json.tool | head -20

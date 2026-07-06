"""
app.py
Flask API. Endpoints:

  POST /users/<user_id>/activities   ingest activity events (real input)
  GET  /users/<user_id>/activities   list stored raw events
  POST /users/<user_id>/insights     run rule-based analysis + LLM narrative (real output)
  GET  /users/<user_id>/insights     list previously generated insights
  POST /demo/<user_id>/seed          populate synthetic sample data for a quick demo
  GET  /health                       liveness check
"""
from flask import Flask, request, jsonify, send_from_directory
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import storage
import patterns
import llm
import seed_data

app = Flask(__name__, static_folder="static", static_url_path="/static")
storage.init_db()


@app.route("/", methods=["GET"])
def index():
    """Serves the browser UI (app/static/index.html) for entering
    activities and generating insights without needing curl or a CLI."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/users/<user_id>/activities", methods=["POST"])
def ingest_activities(user_id):
    payload = request.get_json(force=True, silent=True)
    if not payload or "events" not in payload:
        return jsonify({"error": "expected JSON body: {\"events\": [ {activity_type, timestamp, ...}, ... ]}"}), 400

    events = payload["events"]
    if not isinstance(events, list) or len(events) == 0:
        return jsonify({"error": "events must be a non-empty list"}), 400

    inserted_ids = []
    for i, e in enumerate(events):
        if "activity_type" not in e or "timestamp" not in e:
            return jsonify({"error": f"event at index {i} missing required field 'activity_type' or 'timestamp'"}), 400
        rid = storage.insert_activity(
            user_id=user_id,
            activity_type=e["activity_type"],
            timestamp=e["timestamp"],
            duration_minutes=e.get("duration_minutes"),
            metadata=e.get("metadata"),
        )
        inserted_ids.append(rid)

    return jsonify({"inserted": len(inserted_ids), "ids": inserted_ids}), 201


@app.route("/users/<user_id>/activities", methods=["GET"])
def list_activities(user_id):
    return jsonify({"user_id": user_id, "events": storage.get_activities(user_id)})


@app.route("/users/<user_id>/insights", methods=["POST"])
def generate_insight(user_id):
    events = storage.get_activities(user_id)
    if not events:
        return jsonify({"error": f"no activity data for user '{user_id}' yet - POST some events first"}), 404

    stats = patterns.analyze(events)
    result, llm_used, model_name = llm.generate_insight(stats)
    highlights = result.get("highlights", [])
    suggestion = result.get("suggestion")

    # Keep a flat "narrative" string too, for anything consuming the old
    # shape (demo.sh, prior README examples) - just the highlights and
    # suggestion joined into readable prose.
    narrative = " ".join(highlights + ([suggestion] if suggestion else []))

    storage.insert_insight(user_id, stats, narrative, llm_used, model_name)

    return jsonify(
        {
            "user_id": user_id,
            "narrative": narrative,
            "highlights": highlights,
            "suggestion": suggestion,
            "llm_used": llm_used,
            "llm_model": model_name,
            "stats": stats,
        }
    ), 201


@app.route("/users/<user_id>/insights", methods=["GET"])
def list_insights(user_id):
    return jsonify({"user_id": user_id, "insights": storage.get_insights(user_id)})


@app.route("/demo/<user_id>/seed", methods=["POST"])
def seed(user_id):
    events = seed_data.generate(user_id)
    for e in events:
        storage.insert_activity(
            user_id=user_id,
            activity_type=e["activity_type"],
            timestamp=e["timestamp"],
            duration_minutes=e.get("duration_minutes"),
            metadata=e.get("metadata"),
        )
    return jsonify({"user_id": user_id, "seeded_events": len(events)}), 201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
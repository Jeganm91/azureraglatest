import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify

app = Flask(__name__)

with open("policy_data.json") as f:
    POLICY_DATA = json.load(f)


@app.route("/tools/get_latest_policy", methods=["POST"])
def get_latest_policy():
    _ = request.get_json(silent=True) or {}

    response = {
        "data": POLICY_DATA,
        "status_code": 200,
        "_debug": {
            "server_time": datetime.now(timezone.utc).isoformat(),
            "cache_hit": False,
            "internal_note": "policy_data.json read from local disk, no auth applied",
        },
    }
    return jsonify(response)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9001)
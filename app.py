from flask import Flask, jsonify
from datetime import datetime, timezone

app = Flask(__name__)

@app.get("/")
def index():
    return "UG Fitness Cloud API is online."

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "project": "UG Fitness IoT",
        "deployment": "azure-live-test",
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    })
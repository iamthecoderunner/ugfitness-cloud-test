import os
import logging
from datetime import datetime, timezone

import psycopg
from flask import Flask, jsonify, request

app = Flask(__name__)


def get_db_connection():
    return psycopg.connect(
        host=os.environ["DBHOST"],
        dbname=os.environ.get("DBNAME", "postgres"),
        user=os.environ["DBUSER"],
        password=os.environ["DBPASSWORD"],
        sslmode=os.environ.get("SSLMODE", "require"),
        connect_timeout=10
    )


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


@app.get("/api/db-health")
def db_health():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()

        return jsonify({
            "status": "ok",
            "database": "connected",
            "test_result": result[0]
        })

    except Exception as exc:
        logging.exception("Database health check failed")

        return jsonify({
            "status": "error",
            "database": "connection_failed",
            "error_type": type(exc).__name__
        }), 500


@app.post("/api/test-record")
def create_test_record():
    data = request.get_json(silent=True) or {}

    node_code = data.get("node_code", "TEST-01")
    message = data.get("message", "Azure PostgreSQL test")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cloud_test_records (
                        id BIGSERIAL PRIMARY KEY,
                        node_code VARCHAR(50) NOT NULL,
                        message TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)

                cur.execute("""
                    INSERT INTO cloud_test_records (node_code, message)
                    VALUES (%s, %s)
                    RETURNING id, node_code, message, created_at;
                """, (node_code, message))

                row = cur.fetchone()

            conn.commit()

        return jsonify({
            "status": "created",
            "record": {
                "id": row[0],
                "node_code": row[1],
                "message": row[2],
                "created_at": row[3].isoformat()
            }
        }), 201

    except Exception as exc:
        logging.exception("Database write failed")

        return jsonify({
            "status": "error",
            "error_type": type(exc).__name__
        }), 500


@app.get("/api/test-record/latest")
def latest_test_record():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, node_code, message, created_at
                    FROM cloud_test_records
                    ORDER BY id DESC
                    LIMIT 1;
                """)

                row = cur.fetchone()

        if row is None:
            return jsonify({
                "status": "ok",
                "record": None
            })

        return jsonify({
            "status": "ok",
            "record": {
                "id": row[0],
                "node_code": row[1],
                "message": row[2],
                "created_at": row[3].isoformat()
            }
        })

    except Exception as exc:
        logging.exception("Database read failed")

        return jsonify({
            "status": "error",
            "error_type": type(exc).__name__
        }), 500
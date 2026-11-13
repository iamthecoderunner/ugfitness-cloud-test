import os
import secrets
from datetime import date

import psycopg
from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


def get_connection():
    return psycopg.connect(
        host=os.environ["DBHOST"],
        dbname=os.environ.get("DBNAME", "postgres"),
        user=os.environ["DBUSER"],
        password=os.environ["DBPASSWORD"],
        sslmode=os.environ.get("SSLMODE", "require"),
    )


def normalize_uid(uid):
    if uid is None:
        return None

    return str(uid).strip().upper().replace("-", ":")


def device_authorized():
    expected = os.environ.get("DEVICE_API_KEY")
    supplied = request.headers.get("X-Device-Key")

    if not expected or not supplied:
        return False

    return secrets.compare_digest(expected, supplied)


def get_effective_member_status(account_status, membership_end):
    if account_status != "ACTIVE":
        return "INACTIVE"

    if membership_end and membership_end < date.today():
        return "EXPIRED"

    return "ACTIVE"


def get_occupancy(cur):
    cur.execute("""
        SELECT COUNT(*)
        FROM visits
        WHERE visit_status = 'OPEN';
    """)

    return cur.fetchone()[0]


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "UG Fitness API"
    })


@app.post("/api/rfid-scan")
def rfid_scan():

    if not device_authorized():
        return jsonify({
            "status": "error",
            "message": "Unauthorized device"
        }), 401

    data = request.get_json(silent=True) or {}

    uid = normalize_uid(data.get("uid"))
    node_code = str(data.get("node_code", "")).strip()

    if not uid:
        return jsonify({
            "status": "error",
            "message": "RFID UID is required"
        }), 400

    if not node_code:
        return jsonify({
            "status": "error",
            "message": "node_code is required"
        }), 400

    with get_connection() as conn:
        with conn.cursor() as cur:

            # -------------------------------------------
            # Validate RFID node
            # -------------------------------------------
            cur.execute("""
                SELECT id, enabled, node_type
                FROM iot_nodes
                WHERE node_code = %s;
            """, (node_code,))

            node = cur.fetchone()

            if not node:
                return jsonify({
                    "status": "error",
                    "message": "Unknown IoT node"
                }), 404

            node_id, enabled, node_type = node

            if node_type != "RFID":
                return jsonify({
                    "status": "error",
                    "message": "Node is not an RFID reader"
                }), 400

            if not enabled:
                return jsonify({
                    "status": "error",
                    "message": "RFID node is disabled"
                }), 403

            # Mark node online / seen
            cur.execute("""
                UPDATE iot_nodes
                SET
                    last_seen_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s;
            """, (node_id,))

            # -------------------------------------------
            # Simple duplicate-scan protection
            # -------------------------------------------
            cur.execute("""
                SELECT scanned_at
                FROM rfid_scan_events
                WHERE node_id = %s
                  AND uid = %s
                ORDER BY scanned_at DESC
                LIMIT 1;
            """, (node_id, uid))

            recent = cur.fetchone()

            if recent:
                cur.execute("""
                    SELECT
                        EXTRACT(
                            EPOCH FROM (
                                NOW() - %s::timestamptz
                            )
                        );
                """, (recent[0],))

                seconds_since_scan = float(cur.fetchone()[0])

                if seconds_since_scan < 3:
                    return jsonify({
                        "status": "ignored",
                        "message": "Duplicate scan ignored"
                    }), 200

            # -------------------------------------------
            # Find credential
            # -------------------------------------------
            cur.execute("""
                SELECT
                    r.id,
                    r.card_type,
                    r.status,
                    r.member_id,
                    r.assigned_walkin_id
                FROM rfid_credentials r
                WHERE r.uid = %s;
            """, (uid,))

            credential = cur.fetchone()

            if not credential:
                cur.execute("""
                    INSERT INTO rfid_scan_events (
                        node_id,
                        uid,
                        result_code,
                        message
                    )
                    VALUES (%s, %s, %s, %s);
                """, (
                    node_id,
                    uid,
                    "UNKNOWN_CARD",
                    "RFID credential not registered"
                ))

                occupancy = get_occupancy(cur)

                return jsonify({
                    "status": "error",
                    "result": "UNKNOWN_CARD",
                    "uid": uid,
                    "occupancy": occupancy,
                    "message": "Unknown RFID card"
                }), 404

            (
                credential_id,
                card_type,
                credential_status,
                member_id,
                assigned_walkin_id
            ) = credential

            # -------------------------------------------
            # Permanent member RFID
            # -------------------------------------------
            if card_type == "PERMANENT":

                if credential_status != "ACTIVE":
                    cur.execute("""
                        INSERT INTO rfid_scan_events (
                            node_id,
                            uid,
                            result_code,
                            message
                        )
                        VALUES (%s, %s, %s, %s);
                    """, (
                        node_id,
                        uid,
                        "CARD_INACTIVE",
                        "Permanent RFID credential is inactive"
                    ))

                    return jsonify({
                        "status": "error",
                        "result": "CARD_INACTIVE",
                        "message": "RFID card is inactive"
                    }), 403

                cur.execute("""
                    SELECT
                        member_code,
                        full_name,
                        account_status,
                        membership_start,
                        membership_end
                    FROM members
                    WHERE id = %s;
                """, (member_id,))

                member = cur.fetchone()

                if not member:
                    return jsonify({
                        "status": "error",
                        "message": "Member record not found"
                    }), 404

                (
                    member_code,
                    full_name,
                    account_status,
                    membership_start,
                    membership_end
                ) = member

                effective_status = get_effective_member_status(
                    account_status,
                    membership_end
                )

                if effective_status != "ACTIVE":

                    result_code = (
                        "MEMBER_EXPIRED"
                        if effective_status == "EXPIRED"
                        else "MEMBER_INACTIVE"
                    )

                    cur.execute("""
                        INSERT INTO rfid_scan_events (
                            node_id,
                            uid,
                            result_code,
                            message
                        )
                        VALUES (%s, %s, %s, %s);
                    """, (
                        node_id,
                        uid,
                        result_code,
                        f"Member status: {effective_status}"
                    ))

                    occupancy = get_occupancy(cur)

                    return jsonify({
                        "status": "error",
                        "result": result_code,
                        "member": {
                            "member_code": member_code,
                            "full_name": full_name,
                            "membership_status": effective_status,
                            "membership_end": (
                                membership_end.isoformat()
                                if membership_end
                                else None
                            )
                        },
                        "occupancy": occupancy,
                        "message": f"Member is {effective_status.lower()}"
                    }), 403

                # ---------------------------------------
                # Is member already inside?
                # ---------------------------------------
                cur.execute("""
                    SELECT id, check_in_at
                    FROM visits
                    WHERE member_id = %s
                      AND visit_status = 'OPEN'
                    ORDER BY check_in_at DESC
                    LIMIT 1;
                """, (member_id,))

                open_visit = cur.fetchone()

                if open_visit:

                    visit_id = open_visit[0]

                    cur.execute("""
                        UPDATE visits
                        SET
                            check_out_at = NOW(),
                            visit_status = 'CLOSED',
                            exit_method = 'RFID'
                        WHERE id = %s;
                    """, (visit_id,))

                    action = "CHECK_OUT"

                    cur.execute("""
                        INSERT INTO rfid_scan_events (
                            node_id,
                            uid,
                            result_code,
                            message
                        )
                        VALUES (%s, %s, %s, %s);
                    """, (
                        node_id,
                        uid,
                        action,
                        f"{full_name} checked out"
                    ))

                else:

                    cur.execute("""
                        INSERT INTO visits (
                            member_id,
                            credential_id,
                            entry_method,
                            visit_status
                        )
                        VALUES (
                            %s,
                            %s,
                            'RFID',
                            'OPEN'
                        )
                        RETURNING id;
                    """, (
                        member_id,
                        credential_id
                    ))

                    visit_id = cur.fetchone()[0]

                    action = "CHECK_IN"

                    cur.execute("""
                        INSERT INTO rfid_scan_events (
                            node_id,
                            uid,
                            result_code,
                            message
                        )
                        VALUES (%s, %s, %s, %s);
                    """, (
                        node_id,
                        uid,
                        action,
                        f"{full_name} checked in"
                    ))

                occupancy = get_occupancy(cur)

                return jsonify({
                    "status": "ok",
                    "result": action,
                    "member": {
                        "member_code": member_code,
                        "full_name": full_name,
                        "membership_status": "ACTIVE",
                        "membership_start": (
                            membership_start.isoformat()
                            if membership_start
                            else None
                        ),
                        "membership_end": (
                            membership_end.isoformat()
                            if membership_end
                            else None
                        )
                    },
                    "visit_id": visit_id,
                    "occupancy": occupancy,
                    "message": (
                        f"{full_name} checked in"
                        if action == "CHECK_IN"
                        else f"{full_name} checked out"
                    )
                }), 200

            # -------------------------------------------
            # Temporary card workflow comes next
            # -------------------------------------------
            if card_type == "TEMPORARY":

                cur.execute("""
                    INSERT INTO rfid_scan_events (
                        node_id,
                        uid,
                        result_code,
                        message
                    )
                    VALUES (%s, %s, %s, %s);
                """, (
                    node_id,
                    uid,
                    "TEMP_CARD_PENDING",
                    "Temporary RFID workflow not yet activated"
                ))

                return jsonify({
                    "status": "error",
                    "result": "TEMP_CARD_PENDING",
                    "message": "Temporary RFID workflow not yet activated"
                }), 409

            return jsonify({
                "status": "error",
                "message": "Unsupported RFID credential type"
            }), 400

        
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)



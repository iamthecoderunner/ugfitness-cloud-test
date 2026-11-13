import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return psycopg.connect(
        host=os.environ["DBHOST"],
        dbname=os.environ.get("DBNAME", "postgres"),
        user=os.environ["DBUSER"],
        password=os.environ["DBPASSWORD"],
        sslmode=os.environ.get("SSLMODE", "require"),
    )


CARD_A_UID = "79:36:02:E6"
CARD_B_UID = "E1:FB:15:B1"


with get_connection() as conn:
    with conn.cursor() as cur:

        # --------------------------------------------------
        # IoT nodes
        # --------------------------------------------------
        cur.execute("""
            INSERT INTO iot_nodes (
                node_code,
                node_type,
                location,
                enabled
            )
            VALUES (
                'RFID-01',
                'RFID',
                'Reception / Entrance',
                TRUE
            )
            ON CONFLICT (node_code)
            DO UPDATE SET
                node_type = EXCLUDED.node_type,
                location = EXCLUDED.location,
                enabled = TRUE;
        """)

        cur.execute("""
            INSERT INTO iot_nodes (
                node_code,
                node_type,
                location,
                enabled
            )
            VALUES (
                'COMFORT-01',
                'COMFORT',
                'Selected Monitoring Zone',
                TRUE
            )
            ON CONFLICT (node_code)
            DO UPDATE SET
                node_type = EXCLUDED.node_type,
                location = EXCLUDED.location,
                enabled = TRUE;
        """)

        # --------------------------------------------------
        # Active demo member
        # --------------------------------------------------
        cur.execute("""
            INSERT INTO members (
                member_code,
                full_name,
                membership_start,
                membership_end,
                account_status,
                notes
            )
            VALUES (
                'TEST-001',
                'Gio Demo Member',
                CURRENT_DATE,
                CURRENT_DATE + INTERVAL '30 days',
                'ACTIVE',
                'Demo member for adviser system testing'
            )
            ON CONFLICT (member_code)
            DO UPDATE SET
                full_name = EXCLUDED.full_name,
                membership_start = EXCLUDED.membership_start,
                membership_end = EXCLUDED.membership_end,
                account_status = 'ACTIVE',
                notes = EXCLUDED.notes
            RETURNING id;
        """)

        member_id = cur.fetchone()[0]

        # --------------------------------------------------
        # Card A = permanent RFID for active member
        # --------------------------------------------------
        cur.execute("""
            INSERT INTO rfid_credentials (
                uid,
                card_type,
                status,
                member_id,
                assigned_walkin_id
            )
            VALUES (
                %s,
                'PERMANENT',
                'ACTIVE',
                %s,
                NULL
            )
            ON CONFLICT (uid)
            DO UPDATE SET
                card_type = 'PERMANENT',
                status = 'ACTIVE',
                member_id = EXCLUDED.member_id,
                assigned_walkin_id = NULL,
                updated_at = NOW();
        """, (CARD_A_UID, member_id))

        # --------------------------------------------------
        # Card B intentionally stays UNKNOWN.
        #
        # Remove it from credentials if it happened to exist
        # from previous production-schema testing.
        # This does NOT touch the old cloud-test table.
        # --------------------------------------------------
        cur.execute("""
            DELETE FROM rfid_credentials
            WHERE uid = %s;
        """, (CARD_B_UID,))

        # Clear open demo visits for TEST-001 so we start clean.
        cur.execute("""
            UPDATE visits
            SET
                visit_status = 'CLOSED',
                check_out_at = COALESCE(check_out_at, NOW()),
                exit_method = COALESCE(exit_method, 'MANUAL')
            WHERE member_id = %s
              AND visit_status = 'OPEN';
        """, (member_id,))

        # --------------------------------------------------
        # Verification
        # --------------------------------------------------
        cur.execute("""
            SELECT
                m.member_code,
                m.full_name,
                m.account_status,
                m.membership_start,
                m.membership_end,
                r.uid,
                r.card_type,
                r.status
            FROM members m
            JOIN rfid_credentials r
                ON r.member_id = m.id
            WHERE m.member_code = 'TEST-001';
        """)

        member = cur.fetchone()

        cur.execute("""
            SELECT
                node_code,
                node_type,
                location,
                enabled
            FROM iot_nodes
            ORDER BY node_code;
        """)

        nodes = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*)
            FROM rfid_credentials
            WHERE uid = %s;
        """, (CARD_B_UID,))

        card_b_count = cur.fetchone()[0]


print()
print("Production seed completed.")
print("----------------------------------------")

if member:
    print("Demo member:")
    print("  Code:", member[0])
    print("  Name:", member[1])
    print("  Status:", member[2])
    print("  Membership:", member[3], "to", member[4])
    print("  RFID:", member[5])
    print("  Card type:", member[6])
    print("  Card status:", member[7])

print()
print("IoT nodes:")

for node in nodes:
    print(
        f"  {node[0]} | "
        f"{node[1]} | "
        f"{node[2]} | "
        f"enabled={node[3]}"
    )

print()
print(
    "Card B:",
    CARD_B_UID,
    "->",
    "UNKNOWN" if card_b_count == 0 else "REGISTERED"
)
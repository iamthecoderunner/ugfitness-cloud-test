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


with get_connection() as conn:
    with conn.cursor() as cur:

        # --------------------------------------------------
        # SYSTEM USERS
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(80) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name VARCHAR(150) NOT NULL,
                role VARCHAR(30) NOT NULL
                    CHECK (role IN ('ADMIN', 'MANAGEMENT', 'STAFF')),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # MEMBERS
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id BIGSERIAL PRIMARY KEY,
                member_code VARCHAR(50) UNIQUE NOT NULL,
                full_name VARCHAR(150) NOT NULL,

                membership_start DATE,
                membership_end DATE,

                account_status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                    CHECK (account_status IN ('ACTIVE', 'INACTIVE')),

                contact_number VARCHAR(30),
                notes TEXT,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # WALK-INS
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS walkins (
                id BIGSERIAL PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                contact_number VARCHAR(30),
                notes TEXT,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # RFID CARDS
        # Permanent cards can belong to members.
        # Temporary cards are reusable for walk-ins.
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rfid_credentials (
                id BIGSERIAL PRIMARY KEY,
                uid VARCHAR(50) UNIQUE NOT NULL,

                card_type VARCHAR(20) NOT NULL
                    CHECK (card_type IN ('PERMANENT', 'TEMPORARY')),

                status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                    CHECK (
                        status IN (
                            'ACTIVE',
                            'AVAILABLE',
                            'ASSIGNED',
                            'INACTIVE'
                        )
                    ),

                member_id BIGINT REFERENCES members(id)
                    ON DELETE SET NULL,

                assigned_walkin_id BIGINT REFERENCES walkins(id)
                    ON DELETE SET NULL,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # IoT NODES
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS iot_nodes (
                id BIGSERIAL PRIMARY KEY,
                node_code VARCHAR(50) UNIQUE NOT NULL,

                node_type VARCHAR(30) NOT NULL
                    CHECK (
                        node_type IN (
                            'RFID',
                            'COMFORT'
                        )
                    ),

                location VARCHAR(150),
                firmware_version VARCHAR(50),

                enabled BOOLEAN NOT NULL DEFAULT TRUE,

                last_seen_at TIMESTAMPTZ,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # VISITS
        #
        # Exactly one of member_id / walkin_id should be used.
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS visits (
                id BIGSERIAL PRIMARY KEY,

                member_id BIGINT REFERENCES members(id)
                    ON DELETE SET NULL,

                walkin_id BIGINT REFERENCES walkins(id)
                    ON DELETE SET NULL,

                credential_id BIGINT REFERENCES rfid_credentials(id)
                    ON DELETE SET NULL,

                check_in_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                check_out_at TIMESTAMPTZ,

                visit_status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                    CHECK (visit_status IN ('OPEN', 'CLOSED')),

                entry_method VARCHAR(20) NOT NULL DEFAULT 'RFID'
                    CHECK (entry_method IN ('RFID', 'MANUAL')),

                exit_method VARCHAR(20)
                    CHECK (
                        exit_method IS NULL
                        OR exit_method IN ('RFID', 'MANUAL')
                    ),

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                CHECK (
                    (member_id IS NOT NULL AND walkin_id IS NULL)
                    OR
                    (member_id IS NULL AND walkin_id IS NOT NULL)
                )
            );
        """)

        # Prevent two simultaneous OPEN visits for one member.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_open_visit_member
            ON visits(member_id)
            WHERE
                visit_status = 'OPEN'
                AND member_id IS NOT NULL;
        """)

        # Prevent two simultaneous OPEN visits for one walk-in.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_open_visit_walkin
            ON visits(walkin_id)
            WHERE
                visit_status = 'OPEN'
                AND walkin_id IS NOT NULL;
        """)

        # --------------------------------------------------
        # RFID SCAN EVENTS
        # Useful for audit + adviser demo.
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rfid_scan_events (
                id BIGSERIAL PRIMARY KEY,

                node_id BIGINT REFERENCES iot_nodes(id)
                    ON DELETE SET NULL,

                uid VARCHAR(50) NOT NULL,

                result_code VARCHAR(50) NOT NULL,

                message TEXT,

                scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # COMFORT READINGS
        # Store C as canonical value.
        # Fahrenheit will be calculated for display.
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS comfort_readings (
                id BIGSERIAL PRIMARY KEY,

                node_id BIGINT REFERENCES iot_nodes(id)
                    ON DELETE SET NULL,

                temperature_c NUMERIC(6,2) NOT NULL,

                humidity_percent NUMERIC(6,2) NOT NULL
                    CHECK (
                        humidity_percent >= 0
                        AND humidity_percent <= 100
                    ),

                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # MANUAL CORRECTIONS
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS visit_corrections (
                id BIGSERIAL PRIMARY KEY,

                visit_id BIGINT REFERENCES visits(id)
                    ON DELETE SET NULL,

                user_id BIGINT REFERENCES users(id)
                    ON DELETE SET NULL,

                action VARCHAR(50) NOT NULL,

                reason TEXT NOT NULL,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # ALERTS
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id BIGSERIAL PRIMARY KEY,

                alert_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL DEFAULT 'INFO'
                    CHECK (
                        severity IN (
                            'INFO',
                            'WARNING',
                            'CRITICAL'
                        )
                    ),

                message TEXT NOT NULL,

                acknowledged BOOLEAN NOT NULL DEFAULT FALSE,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                acknowledged_at TIMESTAMPTZ
            );
        """)

        # --------------------------------------------------
        # AUDIT LOG
        # --------------------------------------------------
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id BIGSERIAL PRIMARY KEY,

                user_id BIGINT REFERENCES users(id)
                    ON DELETE SET NULL,

                action VARCHAR(100) NOT NULL,
                entity_type VARCHAR(50),
                entity_id BIGINT,

                details TEXT,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # --------------------------------------------------
        # INITIAL IoT NODES
        # --------------------------------------------------
        cur.execute("""
            INSERT INTO iot_nodes (
                node_code,
                node_type,
                location
            )
            VALUES (
                'RFID-01',
                'RFID',
                'Reception / Entrance'
            )
            ON CONFLICT (node_code) DO NOTHING;
        """)

        cur.execute("""
            INSERT INTO iot_nodes (
                node_code,
                node_type,
                location
            )
            VALUES (
                'COMFORT-01',
                'COMFORT',
                'Selected Monitoring Zone'
            )
            ON CONFLICT (node_code) DO NOTHING;
        """)


print("Production schema initialized successfully.")
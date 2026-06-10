"""SQLite database for claims, members, and processing history."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "claims.db"

_conn: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        try:
            _conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        _create_tables(_conn)
        _seed_members(_conn)
    return _conn


def reset_connection():
    """Reset the connection (for testing or schema changes)."""
    global _conn
    if _conn:
        _conn.close()
    _conn = None


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS members (
            member_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            date_of_birth TEXT,
            gender TEXT,
            relationship TEXT,
            join_date TEXT,
            primary_member_id TEXT,
            dependents TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            member_id TEXT NOT NULL,
            member_name TEXT,
            policy_id TEXT NOT NULL,
            claim_category TEXT NOT NULL,
            treatment_date TEXT NOT NULL,
            claimed_amount REAL NOT NULL,
            hospital_name TEXT,
            status TEXT,
            approved_amount REAL,
            confidence REAL,
            summary TEXT,
            trace TEXT,
            full_decision TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (member_id) REFERENCES members(member_id)
        );

        CREATE TABLE IF NOT EXISTS claims_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id TEXT NOT NULL,
            claim_id TEXT NOT NULL,
            claim_date TEXT NOT NULL,
            amount REAL NOT NULL,
            provider TEXT,
            status TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (member_id) REFERENCES members(member_id)
        );

        CREATE TABLE IF NOT EXISTS claim_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            member_id TEXT NOT NULL,
            patient_name TEXT,
            doctor_name TEXT,
            doctor_registration TEXT,
            hospital_name TEXT,
            diagnosis TEXT,
            treatment TEXT,
            treatment_date TEXT,
            bill_number TEXT,
            total_amount REAL,
            medicines TEXT DEFAULT '[]',
            line_items TEXT DEFAULT '[]',
            file_hashes TEXT DEFAULT '[]',
            file_paths TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(claim_id),
            FOREIGN KEY (member_id) REFERENCES members(member_id)
        );

        CREATE TABLE IF NOT EXISTS network_hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            discount_percent REAL DEFAULT 20,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (member_id) REFERENCES members(member_id)
        );

        CREATE INDEX IF NOT EXISTS idx_claims_member ON claims(member_id);
        CREATE INDEX IF NOT EXISTS idx_claims_date ON claims(treatment_date);
        CREATE INDEX IF NOT EXISTS idx_history_member_date ON claims_history(member_id, claim_date);
        CREATE INDEX IF NOT EXISTS idx_details_member ON claim_details(member_id);
        CREATE INDEX IF NOT EXISTS idx_details_doctor_date ON claim_details(doctor_name, treatment_date);
        CREATE INDEX IF NOT EXISTS idx_users_member_id ON users(member_id);
    """)
    conn.commit()


def _seed_members(conn: sqlite3.Connection):
    """Seed members from policy_terms.json if table is empty."""
    count = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    if count > 0:
        return

    from policy_engine import load_policy
    policy = load_policy()
    for member in policy["members"]:
        conn.execute(
            """INSERT OR IGNORE INTO members (member_id, name, date_of_birth, gender, relationship, join_date, primary_member_id, dependents)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                member["member_id"],
                member["name"],
                member.get("date_of_birth"),
                member.get("gender"),
                member.get("relationship"),
                member.get("join_date"),
                member.get("primary_member_id"),
                json.dumps(member.get("dependents", [])),
            ),
        )
    conn.commit()
    _seed_network_hospitals(conn, policy)
    _seed_users(conn, policy)


def _seed_network_hospitals(conn: sqlite3.Connection, policy: dict):
    """Seed network hospitals from policy_terms.json."""
    count = conn.execute("SELECT COUNT(*) FROM network_hospitals").fetchone()[0]
    if count > 0:
        return
    discount = policy.get("opd_categories", {}).get("consultation", {}).get("network_discount_percent", 20)
    for hospital in policy.get("network_hospitals", []):
        conn.execute(
            "INSERT OR IGNORE INTO network_hospitals (name, discount_percent) VALUES (?, ?)",
            (hospital, discount),
        )
    conn.commit()


def _seed_users(conn: sqlite3.Connection, policy: dict):
    """Create default login accounts for all members + admin."""
    import hashlib

    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return

    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    # Admin account
    conn.execute(
        "INSERT OR IGNORE INTO users (member_id, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
        ("ADMIN", "Admin", "admin@plum.com", hash_password("plum2024"), "admin"),
    )

    # Member accounts — password is their member_id lowercase (e.g. emp001)
    for member in policy["members"]:
        conn.execute(
            "INSERT OR IGNORE INTO users (member_id, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (
                member["member_id"],
                member["name"],
                "aryamangupta004@gmail.com",
                hash_password(member["member_id"].lower()),
                "member",
            ),
        )
    conn.commit()


def get_network_hospital(hospital_name: str) -> Optional[dict]:
    """Check if hospital is in network and get its discount."""
    if not hospital_name:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT name, discount_percent FROM network_hospitals WHERE LOWER(name) = LOWER(?) AND active = 1",
        (hospital_name.strip(),),
    ).fetchone()
    if not row:
        # Fuzzy match
        row = conn.execute(
            "SELECT name, discount_percent FROM network_hospitals WHERE LOWER(name) LIKE LOWER(?) AND active = 1",
            (f"%{hospital_name.strip()}%",),
        ).fetchone()
    if not row:
        return None
    return {"name": row["name"], "discount_percent": row["discount_percent"]}


def get_all_network_hospitals() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT name, discount_percent FROM network_hospitals WHERE active = 1 ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def authenticate_user(member_id: str, password: str) -> Optional[dict]:
    """Verify login credentials. Returns user info or None."""
    import hashlib
    conn = get_connection()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    row = conn.execute(
        "SELECT member_id, name, email, role FROM users WHERE member_id = ? AND password_hash = ?",
        (member_id.upper(), password_hash),
    ).fetchone()
    if not row:
        return None
    return {
        "member_id": row["member_id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
    }


def get_member_by_name(name: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM members WHERE LOWER(name) = LOWER(?)", (name.strip(),)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM members WHERE LOWER(name) LIKE LOWER(?)", (f"%{name.strip()}%",)
        ).fetchone()
    if not row:
        return None
    return {
        "member_id": row["member_id"],
        "name": row["name"],
        "date_of_birth": row["date_of_birth"],
        "gender": row["gender"],
        "relationship": row["relationship"],
        "join_date": row["join_date"],
        "primary_member_id": row["primary_member_id"],
        "dependents": json.loads(row["dependents"]) if row["dependents"] else [],
    }


def get_member(member_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    if not row:
        return None
    return {
        "member_id": row["member_id"],
        "name": row["name"],
        "date_of_birth": row["date_of_birth"],
        "gender": row["gender"],
        "relationship": row["relationship"],
        "join_date": row["join_date"],
        "primary_member_id": row["primary_member_id"],
        "dependents": json.loads(row["dependents"]) if row["dependents"] else [],
    }


def get_all_members() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM members ORDER BY member_id").fetchall()
    return [
        {
            "member_id": row["member_id"],
            "name": row["name"],
            "date_of_birth": row["date_of_birth"],
            "gender": row["gender"],
            "relationship": row["relationship"],
            "join_date": row["join_date"],
        }
        for row in rows
    ]


def save_claim(decision: dict):
    conn = get_connection()
    # Look up member name
    member_name = None
    member_row = conn.execute("SELECT name FROM members WHERE member_id = ?", (decision["member_id"],)).fetchone()
    if member_row:
        member_name = member_row["name"]

    conn.execute(
        """INSERT OR REPLACE INTO claims
           (claim_id, member_id, member_name, policy_id, claim_category, treatment_date, claimed_amount,
            hospital_name, status, approved_amount, confidence, summary, trace, full_decision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            decision["claim_id"],
            decision["member_id"],
            member_name,
            decision.get("policy_id", "PLUM_GHI_2024"),
            decision["claim_category"],
            decision["treatment_date"],
            decision["claimed_amount"],
            decision.get("hospital_name"),
            decision["status"],
            decision.get("approved_amount"),
            decision.get("confidence"),
            decision.get("summary"),
            json.dumps(decision.get("trace", [])),
            json.dumps(decision),
        ),
    )
    # Also save to claims history for fraud detection
    conn.execute(
        """INSERT INTO claims_history (member_id, claim_id, claim_date, amount, provider, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            decision["member_id"],
            decision["claim_id"],
            decision["treatment_date"],
            decision["claimed_amount"],
            decision.get("hospital_name"),
            decision["status"],
        ),
    )
    conn.commit()


def get_claim(claim_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT full_decision FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
    if not row:
        return None
    return json.loads(row["full_decision"])


def get_all_claims() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT claim_id, member_id, member_name, status, claim_category, claimed_amount, approved_amount, confidence, created_at FROM claims ORDER BY created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def save_uploaded_files(claim_id: str, member_id: str, documents: list[dict]) -> list[str]:
    """Save uploaded file data to disk. Returns list of saved file paths."""
    import base64
    uploads_dir = Path(__file__).parent / "uploads" / member_id
    uploads_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for i, doc in enumerate(documents):
        if not doc.get("file_data"):
            continue

        file_name = doc.get("file_name", f"doc_{i}")
        safe_name = f"{claim_id}_{i}_{file_name}"
        file_path = uploads_dir / safe_name

        try:
            file_bytes = base64.b64decode(doc["file_data"])
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            saved_paths.append(str(file_path))
        except Exception:
            continue

    return saved_paths


def save_claim_details(claim_id: str, member_id: str, extracted_data: dict, documents: list[dict], file_paths: list[str] = None):
    """Store extracted claim details for future duplicate detection."""
    import hashlib
    conn = get_connection()

    file_hashes = []
    for doc in documents:
        if doc.get("file_data"):
            file_hashes.append(hashlib.sha256(doc["file_data"].encode()).hexdigest())
        elif doc.get("content"):
            file_hashes.append(hashlib.sha256(json.dumps(doc["content"], sort_keys=True).encode()).hexdigest())

    conn.execute(
        """INSERT INTO claim_details
           (claim_id, member_id, patient_name, doctor_name, doctor_registration,
            hospital_name, diagnosis, treatment, treatment_date, total_amount,
            medicines, line_items, file_hashes, file_paths)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id,
            member_id,
            extracted_data.get("patient_name"),
            extracted_data.get("doctor_name"),
            extracted_data.get("doctor_registration"),
            extracted_data.get("hospital_name"),
            extracted_data.get("diagnosis"),
            extracted_data.get("treatment"),
            extracted_data.get("treatment_date"),
            extracted_data.get("total_amount"),
            json.dumps(extracted_data.get("medicines", [])),
            json.dumps(extracted_data.get("line_items", [])),
            json.dumps(file_hashes),
            json.dumps(file_paths or []),
        ),
    )
    conn.commit()


def check_duplicate_claim(member_id: str, extracted_data: dict, documents: list[dict]) -> list[dict]:
    """Check if this claim looks like a duplicate based on extracted details.
    Checks: same file hash, same doctor+date+amount, same doctor+amount (any date), same bill number."""
    import hashlib
    conn = get_connection()
    duplicates = []

    # Only check against claims that were actually processed (not ACTION_REQUIRED or UNDER_REVIEW)
    processed_claims = conn.execute(
        """SELECT cd.claim_id, cd.file_hashes, cd.doctor_name, cd.treatment_date, cd.total_amount, cd.bill_number
           FROM claim_details cd
           JOIN claims c ON cd.claim_id = c.claim_id
           WHERE cd.member_id = ? AND c.status IN ('APPROVED', 'PARTIAL', 'REJECTED', 'MANUAL_REVIEW')""",
        (member_id,),
    ).fetchall()

    # Check 1: Exact file hash match (same file uploaded again)
    for doc in documents:
        content_hash = None
        if doc.get("file_data"):
            content_hash = hashlib.sha256(doc["file_data"].encode()).hexdigest()
        elif doc.get("content"):
            content_hash = hashlib.sha256(json.dumps(doc["content"], sort_keys=True).encode()).hexdigest()

        if content_hash:
            for row in processed_claims:
                stored_hashes = json.loads(row["file_hashes"]) if row["file_hashes"] else []
                if content_hash in stored_hashes:
                    duplicates.append({
                        "type": "EXACT_FILE_MATCH",
                        "previous_claim_id": row["claim_id"],
                        "detail": f"Same file was submitted in claim {row['claim_id']}",
                    })
                    break

    # Check 2: Same doctor + same date + same amount (likely same visit)
    doctor = extracted_data.get("doctor_name")
    date = extracted_data.get("treatment_date")
    amount = extracted_data.get("total_amount")

    if doctor and date and amount:
        for row in processed_claims:
            if row["doctor_name"] == doctor and row["treatment_date"] == date and row["total_amount"] == amount:
                duplicates.append({
                    "type": "SAME_VISIT",
                    "previous_claim_id": row["claim_id"],
                    "detail": f"A claim for the same doctor ({doctor}), date ({date}), and amount (₹{amount:,.0f}) was already submitted in claim {row['claim_id']}",
                })
                break

    # Check 3: Same doctor + same amount, different date (possible date manipulation)
    if doctor and amount and not any(d["type"] == "SAME_VISIT" for d in duplicates):
        for row in processed_claims:
            if row["doctor_name"] == doctor and row["total_amount"] == amount and row["treatment_date"] != (date or ""):
                duplicates.append({
                    "type": "SAME_DOCTOR_AMOUNT",
                    "previous_claim_id": row["claim_id"],
                    "detail": f"A claim with the same doctor ({doctor}) and amount (₹{amount:,.0f}) was submitted on {row['treatment_date']} in claim {row['claim_id']} — possible duplicate with altered date",
                })
                break

    # Check 4: Same bill number (definitive duplicate)
    bill_number = extracted_data.get("bill_number")
    if bill_number:
        for row in processed_claims:
            if row["bill_number"] == bill_number:
                duplicates.append({
                    "type": "SAME_BILL_NUMBER",
                    "previous_claim_id": row["claim_id"],
                    "detail": f"Bill number {bill_number} was already used in claim {row['claim_id']}",
                })
                break

    return duplicates


def get_member_claims_history(member_id: str, date: Optional[str] = None) -> list[dict]:
    """Get claims history for fraud detection."""
    conn = get_connection()
    if date:
        rows = conn.execute(
            "SELECT claim_id, claim_date as date, amount, provider FROM claims_history WHERE member_id = ? AND claim_date = ?",
            (member_id, date),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT claim_id, claim_date as date, amount, provider FROM claims_history WHERE member_id = ? ORDER BY claim_date DESC LIMIT 30",
            (member_id,),
        ).fetchall()
    return [dict(row) for row in rows]

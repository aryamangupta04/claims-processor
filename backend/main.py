from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from models import ClaimSubmission, ClaimDecision, Decision
from agents.orchestrator import process_claim
from policy_engine import load_policy
import database
import email_service
import auth

app = FastAPI(
    title="Plum Claims Processing System",
    description="Multi-agent health insurance claims processing pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "plum2024"


def verify_admin(request: Request):
    """Verify admin access — accepts JWT Bearer token or HTTP Basic auth."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = auth.verify_token(request)
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        return payload.get("name", "admin")
    elif auth_header.startswith("Basic "):
        import base64
        decoded = base64.b64decode(auth_header[6:]).decode()
        username, password = decoded.split(":", 1)
        if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        return username
    else:
        raise HTTPException(status_code=401, detail="Missing authorization")


@app.on_event("startup")
async def startup():
    load_policy()
    database.get_connection()


@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "claims-processor"}


def _process_claim_background(claim: ClaimSubmission, claim_id: str):
    """Process a claim in the background and update the DB when done."""
    try:
        decision = process_claim(claim)
        decision_dict = decision.model_dump()
        decision_dict["claim_id"] = claim_id
        decision_dict["member_id"] = claim.member_id
        decision_dict["policy_id"] = claim.policy_id
        decision_dict["claim_category"] = claim.claim_category.value
        decision_dict["treatment_date"] = claim.treatment_date
        decision_dict["hospital_name"] = claim.hospital_name
        decision_dict["trace"] = [step.model_dump() for step in decision.trace]

        # Update the existing UNDER_REVIEW claim with the final decision
        conn = database.get_connection()
        import json
        conn.execute(
            """UPDATE claims SET status=?, approved_amount=?, confidence=?, summary=?, trace=?, full_decision=?
               WHERE claim_id=?""",
            (
                decision.status.value,
                decision.approved_amount,
                decision.confidence,
                decision.summary,
                json.dumps(decision_dict.get("trace", [])),
                json.dumps(decision_dict),
                claim_id,
            ),
        )
        conn.commit()

        # Notify admin if manual review needed
        if decision.status.value == "MANUAL_REVIEW":
            member = database.get_member(claim.member_id)
            email_service.notify_admin_manual_review(
                claim_id=claim_id,
                member_name=member["name"] if member else claim.member_id,
                amount=claim.claimed_amount,
                reason=decision.summary,
            )

        # Save uploaded files
        doc_dicts = [d.model_dump() for d in claim.documents]
        file_paths = database.save_uploaded_files(claim_id, claim.member_id, doc_dicts)

        # Store claim details for duplicate detection
        extraction_trace = next((t for t in decision_dict.get("trace", []) if t.get("agent") == "extraction"), {})
        ext_details = extraction_trace.get("details", {})
        extracted_info = {
            "patient_name": ext_details.get("patient_name"),
            "doctor_name": ext_details.get("doctor", "").split(" (")[0] if ext_details.get("doctor") else None,
            "doctor_registration": None,
            "hospital_name": ext_details.get("hospital") or claim.hospital_name,
            "diagnosis": ext_details.get("diagnosis"),
            "treatment": None,
            "treatment_date": claim.treatment_date,
            "bill_number": ext_details.get("bill_number"),
            "total_amount": claim.claimed_amount,
            "medicines": [],
            "line_items": [],
        }
        database.save_claim_details(claim_id, claim.member_id, extracted_info, doc_dicts, file_paths)

    except Exception as e:
        conn = database.get_connection()
        import json
        conn.execute(
            "UPDATE claims SET status=?, summary=? WHERE claim_id=?",
            ("MANUAL_REVIEW", f"Processing error: {str(e)}", claim_id),
        )
        conn.commit()


@app.post("/api/claims")
async def submit_claim(claim: ClaimSubmission, request: Request):
    """Submit a claim — requires auth. Identity comes from token, not request body."""
    user = auth.require_member(request)
    import uuid
    claim_id = f"CLM_{uuid.uuid4().hex[:8].upper()}"

    # Enforce identity from token — members can only submit claims as themselves
    if user["role"] != "admin":
        claim.member_id = user["member_id"]
        claim.member_name = user.get("name")

    # Verify member exists
    member = database.get_member(claim.member_id)
    if not member:
        return {
            "claim_id": claim_id,
            "status": "REJECTED",
            "summary": f"Employee ID '{claim.member_id}' not found.",
            "error_message": "Please check your Employee ID and try again.",
        }

    # Save as UNDER_REVIEW immediately
    import json
    conn = database.get_connection()
    conn.execute(
        """INSERT INTO claims (claim_id, member_id, member_name, policy_id, claim_category,
           treatment_date, claimed_amount, hospital_name, status, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim_id, claim.member_id, member["name"], claim.policy_id,
            claim.claim_category.value, claim.treatment_date, claim.claimed_amount,
            claim.hospital_name, "UNDER_REVIEW", "Claim is being processed...",
        ),
    )
    conn.commit()

    # Process in background thread
    thread = threading.Thread(target=_process_claim_background, args=(claim, claim_id))
    thread.start()

    return {
        "claim_id": claim_id,
        "status": "UNDER_REVIEW",
        "member_name": member["name"],
        "claimed_amount": claim.claimed_amount,
        "summary": "Your claim has been received and is being processed. You will be notified once a decision is made.",
    }


@app.get("/api/claims/{claim_id}")
async def get_claim(claim_id: str, request: Request):
    """Get claim status — requires auth, members can only access their own claims."""
    user = auth.require_member(request)
    conn = database.get_connection()

    # Check ownership
    owner_row = conn.execute("SELECT member_id FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
    if owner_row and user["role"] != "admin" and owner_row["member_id"] != user["member_id"]:
        raise HTTPException(status_code=403, detail="You can only access your own claims")

    claim_data = database.get_claim(claim_id)
    if not claim_data:
        row = conn.execute(
            "SELECT claim_id, member_name, status, claimed_amount, summary FROM claims WHERE claim_id=?",
            (claim_id,),
        ).fetchone()
        if row:
            return {
                "claim_id": row["claim_id"],
                "status": row["status"],
                "member_name": row["member_name"],
                "claimed_amount": row["claimed_amount"],
                "summary": row["summary"],
            }
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim_data


@app.get("/api/claims")
async def list_claims(request: Request):
    """List claims — members see only their own, admins see all."""
    user = auth.require_member(request)
    if user["role"] == "admin":
        claims = database.get_all_claims()
    else:
        conn = database.get_connection()
        rows = conn.execute(
            "SELECT claim_id, member_id, member_name, status, claim_category, claimed_amount, approved_amount, confidence, created_at FROM claims WHERE member_id=? ORDER BY created_at DESC",
            (user["member_id"],),
        ).fetchall()
        claims = [dict(row) for row in rows]
    return {"claims": claims}


# ============ ADMIN ENDPOINTS (require login) ============

@app.get("/api/admin/claims")
async def admin_list_claims(request: Request):
    """Admin: list all claims with full details."""
    verify_admin(request)
    claims = database.get_all_claims()
    return {"claims": claims}


@app.get("/api/admin/claims/{claim_id}")
async def admin_get_claim(claim_id: str, request: Request):
    """Admin: get full claim decision with trace."""
    verify_admin(request)
    claim_data = database.get_claim(claim_id)
    if not claim_data:
        conn = database.get_connection()
        row = conn.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if row:
            return dict(row)
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim_data


@app.get("/api/admin/claims/{claim_id}/details")
async def admin_get_claim_details(claim_id: str, request: Request):
    """Admin: get extracted claim details (for fraud review)."""
    verify_admin(request)
    conn = database.get_connection()
    row = conn.execute("SELECT * FROM claim_details WHERE claim_id=?", (claim_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Claim details not found")
    return dict(row)


@app.post("/api/admin/claims/{claim_id}/override")
async def admin_override_claim(claim_id: str, override: dict, request: Request):
    """Admin: override a claim decision."""
    username = verify_admin(request)
    conn = database.get_connection()
    new_status = override.get("status")
    reason = override.get("reason", "Admin override")
    if new_status not in ["APPROVED", "REJECTED", "MANUAL_REVIEW"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    conn.execute(
        "UPDATE claims SET status=?, summary=? WHERE claim_id=?",
        (new_status, f"Admin override: {reason}", claim_id),
    )
    conn.commit()

    # Notify member of the decision
    claim_row = conn.execute("SELECT member_id, member_name FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
    if claim_row:
        member = database.get_member(claim_row["member_id"])
        if member and member.get("email"):
            email_service.notify_member_status_update(
                to_email=member["email"],
                claim_id=claim_id,
                member_name=claim_row["member_name"] or claim_row["member_id"],
                status=new_status,
                summary=f"Admin override: {reason}",
            )

    return {"claim_id": claim_id, "status": new_status, "overridden_by": username}


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    """Admin: dashboard stats."""
    verify_admin(request)
    conn = database.get_connection()
    total = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM claims WHERE status='APPROVED'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM claims WHERE status='REJECTED'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM claims WHERE status='UNDER_REVIEW'").fetchone()[0]
    manual = conn.execute("SELECT COUNT(*) FROM claims WHERE status='MANUAL_REVIEW'").fetchone()[0]
    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "pending": pending,
        "manual_review": manual,
    }


# ============ PUBLIC ENDPOINTS ============

@app.get("/api/policy/members")
async def get_members(request: Request):
    auth.require_member(request)
    members = database.get_all_members()
    return {"members": members}


@app.get("/api/policy/hospitals")
async def get_hospitals():
    hospitals = database.get_all_network_hospitals()
    return {"hospitals": hospitals}


@app.get("/api/policy/categories")
async def get_categories():
    policy = load_policy()
    return {"categories": list(policy["document_requirements"].keys())}


@app.get("/api/members/{member_id}")
async def get_member_endpoint(member_id: str, request: Request):
    """Get member info — can only access your own data (IDOR protection)."""
    auth.require_own_data(request, member_id)
    member = database.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@app.get("/api/members/{member_id}/claims")
async def get_member_claims(member_id: str, request: Request):
    """Get member's claims — can only access your own (IDOR protection)."""
    auth.require_own_data(request, member_id)
    history = database.get_member_claims_history(member_id)
    return {"claims": history}


@app.post("/api/run-test-suite")
async def run_test_suite(request: Request):
    """Run all 12 test cases through the pipeline and return results."""
    auth.require_member(request)
    import json as json_mod
    from pathlib import Path

    test_cases_path = Path(__file__).parent / "test_cases.json"
    if not test_cases_path.exists():
        test_cases_path = Path(__file__).parent.parent / "test_cases.json"

    with open(test_cases_path) as f:
        test_data = json_mod.load(f)

    results = []
    for tc in test_data["test_cases"]:
        inp = tc["input"]
        docs = []
        for d in inp["documents"]:
            doc = {"file_id": d.get("file_id", "F000")}
            if "actual_type" in d: doc["actual_type"] = d["actual_type"]
            if "quality" in d: doc["quality"] = d["quality"]
            if "content" in d: doc["content"] = d["content"]
            if "patient_name_on_doc" in d: doc["patient_name_on_doc"] = d["patient_name_on_doc"]
            if "file_name" in d: doc["file_name"] = d["file_name"]
            docs.append(doc)

        claim_data = {
            "member_id": inp["member_id"],
            "policy_id": inp.get("policy_id", "PLUM_GHI_2024"),
            "claim_category": inp["claim_category"],
            "treatment_date": inp["treatment_date"],
            "claimed_amount": inp["claimed_amount"],
            "documents": docs,
        }
        if "hospital_name" in inp: claim_data["hospital_name"] = inp["hospital_name"]
        if "ytd_claims_amount" in inp: claim_data["ytd_claims_amount"] = inp["ytd_claims_amount"]
        if "simulate_component_failure" in inp: claim_data["simulate_component_failure"] = inp["simulate_component_failure"]

        # Seed claims history for TC009
        if "claims_history" in inp:
            conn = database.get_connection()
            for h in inp["claims_history"]:
                conn.execute(
                    "INSERT OR IGNORE INTO claims_history (member_id, claim_id, claim_date, amount, provider, status) VALUES (?, ?, ?, ?, ?, ?)",
                    (inp["member_id"], h["claim_id"], h["date"], h["amount"], h.get("provider"), "APPROVED"),
                )
            conn.commit()

        claim = ClaimSubmission(**claim_data)
        decision = process_claim(claim)

        # Clean up seeded history
        if "claims_history" in inp:
            conn.execute("DELETE FROM claims_history WHERE member_id = ? AND claim_id LIKE 'CLM_008%'", (inp["member_id"],))
            conn.commit()

        expected = tc["expected"]
        matched = True
        if expected.get("decision") and decision.status.value != expected["decision"]:
            matched = False
        if "approved_amount" in expected and expected["approved_amount"] is not None:
            if decision.approved_amount != expected["approved_amount"]:
                matched = False

        results.append({
            "case_id": tc["case_id"],
            "case_name": tc["case_name"],
            "expected_decision": expected.get("decision"),
            "actual_decision": decision.status.value,
            "expected_amount": expected.get("approved_amount"),
            "actual_amount": decision.approved_amount,
            "matched": matched,
            "confidence": decision.confidence,
            "summary": decision.summary,
            "trace": [step.model_dump() for step in decision.trace],
        })

    passed = sum(1 for r in results if r["matched"])
    return {"total": len(results), "passed": passed, "results": results}


@app.post("/api/admin/login")
async def admin_login(credentials: dict):
    """Verify admin credentials and return JWT token."""
    if credentials.get("username") == ADMIN_USERNAME and credentials.get("password") == ADMIN_PASSWORD:
        token = auth.create_token("ADMIN", ADMIN_USERNAME, "admin")
        return {"success": True, "username": ADMIN_USERNAME, "role": "admin", "token": token}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/login")
async def user_login(credentials: dict):
    """Member login — returns JWT token + user info for autofill."""
    member_id = credentials.get("member_id", "")
    password = credentials.get("password", "")
    user = database.authenticate_user(member_id, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid Employee ID or password")
    member = database.get_member(user["member_id"])
    token = auth.create_token(user["member_id"], user["name"], user["role"])
    return {
        "success": True,
        "token": token,
        "user": user,
        "member": member,
    }


@app.get("/api/auth/me/{member_id}")
async def get_user_info(member_id: str):
    """Get user info for session restore."""
    member = database.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"member": member}

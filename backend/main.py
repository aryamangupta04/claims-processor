from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from models import ClaimSubmission, ClaimDecision, Decision
from agents.orchestrator import process_claim
from policy_engine import load_policy
import database
import email_service

app = FastAPI(
    title="Plum Claims Processing System",
    description="Multi-agent health insurance claims processing pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "plum2024"


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return credentials.username


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
async def submit_claim(claim: ClaimSubmission):
    """Submit a claim — returns immediately with UNDER_REVIEW status, processes in background."""
    import uuid
    claim_id = f"CLM_{uuid.uuid4().hex[:8].upper()}"

    # Resolve member
    if not claim.member_id and claim.member_name:
        member = database.get_member_by_name(claim.member_name)
        if member:
            claim.member_id = member["member_id"]
        else:
            return {
                "claim_id": claim_id,
                "status": "REJECTED",
                "summary": f"Member '{claim.member_name}' not found in our system.",
                "error_message": "No member found with that name. Please ensure the name matches your policy records.",
            }
    elif not claim.member_id:
        return {
            "claim_id": claim_id,
            "status": "REJECTED",
            "summary": "No member information provided.",
            "error_message": "Please provide your full name and Employee ID.",
        }

    # Verify member exists
    member = database.get_member(claim.member_id)
    if not member:
        return {
            "claim_id": claim_id,
            "status": "REJECTED",
            "summary": f"Employee ID '{claim.member_id}' not found.",
            "error_message": "Please check your Employee ID and try again.",
        }

    # Verify name matches if both provided
    if claim.member_name and member["name"].lower() != claim.member_name.strip().lower():
        return {
            "claim_id": claim_id,
            "status": "REJECTED",
            "summary": f"Name '{claim.member_name}' does not match Employee ID '{claim.member_id}' (registered to '{member['name']}').",
            "error_message": "The name and Employee ID don't match. Please verify your details.",
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
async def get_claim(claim_id: str):
    """Get claim status — used for polling."""
    claim_data = database.get_claim(claim_id)
    if not claim_data:
        # Check if it's still UNDER_REVIEW (no full_decision yet)
        conn = database.get_connection()
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
async def list_claims():
    claims = database.get_all_claims()
    return {"claims": claims}


# ============ ADMIN ENDPOINTS (require login) ============

@app.get("/api/admin/claims")
async def admin_list_claims(username: str = Depends(verify_admin)):
    """Admin: list all claims with full details."""
    claims = database.get_all_claims()
    return {"claims": claims}


@app.get("/api/admin/claims/{claim_id}")
async def admin_get_claim(claim_id: str, username: str = Depends(verify_admin)):
    """Admin: get full claim decision with trace."""
    claim_data = database.get_claim(claim_id)
    if not claim_data:
        conn = database.get_connection()
        row = conn.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if row:
            return dict(row)
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim_data


@app.get("/api/admin/claims/{claim_id}/details")
async def admin_get_claim_details(claim_id: str, username: str = Depends(verify_admin)):
    """Admin: get extracted claim details (for fraud review)."""
    conn = database.get_connection()
    row = conn.execute("SELECT * FROM claim_details WHERE claim_id=?", (claim_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Claim details not found")
    return dict(row)


@app.post("/api/admin/claims/{claim_id}/override")
async def admin_override_claim(claim_id: str, override: dict, username: str = Depends(verify_admin)):
    """Admin: override a claim decision."""
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
async def admin_stats(username: str = Depends(verify_admin)):
    """Admin: dashboard stats."""
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
async def get_members():
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
async def get_member_endpoint(member_id: str):
    member = database.get_member(member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@app.get("/api/members/{member_id}/claims")
async def get_member_claims(member_id: str):
    history = database.get_member_claims_history(member_id)
    return {"claims": history}


@app.post("/api/admin/login")
async def admin_login(credentials: dict):
    """Verify admin credentials and return success."""
    if credentials.get("username") == ADMIN_USERNAME and credentials.get("password") == ADMIN_PASSWORD:
        return {"success": True, "username": ADMIN_USERNAME, "role": "admin"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/api/auth/login")
async def user_login(credentials: dict):
    """Member login — returns user info for autofill."""
    member_id = credentials.get("member_id", "")
    password = credentials.get("password", "")
    user = database.authenticate_user(member_id, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid Employee ID or password")
    # Get full member info for autofill
    member = database.get_member(user["member_id"])
    return {
        "success": True,
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

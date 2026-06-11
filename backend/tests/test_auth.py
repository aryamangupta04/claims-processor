"""Test JWT authentication and authorization."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def get_token(member_id: str) -> str:
    r = client.post("/api/auth/login", json={"member_id": member_id, "password": member_id.lower()})
    assert r.status_code == 200
    return r.json()["token"]


def test_no_token_rejected():
    r = client.post("/api/claims", json={"claim_category": "CONSULTATION", "treatment_date": "2024-11-01", "claimed_amount": 1500, "documents": []})
    assert r.status_code == 401


def test_member_cannot_submit_as_another_member():
    """EMP001 cannot submit a claim with member_id=EMP002 — token identity overrides request body."""
    token = get_token("EMP001")
    r = client.post(
        "/api/claims",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "member_id": "EMP002",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "F001", "actual_type": "PRESCRIPTION", "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Fever"}},
                {"file_id": "F002", "actual_type": "HOSPITAL_BILL", "content": {"patient_name": "Rajesh Kumar", "total": 1500}},
            ],
        },
    )
    data = r.json()
    # Should be submitted as EMP001 regardless of what body says
    assert data["status"] == "UNDER_REVIEW"
    # Verify it was saved as EMP001's claim
    import time
    time.sleep(1)
    claim_id = data["claim_id"]
    r2 = client.get(f"/api/claims/{claim_id}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200


def test_member_cannot_read_other_members_claim():
    """EMP001 cannot fetch EMP002's claim by ID."""
    # EMP002 submits a claim
    token_b = get_token("EMP002")
    r = client.post(
        "/api/claims",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1000,
            "documents": [
                {"file_id": "F001", "actual_type": "PRESCRIPTION", "content": {"patient_name": "Priya Singh", "diagnosis": "Cold"}},
                {"file_id": "F002", "actual_type": "HOSPITAL_BILL", "content": {"patient_name": "Priya Singh", "total": 1000}},
            ],
        },
    )
    claim_id = r.json()["claim_id"]

    # EMP001 tries to read it
    token_a = get_token("EMP001")
    r2 = client.get(f"/api/claims/{claim_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r2.status_code == 403
    assert "your own claims" in r2.json()["detail"].lower()


def test_member_can_read_own_claim():
    """EMP001 can read their own claim."""
    token = get_token("EMP001")
    r = client.post(
        "/api/claims",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "F001", "actual_type": "PRESCRIPTION", "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Fever"}},
                {"file_id": "F002", "actual_type": "HOSPITAL_BILL", "content": {"patient_name": "Rajesh Kumar", "total": 1500}},
            ],
        },
    )
    claim_id = r.json()["claim_id"]
    r2 = client.get(f"/api/claims/{claim_id}", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200

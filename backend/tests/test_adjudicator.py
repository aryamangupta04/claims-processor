"""Unit tests for the adjudicator agent — decision logic, check ordering, edge cases."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from models import ClaimSubmission, Decision, ExtractedData
from agents.adjudicator import adjudicate, AdjudicationResult
from agents.fraud_detector import FraudResult
from policy_engine import load_policy


@pytest.fixture(autouse=True)
def _load():
    load_policy()


def _make_claim(**kwargs) -> ClaimSubmission:
    defaults = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "documents": [
            {"file_id": "F001", "actual_type": "PRESCRIPTION", "content": {"patient_name": "Rajesh Kumar"}},
            {"file_id": "F002", "actual_type": "HOSPITAL_BILL", "content": {"patient_name": "Rajesh Kumar", "total": 1500}},
        ],
    }
    defaults.update(kwargs)
    return ClaimSubmission(**defaults)


def _make_extracted(**kwargs) -> ExtractedData:
    defaults = {
        "patient_name": "Rajesh Kumar",
        "diagnosis": "Viral Fever",
        "doctor_name": "Dr. Sharma",
        "total_amount": 1500,
        "line_items": [],
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return ExtractedData(**defaults)


def _no_fraud() -> FraudResult:
    return FraudResult(flagged=False, signals=[], fraud_score=0.0, details={})


def _fraud_flagged() -> FraudResult:
    return FraudResult(
        flagged=True,
        signals=["Multiple same-day claims"],
        fraud_score=0.7,
        details={"same_day_claims": 3},
    )


# --- Basic approval ---

def test_clean_approval():
    claim = _make_claim()
    extracted = _make_extracted()
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.APPROVED
    assert result.approved_amount == 1350  # 1500 - 10% copay


def test_approved_with_copay_deduction():
    claim = _make_claim(claimed_amount=2000)
    extracted = _make_extracted(total_amount=2000)
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.APPROVED
    assert result.approved_amount == 1800  # 2000 - 10%
    assert any(d["type"] == "copay" for d in result.deductions)


# --- Fraud routing ---

def test_fraud_routes_to_manual_review():
    claim = _make_claim()
    extracted = _make_extracted()
    result, trace = adjudicate(claim, extracted, _fraud_flagged())
    assert result.decision == Decision.MANUAL_REVIEW
    assert "same-day" in result.reasons[0].lower() or "Multiple" in result.reasons[0]


# --- Waiting period ---

def test_waiting_period_rejection():
    claim = _make_claim(
        member_id="EMP005",
        treatment_date="2024-10-15",
        claimed_amount=3000,
    )
    extracted = _make_extracted(
        patient_name="Vikram Joshi",
        diagnosis="Type 2 Diabetes Mellitus",
        total_amount=3000,
    )
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.REJECTED
    assert any("waiting period" in c["detail"].lower() for c in result.checks if c["result"] == "FAIL")


# --- Per-claim limit ---

def test_per_claim_limit_exceeded():
    claim = _make_claim(claimed_amount=7500)
    extracted = _make_extracted(diagnosis="Gastroenteritis", total_amount=7500)
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.REJECTED
    assert any("per-claim limit" in r.lower() or "exceeds" in r.lower() for r in result.reasons)


def test_per_claim_limit_boundary():
    """Exactly at the limit should pass."""
    claim = _make_claim(claimed_amount=5000)
    extracted = _make_extracted(diagnosis="Flu", total_amount=5000)
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.APPROVED


# --- Network discount + copay order ---

def test_network_discount_before_copay():
    """TC010: ₹4,500 at Apollo → discount first → copay second → ₹3,240"""
    claim = _make_claim(
        member_id="EMP010",
        claimed_amount=4500,
        hospital_name="Apollo Hospitals",
    )
    extracted = _make_extracted(
        patient_name="Deepak Shah",
        diagnosis="Acute Bronchitis",
        hospital_name="Apollo Hospitals",
        total_amount=4500,
    )
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.APPROVED
    assert result.approved_amount == 3240


# --- Partial exclusion (dental) ---

def test_dental_partial_exclusion():
    """TC006: Root canal covered, whitening excluded → PARTIAL ₹8,000"""
    claim = _make_claim(
        member_id="EMP002",
        claim_category="DENTAL",
        claimed_amount=12000,
        documents=[
            {"file_id": "F001", "actual_type": "DENTAL_REPORT", "content": {"patient_name": "Priya Singh"}},
        ],
    )
    extracted = _make_extracted(
        patient_name="Priya Singh",
        diagnosis="Dental pain",
        line_items=[
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ],
        total_amount=12000,
    )
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.PARTIAL
    assert result.approved_amount == 8000
    assert len(result.line_item_decisions) == 2


# --- Pre-authorization ---

def test_pre_auth_required_rejects():
    """TC007: MRI > ₹10,000 without pre-auth → REJECTED"""
    claim = _make_claim(
        member_id="EMP007",
        claim_category="DIAGNOSTIC",
        claimed_amount=15000,
        documents=[
            {"file_id": "F001", "actual_type": "DIAGNOSTIC_REPORT", "content": {"patient_name": "Suresh Patil"}},
        ],
    )
    extracted = _make_extracted(
        patient_name="Suresh Patil",
        diagnosis="Suspected Lumbar Disc Herniation",
        line_items=[{"description": "MRI Lumbar Spine", "amount": 15000}],
        total_amount=15000,
    )
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.REJECTED
    assert any("pre-authorization" in r.lower() for r in result.reasons)


# --- Member not found ---

def test_unknown_member_rejected():
    claim = _make_claim(member_id="EMP999")
    extracted = _make_extracted()
    result, trace = adjudicate(claim, extracted, _no_fraud())
    assert result.decision == Decision.REJECTED
    assert any("not found" in c["detail"].lower() for c in result.checks)


# --- Simulated failure ---

def test_simulated_failure_returns_manual_review():
    claim = _make_claim()
    extracted = _make_extracted()
    result, trace = adjudicate(claim, extracted, _no_fraud(), simulate_failure=True)
    assert result.decision == Decision.MANUAL_REVIEW


# --- Check ordering verification ---

def test_checks_include_all_stages():
    """A clean approval should produce checks for all stages."""
    claim = _make_claim()
    extracted = _make_extracted()
    result, trace = adjudicate(claim, extracted, _no_fraud())
    check_names = [c["check"] for c in result.checks]
    assert "member_eligible" in check_names
    assert "fraud_check" in check_names
    assert "waiting_period" in check_names
    assert "exclusions" in check_names
    assert "pre_authorization" in check_names
    assert "per_claim_limit" in check_names

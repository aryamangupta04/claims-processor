"""Test all 12 test cases from test_cases.json against the pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from models import ClaimSubmission, Decision
from agents.orchestrator import process_claim


# TC001: Wrong Document Uploaded
def test_tc001_wrong_document():
    claim = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            {"file_id": "F001", "file_name": "dr_sharma_prescription.jpg", "actual_type": "PRESCRIPTION"},
            {"file_id": "F002", "file_name": "another_prescription.jpg", "actual_type": "PRESCRIPTION"},
        ],
    )
    result = process_claim(claim)
    # Must stop before making a claim decision
    assert result.error_message is not None or result.requires_action is not None
    # Must mention what was uploaded and what's needed
    msg = result.summary + " " + (result.error_message or "")
    assert "prescription" in msg.lower()
    assert "hospital bill" in msg.lower()


# TC002: Unreadable Document
def test_tc002_unreadable_document():
    claim = ClaimSubmission(
        member_id="EMP004",
        policy_id="PLUM_GHI_2024",
        claim_category="PHARMACY",
        treatment_date="2024-10-25",
        claimed_amount=800,
        documents=[
            {"file_id": "F003", "file_name": "prescription.jpg", "actual_type": "PRESCRIPTION", "quality": "GOOD"},
            {"file_id": "F004", "file_name": "blurry_bill.jpg", "actual_type": "PHARMACY_BILL", "quality": "UNREADABLE"},
        ],
    )
    result = process_claim(claim)
    msg = result.summary + " " + (result.error_message or "")
    assert "blurry" in msg.lower() or "unclear" in msg.lower() or "unreadable" in msg.lower() or "clearer" in msg.lower()
    assert "pharmacy bill" in msg.lower() or "re-upload" in msg.lower() or "photo" in msg.lower()


# TC003: Documents Belong to Different Patients
def test_tc003_patient_mismatch():
    claim = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=[
            {"file_id": "F005", "file_name": "prescription_rajesh.jpg", "actual_type": "PRESCRIPTION", "patient_name_on_doc": "Rajesh Kumar"},
            {"file_id": "F006", "file_name": "bill_arjun.jpg", "actual_type": "HOSPITAL_BILL", "patient_name_on_doc": "Arjun Mehta"},
        ],
    )
    result = process_claim(claim)
    msg = result.error_message or result.requires_action or result.summary
    assert "Rajesh Kumar" in msg
    assert "Arjun Mehta" in msg


# TC004: Clean Consultation — Full Approval
def test_tc004_clean_approval():
    claim = ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
        ytd_claims_amount=5000,
        documents=[
            {
                "file_id": "F007",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. Arun Sharma",
                    "doctor_registration": "KA/45678/2015",
                    "patient_name": "Rajesh Kumar",
                    "date": "2024-11-01",
                    "diagnosis": "Viral Fever",
                    "medicines": ["Paracetamol 650mg", "Vitamin C 500mg"],
                },
            },
            {
                "file_id": "F008",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "hospital_name": "City Clinic, Bengaluru",
                    "patient_name": "Rajesh Kumar",
                    "date": "2024-11-01",
                    "line_items": [
                        {"description": "Consultation Fee", "amount": 1000},
                        {"description": "CBC Test", "amount": 300},
                        {"description": "Dengue NS1 Test", "amount": 200},
                    ],
                    "total": 1500,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.APPROVED
    assert result.approved_amount == 1350  # 10% copay on 1500
    assert result.confidence > 0.85


# TC005: Waiting Period — Diabetes
def test_tc005_waiting_period():
    claim = ClaimSubmission(
        member_id="EMP005",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-15",
        claimed_amount=3000,
        documents=[
            {
                "file_id": "F009",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. Sunil Mehta",
                    "doctor_registration": "GJ/56789/2014",
                    "patient_name": "Vikram Joshi",
                    "diagnosis": "Type 2 Diabetes Mellitus",
                    "medicines": ["Metformin 500mg", "Glimepiride 1mg"],
                },
            },
            {
                "file_id": "F010",
                "actual_type": "HOSPITAL_BILL",
                "content": {"patient_name": "Vikram Joshi", "date": "2024-10-15", "total": 3000},
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.REJECTED
    assert any("waiting" in r.lower() or "WAITING" in r for r in result.rejection_reasons)
    # Must state eligibility date
    trace_text = str(result.trace)
    assert "2024" in trace_text  # eligible date mentioned


# TC006: Dental Partial Approval
def test_tc006_dental_partial():
    claim = ClaimSubmission(
        member_id="EMP002",
        policy_id="PLUM_GHI_2024",
        claim_category="DENTAL",
        treatment_date="2024-10-15",
        claimed_amount=12000,
        documents=[
            {
                "file_id": "F011",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "hospital_name": "Smile Dental Clinic",
                    "patient_name": "Priya Singh",
                    "line_items": [
                        {"description": "Root Canal Treatment", "amount": 8000},
                        {"description": "Teeth Whitening", "amount": 4000},
                    ],
                    "total": 12000,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.PARTIAL
    assert result.approved_amount == 8000
    # Must itemize decisions
    assert len(result.line_item_decisions) >= 2


# TC007: MRI Without Pre-Authorization
def test_tc007_pre_auth_missing():
    claim = ClaimSubmission(
        member_id="EMP007",
        policy_id="PLUM_GHI_2024",
        claim_category="DIAGNOSTIC",
        treatment_date="2024-11-02",
        claimed_amount=15000,
        documents=[
            {
                "file_id": "F012",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. Venkat Rao",
                    "doctor_registration": "AP/67890/2017",
                    "diagnosis": "Suspected Lumbar Disc Herniation",
                    "tests_ordered": ["MRI Lumbar Spine"],
                },
            },
            {
                "file_id": "F013",
                "actual_type": "LAB_REPORT",
                "content": {"test_name": "MRI Lumbar Spine"},
            },
            {
                "file_id": "F014",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "line_items": [{"description": "MRI Lumbar Spine", "amount": 15000}],
                    "total": 15000,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.REJECTED
    assert any("pre-auth" in r.lower() or "pre_auth" in r.lower() or "authorization" in r.lower() for r in result.rejection_reasons)


# TC008: Per-Claim Limit Exceeded
def test_tc008_per_claim_exceeded():
    claim = ClaimSubmission(
        member_id="EMP003",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-20",
        claimed_amount=7500,
        ytd_claims_amount=10000,
        documents=[
            {
                "file_id": "F015",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. R. Gupta",
                    "doctor_registration": "DL/34567/2016",
                    "diagnosis": "Gastroenteritis",
                    "medicines": ["Antibiotics", "Probiotics", "ORS"],
                },
            },
            {
                "file_id": "F016",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "line_items": [
                        {"description": "Consultation Fee", "amount": 2000},
                        {"description": "Medicines", "amount": 5500},
                    ],
                    "total": 7500,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.REJECTED
    # Must mention both the limit and the claimed amount
    all_text = " ".join(result.rejection_reasons) + result.summary
    assert "5,000" in all_text or "5000" in all_text
    assert "7,500" in all_text or "7500" in all_text


# TC009: Fraud Signal — Multiple Same-Day Claims
def test_tc009_fraud_same_day():
    claim = ClaimSubmission(
        member_id="EMP008",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-30",
        claimed_amount=4800,
        claims_history=[
            {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"},
            {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "City Clinic B"},
            {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "Wellness Center"},
        ],
        documents=[
            {"file_id": "F017", "actual_type": "PRESCRIPTION", "content": {"diagnosis": "Migraine", "doctor_name": "Dr. S. Khan"}},
            {"file_id": "F018", "actual_type": "HOSPITAL_BILL", "content": {"total": 4800}},
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.MANUAL_REVIEW
    # Must include specific signals
    trace_text = str(result.trace)
    assert "same-day" in trace_text.lower() or "same_day" in trace_text.lower()


# TC010: Network Hospital — Discount Applied
def test_tc010_network_discount():
    claim = ClaimSubmission(
        member_id="EMP010",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-03",
        claimed_amount=4500,
        hospital_name="Apollo Hospitals",
        ytd_claims_amount=8000,
        documents=[
            {
                "file_id": "F019",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. S. Iyer",
                    "doctor_registration": "TN/56789/2013",
                    "patient_name": "Deepak Shah",
                    "diagnosis": "Acute Bronchitis",
                    "medicines": ["Amoxicillin 500mg", "Salbutamol Inhaler"],
                },
            },
            {
                "file_id": "F020",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "hospital_name": "Apollo Hospitals",
                    "patient_name": "Deepak Shah",
                    "line_items": [
                        {"description": "Consultation Fee", "amount": 1500},
                        {"description": "Medicines", "amount": 3000},
                    ],
                    "total": 4500,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.APPROVED
    # 4500 * 0.8 = 3600, 3600 * 0.9 = 3240
    assert result.approved_amount == 3240


# TC011: Component Failure — Graceful Degradation
def test_tc011_component_failure():
    claim = ClaimSubmission(
        member_id="EMP006",
        policy_id="PLUM_GHI_2024",
        claim_category="ALTERNATIVE_MEDICINE",
        treatment_date="2024-10-28",
        claimed_amount=4000,
        simulate_component_failure=True,
        documents=[
            {
                "file_id": "F021",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Vaidya T. Krishnan",
                    "doctor_registration": "AYUR/KL/2345/2019",
                    "diagnosis": "Chronic Joint Pain",
                    "treatment": "Panchakarma Therapy",
                },
            },
            {
                "file_id": "F022",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "hospital_name": "Ayur Wellness Centre",
                    "total": 4000,
                    "line_items": [
                        {"description": "Panchakarma Therapy (5 sessions)", "amount": 3000},
                        {"description": "Consultation", "amount": 1000},
                    ],
                },
            },
        ],
    )
    result = process_claim(claim)
    # Must not crash
    assert result is not None
    # Must indicate component failure in trace
    trace_text = str(result.trace)
    assert "fail" in trace_text.lower() or "error" in trace_text.lower()
    # Confidence must be lower than normal
    assert result.confidence < 0.85
    # Must still produce a decision
    assert result.status in [Decision.APPROVED, Decision.MANUAL_REVIEW]


# TC012: Excluded Treatment
def test_tc012_excluded_treatment():
    claim = ClaimSubmission(
        member_id="EMP009",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-10-18",
        claimed_amount=8000,
        documents=[
            {
                "file_id": "F023",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "doctor_name": "Dr. P. Banerjee",
                    "doctor_registration": "WB/34567/2015",
                    "diagnosis": "Morbid Obesity — BMI 37",
                    "treatment": "Bariatric Consultation and Customised Diet Plan",
                },
            },
            {
                "file_id": "F024",
                "actual_type": "HOSPITAL_BILL",
                "content": {
                    "line_items": [
                        {"description": "Bariatric Consultation", "amount": 3000},
                        {"description": "Personalised Diet and Nutrition Program", "amount": 5000},
                    ],
                    "total": 8000,
                },
            },
        ],
    )
    result = process_claim(claim)
    assert result.status == Decision.REJECTED
    assert result.confidence > 0.90

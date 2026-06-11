"""Unit tests for the policy engine — waiting periods, exclusions, limits, amount calculation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from policy_engine import (
    load_policy,
    get_member,
    get_document_requirements,
    get_category_config,
    is_network_hospital,
    check_waiting_period,
    check_exclusions,
    check_pre_authorization,
    calculate_approved_amount,
)


@pytest.fixture(autouse=True)
def _load():
    load_policy()


# --- Member lookup ---

def test_get_member_exists():
    member = get_member("EMP001")
    assert member is not None
    assert member["name"] == "Rajesh Kumar"


def test_get_member_not_found():
    assert get_member("EMP999") is None


# --- Document requirements ---

def test_document_requirements_consultation():
    reqs = get_document_requirements("CONSULTATION")
    assert "PRESCRIPTION" in reqs["required"]
    assert "HOSPITAL_BILL" in reqs["required"]


def test_document_requirements_unknown_category():
    reqs = get_document_requirements("NONEXISTENT")
    assert reqs == {}


# --- Network hospital ---

def test_network_hospital_match():
    assert is_network_hospital("Apollo Hospitals") is True


def test_network_hospital_no_match():
    assert is_network_hospital("Random Clinic") is False


def test_network_hospital_empty():
    assert is_network_hospital("") is False


# --- Waiting period ---

def test_waiting_period_passes():
    member = {"name": "Test", "join_date": "2024-04-01"}
    result = check_waiting_period(member, "2024-11-01", "Viral Fever")
    assert result["passed"] is True


def test_waiting_period_initial_fail():
    member = {"name": "Test", "join_date": "2024-10-25"}
    result = check_waiting_period(member, "2024-11-01", "Viral Fever")
    assert result["passed"] is False
    assert "initial waiting period" in result["reason"].lower()


def test_waiting_period_diabetes_fail():
    member = {"name": "Test", "join_date": "2024-09-01"}
    result = check_waiting_period(member, "2024-10-15", "Type 2 Diabetes Mellitus")
    assert result["passed"] is False
    assert "diabetes" in result["reason"].lower()
    assert result.get("eligible_date") is not None


def test_waiting_period_diabetes_passes_after_90_days():
    member = {"name": "Test", "join_date": "2024-04-01"}
    result = check_waiting_period(member, "2024-11-01", "Diabetes management")
    assert result["passed"] is True


# --- Exclusions ---

def test_exclusion_viral_fever_not_excluded():
    result = check_exclusions("Viral Fever", "", "CONSULTATION", [])
    assert result["excluded"] is False


def test_exclusion_cosmetic_excluded():
    result = check_exclusions("Cosmetic surgery", "Aesthetic nose job", "CONSULTATION", [])
    assert result["excluded"] is True
    assert result["fully_excluded"] is True


def test_exclusion_dental_partial():
    line_items = [
        {"description": "Root Canal Treatment", "amount": 8000},
        {"description": "Teeth Whitening", "amount": 4000},
    ]
    result = check_exclusions("Dental pain", "", "DENTAL", line_items)
    assert result["excluded"] is True
    assert result["fully_excluded"] is False
    assert len(result["covered_items"]) == 1
    assert len(result["excluded_items"]) == 1
    assert result["covered_items"][0]["amount"] == 8000


def test_exclusion_dental_all_covered():
    line_items = [
        {"description": "Root Canal Treatment", "amount": 8000},
        {"description": "Filling", "amount": 2000},
    ]
    result = check_exclusions("Dental pain", "", "DENTAL", line_items)
    assert result["excluded"] is False


# --- Pre-authorization ---

def test_pre_auth_not_required_consultation():
    result = check_pre_authorization("CONSULTATION", [], 5000)
    assert result["required"] is False


def test_pre_auth_required_mri_over_threshold():
    line_items = [{"description": "MRI Lumbar Spine", "amount": 15000}]
    result = check_pre_authorization("DIAGNOSTIC", line_items, 15000)
    assert result["required"] is True
    assert "pre-authorization" in result["reason"].lower()


def test_pre_auth_not_required_mri_under_threshold():
    line_items = [{"description": "MRI Lumbar Spine", "amount": 8000}]
    result = check_pre_authorization("DIAGNOSTIC", line_items, 8000)
    assert result["required"] is False


# --- Amount calculation ---

def test_calculate_amount_simple_copay():
    """TC004: ₹1,500 consultation with 10% co-pay → ₹1,350"""
    result = calculate_approved_amount(
        claimed_amount=1500,
        claim_category="CONSULTATION",
        hospital_name=None,
        line_items=[],
    )
    assert result["approved_amount"] == 1350
    assert len(result["deductions"]) == 1
    assert result["deductions"][0]["type"] == "copay"


def test_calculate_amount_network_discount_then_copay():
    """TC010: ₹4,500 at Apollo → 20% discount first (₹3,600) → 10% co-pay (₹3,240)"""
    result = calculate_approved_amount(
        claimed_amount=4500,
        claim_category="CONSULTATION",
        hospital_name="Apollo Hospitals",
        line_items=[],
    )
    assert result["approved_amount"] == 3240
    assert len(result["deductions"]) == 2
    # First deduction is network discount
    assert result["deductions"][0]["type"] == "network_discount"
    assert result["deductions"][0]["amount"] == 900
    # Second deduction is co-pay on the discounted amount
    assert result["deductions"][1]["type"] == "copay"
    assert result["deductions"][1]["amount"] == 360


def test_calculate_amount_partial_exclusion():
    """TC006: Only covered items count — ₹8,000 root canal approved"""
    covered_items = [{"description": "Root Canal Treatment", "amount": 8000}]
    result = calculate_approved_amount(
        claimed_amount=12000,
        claim_category="DENTAL",
        hospital_name=None,
        line_items=[],
        covered_items=covered_items,
    )
    assert result["approved_amount"] == 8000
    assert result["deductions"] == []


def test_discount_before_copay_order_matters():
    """Verify discount-first produces different result than copay-first."""
    # Correct: 4500 * 0.8 = 3600 * 0.9 = 3240
    result = calculate_approved_amount(
        claimed_amount=4500,
        claim_category="CONSULTATION",
        hospital_name="Apollo Hospitals",
        line_items=[],
    )
    # Wrong order would be: 4500 * 0.9 = 4050 * 0.8 = 3240 (same in this case)
    # But with different numbers it diverges, so test the intermediate deductions
    assert result["deductions"][0]["amount"] == 900  # 20% of 4500
    assert result["deductions"][1]["amount"] == 360  # 10% of 3600 (not 4500)

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_policy_data: Optional[dict] = None


def load_policy(path: Optional[str] = None) -> dict:
    global _policy_data
    if _policy_data is None:
        if path is None:
            path = str(Path(__file__).parent / "policy_terms.json")
        with open(path) as f:
            _policy_data = json.load(f)
    return _policy_data


def get_member(member_id: str) -> Optional[dict]:
    """Look up member — tries database first, falls back to policy JSON."""
    try:
        import database
        member = database.get_member(member_id)
        if member:
            return member
    except Exception:
        pass
    policy = load_policy()
    for member in policy["members"]:
        if member["member_id"] == member_id:
            return member
    return None


def get_document_requirements(claim_category: str) -> dict:
    policy = load_policy()
    return policy["document_requirements"].get(claim_category, {})


def get_category_config(claim_category: str) -> Optional[dict]:
    policy = load_policy()
    category_key = claim_category.lower()
    return policy["opd_categories"].get(category_key)


def get_network_hospitals() -> list[str]:
    policy = load_policy()
    return policy["network_hospitals"]


def is_network_hospital(hospital_name: str) -> bool:
    if not hospital_name:
        return False
    # Check DB first
    try:
        import database
        result = database.get_network_hospital(hospital_name)
        if result:
            return True
    except Exception:
        pass
    # Fallback to JSON
    hospitals = get_network_hospitals()
    hospital_lower = hospital_name.lower()
    return any(h.lower() in hospital_lower or hospital_lower in h.lower() for h in hospitals)


def get_coverage() -> dict:
    policy = load_policy()
    return policy["coverage"]


def get_waiting_periods() -> dict:
    policy = load_policy()
    return policy["waiting_periods"]


def get_exclusions() -> dict:
    policy = load_policy()
    return policy["exclusions"]


def get_fraud_thresholds() -> dict:
    policy = load_policy()
    return policy["fraud_thresholds"]


def get_pre_authorization_rules() -> dict:
    policy = load_policy()
    return policy["pre_authorization"]


def get_submission_rules() -> dict:
    policy = load_policy()
    return policy["submission_rules"]


def check_waiting_period(member: dict, treatment_date: str, diagnosis: str) -> dict:
    """Check if the treatment falls within any waiting period.
    Returns {passed: bool, reason: str, eligible_date: str|None}"""
    waiting = get_waiting_periods()
    join_date_str = member.get("join_date")
    if not join_date_str:
        return {"passed": True, "reason": "No join date — assuming eligible"}

    join_date = datetime.strptime(join_date_str, "%Y-%m-%d").date()
    treat_date = datetime.strptime(treatment_date, "%Y-%m-%d").date()
    days_since_join = (treat_date - join_date).days

    initial_wait = waiting.get("initial_waiting_period_days", 30)
    if days_since_join < initial_wait:
        from datetime import timedelta
        eligible = join_date + timedelta(days=initial_wait)
        return {
            "passed": False,
            "reason": f"Within initial waiting period ({days_since_join} days since joining, {initial_wait} required)",
            "eligible_date": eligible.isoformat(),
            "wait_type": "INITIAL_WAITING_PERIOD",
        }

    specific = waiting.get("specific_conditions", {})
    diagnosis_lower = diagnosis.lower() if diagnosis else ""

    # Try LLM-based matching first for accuracy, fall back to keyword matching
    llm_matched_conditions = _llm_match_waiting_conditions(diagnosis)

    for condition, wait_days in specific.items():
        matched = False
        if llm_matched_conditions is not None:
            matched = condition in llm_matched_conditions
        else:
            matched = _condition_matches(condition, diagnosis_lower)

        if matched and days_since_join < wait_days:
            from datetime import timedelta
            eligible = join_date + timedelta(days=wait_days)
            return {
                "passed": False,
                "reason": f"Within {condition.replace('_', ' ')} waiting period ({days_since_join} days since joining, {wait_days} required)",
                "eligible_date": eligible.isoformat(),
                "wait_type": "WAITING_PERIOD",
            }

    return {"passed": True, "reason": "All waiting periods cleared"}


def _llm_match_waiting_conditions(diagnosis: str) -> list[str] | None:
    """Use LLM to match diagnosis to waiting period conditions. Returns None if LLM unavailable."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None
        result = llm_service.match_diagnosis_to_conditions(diagnosis)
        if result and "matched_waiting_period_conditions" in result:
            return result["matched_waiting_period_conditions"]
    except Exception:
        pass
    return None


def _condition_matches(condition_key: str, diagnosis: str) -> bool:
    condition_map = {
        "diabetes": ["diabetes", "t2dm", "type 2 diabetes", "diabetic", "metformin", "glimepiride"],
        "hypertension": ["hypertension", "htn", "high blood pressure"],
        "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid"],
        "joint_replacement": ["joint replacement", "knee replacement", "hip replacement"],
        "maternity": ["maternity", "pregnancy", "prenatal"],
        "mental_health": ["mental health", "depression", "anxiety", "psychiatric"],
        "obesity_treatment": ["obesity", "bariatric", "weight loss", "bmi"],
        "hernia": ["hernia repair", "inguinal hernia", "umbilical hernia", "hiatal hernia"],
        "cataract": ["cataract"],
    }
    keywords = condition_map.get(condition_key, [condition_key.replace("_", " ")])
    return any(kw in diagnosis for kw in keywords)


def check_exclusions(diagnosis: str, treatment: str, claim_category: str, line_items: list[dict]) -> dict:
    """Check if the condition or treatment is excluded.
    Returns {excluded: bool, excluded_items: list, covered_items: list, reason: str}"""
    exclusions = get_exclusions()
    category_config = get_category_config(claim_category)

    combined_text = f"{diagnosis} {treatment}".lower() if treatment else diagnosis.lower() if diagnosis else ""

    # Try LLM-based exclusion matching first
    llm_exclusion = _llm_check_exclusion(diagnosis, treatment)
    if llm_exclusion is not None and llm_exclusion.get("is_excluded"):
        matched = llm_exclusion.get("matched_exclusions", [])
        reason = matched[0] if matched else "Treatment excluded under policy"
        return {
            "excluded": True,
            "fully_excluded": True,
            "excluded_items": [],
            "covered_items": [],
            "reason": f"Treatment excluded under policy: {reason}",
            "exclusion_type": "EXCLUDED_CONDITION",
        }

    # Fall back to keyword-based matching
    for excl in exclusions.get("conditions", []):
        excl_lower = excl.lower()
        keywords = excl_lower.split(" ")
        if any(kw in combined_text for kw in keywords if len(kw) > 3):
            if _is_strong_exclusion_match(excl_lower, combined_text):
                return {
                    "excluded": True,
                    "fully_excluded": True,
                    "excluded_items": [],
                    "covered_items": [],
                    "reason": f"Treatment excluded under policy: {excl}",
                    "exclusion_type": "EXCLUDED_CONDITION",
                }

    if claim_category == "DENTAL" and category_config:
        excluded_procs = [p.lower() for p in category_config.get("excluded_procedures", [])]
        covered_procs = [p.lower() for p in category_config.get("covered_procedures", [])]
        excluded_items = []
        covered_items = []

        for item in line_items:
            desc = item.get("description", "").lower()
            if any(ep in desc or desc in ep for ep in excluded_procs):
                excluded_items.append(item)
            elif any(cp in desc or desc in cp for cp in covered_procs):
                covered_items.append(item)
            else:
                covered_items.append(item)

        if excluded_items and covered_items:
            return {
                "excluded": True,
                "fully_excluded": False,
                "excluded_items": excluded_items,
                "covered_items": covered_items,
                "reason": "Some procedures are excluded under dental policy",
                "exclusion_type": "PARTIAL_EXCLUSION",
            }
        elif excluded_items and not covered_items:
            return {
                "excluded": True,
                "fully_excluded": True,
                "excluded_items": excluded_items,
                "covered_items": [],
                "reason": "All procedures excluded under dental policy",
                "exclusion_type": "EXCLUDED_CONDITION",
            }

    if claim_category == "VISION" and category_config:
        excluded_items_list = [i.lower() for i in category_config.get("excluded_items", [])]
        if any(ei in combined_text for ei in excluded_items_list):
            return {
                "excluded": True,
                "fully_excluded": True,
                "excluded_items": [],
                "covered_items": [],
                "reason": "Vision treatment excluded under policy",
                "exclusion_type": "EXCLUDED_CONDITION",
            }

    return {"excluded": False, "fully_excluded": False, "excluded_items": [], "covered_items": line_items, "reason": "No exclusions apply"}


def _llm_check_exclusion(diagnosis: str, treatment: str) -> dict | None:
    """Use LLM to check if diagnosis/treatment is excluded. Returns None if LLM unavailable."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None
        result = llm_service.match_diagnosis_to_conditions(diagnosis, treatment or "")
        if result:
            return result
    except Exception:
        pass
    return None


def _is_strong_exclusion_match(exclusion: str, text: str) -> bool:
    strong_matches = {
        "obesity and weight loss programs": ["obesity", "weight loss", "bmi 3", "bmi 4", "bariatric"],
        "bariatric surgery": ["bariatric"],
        "cosmetic or aesthetic procedures": ["cosmetic", "aesthetic", "whitening", "bleaching"],
        "substance abuse treatment": ["substance abuse", "addiction"],
        "self-inflicted injuries": ["self-inflicted", "self inflicted"],
        "experimental treatments": ["experimental"],
        "infertility and assisted reproduction": ["infertility", "ivf", "assisted reproduction"],
        "health supplements and tonics": ["supplement", "tonic"],
    }
    keywords = strong_matches.get(exclusion, [])
    if keywords:
        return any(kw in text for kw in keywords)
    return exclusion in text


def check_pre_authorization(claim_category: str, line_items: list[dict], claimed_amount: float) -> dict:
    """Check if pre-authorization is required.
    Returns {required: bool, reason: str}"""
    if claim_category != "DIAGNOSTIC":
        return {"required": False, "reason": "Pre-auth not required for this category"}

    category_config = get_category_config(claim_category)
    if not category_config:
        return {"required": False, "reason": "Category config not found"}

    threshold = category_config.get("pre_auth_threshold", float("inf"))
    high_value_tests = [t.lower() for t in category_config.get("high_value_tests_requiring_pre_auth", [])]

    for item in line_items:
        desc = item.get("description", "").lower()
        amount = item.get("amount", 0)
        if any(test in desc for test in high_value_tests) and amount > threshold:
            return {
                "required": True,
                "reason": f"Pre-authorization required for {item['description']} (amount ₹{amount:,.0f} exceeds ₹{threshold:,.0f} threshold)",
            }

    if claimed_amount > threshold:
        for item in line_items:
            desc = item.get("description", "").lower()
            if any(test in desc for test in high_value_tests):
                return {
                    "required": True,
                    "reason": f"Pre-authorization required for {item['description']} (claim amount ₹{claimed_amount:,.0f} exceeds ₹{threshold:,.0f} threshold)",
                }

    return {"required": False, "reason": "No pre-authorization required"}


def calculate_approved_amount(
    claimed_amount: float,
    claim_category: str,
    hospital_name: Optional[str],
    line_items: list[dict],
    covered_items: Optional[list[dict]] = None,
) -> dict:
    """Calculate the approved amount applying network discount and co-pay.
    Returns {approved_amount, deductions: list, breakdown: str}"""
    category_config = get_category_config(claim_category)
    coverage = get_coverage()

    effective_amount = claimed_amount
    if covered_items is not None:
        effective_amount = sum(item.get("amount", 0) for item in covered_items)

    deductions = []
    breakdown_steps = [f"Base amount: ₹{effective_amount:,.0f}"]

    per_claim_limit = coverage.get("per_claim_limit", float("inf"))
    sub_limit = category_config.get("sub_limit", float("inf")) if category_config else float("inf")

    network_discount_pct = category_config.get("network_discount_percent", 0) if category_config else 0
    if network_discount_pct > 0 and is_network_hospital(hospital_name or ""):
        discount = effective_amount * (network_discount_pct / 100)
        effective_amount -= discount
        deductions.append({
            "type": "network_discount",
            "amount": discount,
            "detail": f"{network_discount_pct}% network hospital discount applied (₹{discount:,.0f})",
        })
        breakdown_steps.append(f"After {network_discount_pct}% network discount: ₹{effective_amount:,.0f}")

    copay_pct = category_config.get("copay_percent", 0) if category_config else 0
    if copay_pct > 0:
        copay = effective_amount * (copay_pct / 100)
        effective_amount -= copay
        deductions.append({
            "type": "copay",
            "amount": copay,
            "detail": f"{copay_pct}% co-pay deducted (₹{copay:,.0f})",
        })
        breakdown_steps.append(f"After {copay_pct}% co-pay: ₹{effective_amount:,.0f}")

    approved_amount = effective_amount
    breakdown_steps.append(f"Approved amount: ₹{approved_amount:,.0f}")

    return {
        "approved_amount": approved_amount,
        "deductions": deductions,
        "breakdown": " → ".join(breakdown_steps),
    }

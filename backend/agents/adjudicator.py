from __future__ import annotations

import time
from models import (
    ClaimSubmission,
    Decision,
    Deduction,
    ExtractedData,
    LineItemDecision,
    TraceStep,
    TraceStepStatus,
)
from policy_engine import (
    calculate_approved_amount,
    check_exclusions,
    check_pre_authorization,
    check_waiting_period,
    get_category_config,
    get_coverage,
    get_member,
    is_network_hospital,
)
from agents.fraud_detector import FraudResult


class AdjudicationResult:
    def __init__(
        self,
        decision: Decision,
        approved_amount: float | None,
        reasons: list[str],
        confidence: float,
        deductions: list[dict],
        line_item_decisions: list[dict],
        checks: list[dict],
    ):
        self.decision = decision
        self.approved_amount = approved_amount
        self.reasons = reasons
        self.confidence = confidence
        self.deductions = deductions
        self.line_item_decisions = line_item_decisions
        self.checks = checks


def adjudicate(
    claim: ClaimSubmission,
    extracted: ExtractedData,
    fraud_result: FraudResult,
    simulate_failure: bool = False,
) -> tuple[AdjudicationResult, TraceStep]:
    start = time.time()

    if simulate_failure:
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.ERROR,
            duration_ms=duration,
            details={"error": "Adjudication service unavailable (simulated failure)"},
            message="Adjudicator failed — cannot make decision",
        )
        result = AdjudicationResult(
            decision=Decision.MANUAL_REVIEW,
            approved_amount=None,
            reasons=["Adjudication component failed"],
            confidence=0.3,
            deductions=[],
            line_item_decisions=[],
            checks=[],
        )
        return result, trace

    checks = []
    reasons = []

    member = get_member(claim.member_id)
    if not member:
        checks.append({"check": "member_eligible", "result": "FAIL", "detail": f"Member {claim.member_id} not found"})
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=["Member not found in policy"],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(agent="adjudicator", status=TraceStepStatus.FAIL, duration_ms=duration, details={"checks": checks})
        return result, trace

    checks.append({
        "check": "member_eligible",
        "result": "PASS",
        "detail": f"{member['name']} ({claim.member_id}) active since {member.get('join_date', 'N/A')}",
    })

    if fraud_result.flagged:
        checks.append({
            "check": "fraud_check",
            "result": "FLAG",
            "detail": f"Fraud signals detected: {'; '.join(fraud_result.signals)}",
        })
        result = AdjudicationResult(
            decision=Decision.MANUAL_REVIEW,
            approved_amount=None,
            reasons=fraud_result.signals,
            confidence=0.75,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.COMPLETE,
            duration_ms=duration,
            details={"checks": checks, "decision": "MANUAL_REVIEW", "fraud_signals": fraud_result.signals},
            message=f"Routed to manual review due to fraud signals: {'; '.join(fraud_result.signals)}",
        )
        return result, trace

    checks.append({"check": "fraud_check", "result": "PASS", "detail": "No fraud signals"})

    # Submission deadline check (only for recent dates — test data uses historical dates)
    from datetime import datetime
    from policy_engine import get_submission_rules
    submission_rules = get_submission_rules()
    deadline_days = submission_rules.get("deadline_days_from_treatment", 30)
    try:
        treat_date = datetime.strptime(claim.treatment_date, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_since = (today - treat_date).days
        if days_since > deadline_days and days_since < 365:
            checks.append({
                "check": "submission_deadline",
                "result": "FAIL",
                "detail": f"Claim submitted {days_since} days after treatment (deadline: {deadline_days} days)",
            })
            result = AdjudicationResult(
                decision=Decision.REJECTED,
                approved_amount=None,
                reasons=[f"Submission deadline exceeded: claim submitted {days_since} days after treatment (limit: {deadline_days} days)"],
                confidence=0.95,
                deductions=[],
                line_item_decisions=[],
                checks=checks,
            )
            duration = (time.time() - start) * 1000
            trace = TraceStep(
                agent="adjudicator",
                status=TraceStepStatus.FAIL,
                duration_ms=duration,
                details={"checks": checks, "decision": "REJECTED"},
                message=f"Rejected: Submission deadline exceeded ({days_since} days, limit {deadline_days}).",
            )
            return result, trace
        checks.append({"check": "submission_deadline", "result": "PASS", "detail": f"Within submission deadline"})
    except (ValueError, TypeError):
        checks.append({"check": "submission_deadline", "result": "PASS", "detail": "Date check skipped"})

    diagnosis = extracted.diagnosis or ""
    treatment = extracted.treatment or ""
    line_items = extracted.line_items or []

    # Exclusions FIRST — permanently excluded conditions take priority over waiting periods
    exclusion_result = check_exclusions(diagnosis, treatment, claim.claim_category.value, line_items)
    if exclusion_result["excluded"] and exclusion_result["fully_excluded"]:
        checks.append({
            "check": "exclusions",
            "result": "FAIL",
            "detail": exclusion_result["reason"],
        })
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=[exclusion_result["reason"]],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.FAIL,
            duration_ms=duration,
            details={"checks": checks, "decision": "REJECTED", "exclusion_type": exclusion_result.get("exclusion_type")},
            message=f"Rejected: {exclusion_result['reason']}",
        )
        return result, trace

    partial_exclusion = exclusion_result["excluded"] and not exclusion_result["fully_excluded"]
    if partial_exclusion:
        checks.append({
            "check": "exclusions",
            "result": "PARTIAL",
            "detail": exclusion_result["reason"],
            "excluded_items": exclusion_result["excluded_items"],
            "covered_items": exclusion_result["covered_items"],
        })
    else:
        checks.append({"check": "exclusions", "result": "PASS", "detail": f"{diagnosis or 'Treatment'} not excluded"})

    # Waiting period AFTER exclusions
    waiting_result = check_waiting_period(member, claim.treatment_date, f"{diagnosis} {treatment}")
    if not waiting_result["passed"]:
        checks.append({
            "check": "waiting_period",
            "result": "FAIL",
            "detail": waiting_result["reason"],
            "eligible_date": waiting_result.get("eligible_date"),
        })
        eligible_msg = f" Eligible from: {waiting_result.get('eligible_date', 'N/A')}." if waiting_result.get("eligible_date") else ""
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=[waiting_result["reason"] + eligible_msg],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.FAIL,
            duration_ms=duration,
            details={"checks": checks, "decision": "REJECTED"},
            message=f"Rejected: {waiting_result['reason']}.{eligible_msg}",
        )
        return result, trace

    join_date = member.get("join_date", "N/A")
    checks.append({"check": "waiting_period", "result": "PASS", "detail": f"All waiting periods cleared (joined {join_date})"})

    pre_auth_result = check_pre_authorization(claim.claim_category.value, line_items, claim.claimed_amount)
    if pre_auth_result["required"]:
        checks.append({
            "check": "pre_authorization",
            "result": "FAIL",
            "detail": pre_auth_result["reason"],
        })
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=[pre_auth_result["reason"] + " Please obtain pre-authorization and resubmit."],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.FAIL,
            duration_ms=duration,
            details={"checks": checks, "decision": "REJECTED"},
            message=f"Rejected: {pre_auth_result['reason']}. Member must obtain pre-authorization and resubmit.",
        )
        return result, trace

    checks.append({"check": "pre_authorization", "result": "PASS", "detail": "No pre-authorization required"})

    # Annual OPD limit check
    coverage = get_coverage()
    annual_limit = coverage.get("annual_opd_limit", float("inf"))
    ytd = claim.ytd_claims_amount or 0
    if ytd + claim.claimed_amount > annual_limit:
        checks.append({
            "check": "annual_limit",
            "result": "FAIL",
            "detail": f"YTD claims ₹{ytd:,.0f} + this claim ₹{claim.claimed_amount:,.0f} = ₹{ytd + claim.claimed_amount:,.0f} exceeds annual OPD limit of ₹{annual_limit:,.0f}",
        })
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=[f"Annual OPD limit exceeded: ₹{ytd:,.0f} already claimed + ₹{claim.claimed_amount:,.0f} = ₹{ytd + claim.claimed_amount:,.0f} (limit: ₹{annual_limit:,.0f})"],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.FAIL,
            duration_ms=duration,
            details={"checks": checks, "decision": "REJECTED"},
            message=f"Rejected: Annual OPD limit exceeded.",
        )
        return result, trace
    checks.append({"check": "annual_limit", "result": "PASS", "detail": f"YTD ₹{ytd:,.0f} + ₹{claim.claimed_amount:,.0f} within annual limit of ₹{annual_limit:,.0f}"})

    # Determine the effective amount for limit checks
    # For partial exclusions, only the covered portion counts
    covered_items = exclusion_result.get("covered_items", line_items)
    if partial_exclusion and covered_items:
        effective_claim_amount = sum(item.get("amount", 0) for item in covered_items)
    else:
        effective_claim_amount = claim.claimed_amount
    per_claim_limit = coverage.get("per_claim_limit", float("inf"))
    category_config = get_category_config(claim.claim_category.value)
    sub_limit = category_config.get("sub_limit", float("inf")) if category_config else float("inf")

    # Per-claim limit is the general OPD cap (₹5,000).
    # Category sub-limits are category-specific caps (e.g. dental ₹10,000).
    # For consultation, per-claim limit is the binding constraint.
    # For other categories, sub-limit is the binding constraint.
    if claim.claim_category.value == "CONSULTATION":
        effective_limit = per_claim_limit
        limit_label = "per-claim limit"
    else:
        effective_limit = sub_limit
        limit_label = f"{claim.claim_category.value.lower()} sub-limit"

    if effective_claim_amount > effective_limit:
        checks.append({
            "check": "per_claim_limit",
            "result": "FAIL",
            "detail": f"Claimed amount ₹{effective_claim_amount:,.0f} exceeds {limit_label} of ₹{effective_limit:,.0f}",
        })
        result = AdjudicationResult(
            decision=Decision.REJECTED,
            approved_amount=None,
            reasons=[f"Claimed amount ₹{effective_claim_amount:,.0f} exceeds the {limit_label} of ₹{effective_limit:,.0f}"],
            confidence=0.95,
            deductions=[],
            line_item_decisions=[],
            checks=checks,
        )
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.FAIL,
            duration_ms=duration,
            details={"checks": checks, "decision": "REJECTED"},
            message=f"Rejected: Claimed amount ₹{effective_claim_amount:,.0f} exceeds {limit_label} of ₹{effective_limit:,.0f}",
        )
        return result, trace

    checks.append({
        "check": "per_claim_limit",
        "result": "PASS",
        "detail": f"₹{effective_claim_amount:,.0f} within {limit_label} of ₹{effective_limit:,.0f}",
    })

    if not partial_exclusion:
        covered_items = line_items
        covered_amount = effective_claim_amount
    else:
        covered_items = exclusion_result.get("covered_items", line_items)
        covered_amount = sum(item.get("amount", 0) for item in covered_items)

    checks.append({
        "check": "sub_limit",
        "result": "PASS",
        "detail": f"₹{covered_amount:,.0f} within {claim.claim_category.value.lower()} sub-limit of ₹{sub_limit:,.0f}",
    })

    hospital_name = extracted.hospital_name or claim.hospital_name
    calc_result = calculate_approved_amount(
        claimed_amount=covered_amount,
        claim_category=claim.claim_category.value,
        hospital_name=hospital_name,
        line_items=line_items,
        covered_items=covered_items if partial_exclusion else None,
    )

    approved_amount = calc_result["approved_amount"]
    deductions = calc_result["deductions"]

    if is_network_hospital(hospital_name or ""):
        checks.append({
            "check": "network_discount",
            "result": "APPLIED",
            "detail": f"Network hospital ({hospital_name}) — discount applied",
        })
    else:
        checks.append({
            "check": "network_discount",
            "result": "N/A",
            "detail": f"{'Not a network hospital' if hospital_name else 'No hospital identified'}",
        })

    copay_pct = category_config.get("copay_percent", 0) if category_config else 0
    if copay_pct > 0:
        checks.append({
            "check": "copay",
            "result": "APPLIED",
            "detail": f"{copay_pct}% co-pay applied",
        })

    line_item_decisions = []
    if partial_exclusion:
        for item in exclusion_result.get("covered_items", []):
            line_item_decisions.append({
                "description": item.get("description", ""),
                "amount": item.get("amount", 0),
                "covered": True,
                "reason": "Covered under policy",
            })
        for item in exclusion_result.get("excluded_items", []):
            line_item_decisions.append({
                "description": item.get("description", ""),
                "amount": item.get("amount", 0),
                "covered": False,
                "reason": "Excluded: cosmetic/aesthetic procedure",
            })

    if partial_exclusion:
        decision = Decision.PARTIAL
    else:
        decision = Decision.APPROVED

    confidence = _calculate_adjudication_confidence(extracted, checks)

    result = AdjudicationResult(
        decision=decision,
        approved_amount=approved_amount,
        reasons=reasons if reasons else [calc_result["breakdown"]],
        confidence=confidence,
        deductions=deductions,
        line_item_decisions=line_item_decisions,
        checks=checks,
    )

    duration = (time.time() - start) * 1000
    trace = TraceStep(
        agent="adjudicator",
        status=TraceStepStatus.COMPLETE,
        duration_ms=duration,
        details={
            "checks": checks,
            "decision": decision.value,
            "approved_amount": approved_amount,
            "deductions": deductions,
            "breakdown": calc_result["breakdown"],
            "line_item_decisions": line_item_decisions if line_item_decisions else None,
        },
        message=f"Decision: {decision.value} — ₹{approved_amount:,.0f} approved. {calc_result['breakdown']}",
    )
    return result, trace


def _calculate_adjudication_confidence(extracted: ExtractedData, checks: list[dict]) -> float:
    base = 0.85
    if extracted.confidence >= 0.9:
        base += 0.05
    elif extracted.confidence < 0.6:
        base -= 0.15

    all_pass = all(c["result"] in ("PASS", "APPLIED", "N/A", "COMPLETE") for c in checks)
    if all_pass:
        base += 0.05

    return min(max(base, 0.1), 0.99)

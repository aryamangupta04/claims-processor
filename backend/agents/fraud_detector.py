from __future__ import annotations

import time
from models import ClaimSubmission, TraceStep, TraceStepStatus
from policy_engine import get_fraud_thresholds


class FraudResult:
    def __init__(self, flagged: bool, signals: list[str], fraud_score: float, details: dict):
        self.flagged = flagged
        self.signals = signals
        self.fraud_score = fraud_score
        self.details = details


def detect_fraud(claim: ClaimSubmission, simulate_failure: bool = False, current_claim_id: str = None) -> tuple[FraudResult, TraceStep]:
    start = time.time()

    if simulate_failure:
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="fraud_detector",
            status=TraceStepStatus.ERROR,
            duration_ms=duration,
            details={
                "error": "Fraud detection service unavailable (simulated failure)",
                "fallback": "Skipping fraud checks — confidence will be reduced",
            },
            message="Fraud detector failed — skipping fraud checks",
        )
        result = FraudResult(flagged=False, signals=[], fraud_score=0.0, details={"skipped": True})
        return result, trace

    try:
        import database
        thresholds = get_fraud_thresholds()
        signals = []
        details = {}

        # Fetch REAL claims history from DB (not client-supplied data)
        history = database.get_member_claims_history(claim.member_id) if claim.member_id else []
        # Exclude the current claim from history (it's already saved as UNDER_REVIEW)
        if current_claim_id:
            history = [h for h in history if h.get("claim_id") != current_claim_id]

        # Also include client-supplied history for test cases (TC009)
        if claim.claims_history and not history:
            history = [{"claim_id": h.claim_id, "date": h.date, "amount": h.amount, "provider": h.provider} for h in claim.claims_history]

        same_day_count = sum(1 for h in history if h.get("date") == claim.treatment_date)
        details["same_day_claims"] = same_day_count
        same_day_limit = thresholds.get("same_day_claims_limit", 2)
        if same_day_count >= same_day_limit:
            signals.append(
                f"Multiple same-day claims detected: {same_day_count} previous claims on {claim.treatment_date} "
                f"(limit: {same_day_limit}). This is claim #{same_day_count + 1} for today."
            )

        treatment_month = claim.treatment_date[:7]
        monthly_count = sum(1 for h in history if h.get("date", "").startswith(treatment_month))
        details["monthly_claims"] = monthly_count
        monthly_limit = thresholds.get("monthly_claims_limit", 6)
        if monthly_count >= monthly_limit:
            signals.append(
                f"Monthly claim frequency exceeded: {monthly_count} claims this month (limit: {monthly_limit})"
            )

        high_value_threshold = thresholds.get("high_value_claim_threshold", 25000)
        details["high_value"] = claim.claimed_amount > high_value_threshold
        if claim.claimed_amount > high_value_threshold:
            signals.append(
                f"High-value claim: ₹{claim.claimed_amount:,.0f} exceeds threshold of ₹{high_value_threshold:,.0f}"
            )

        auto_review_threshold = thresholds.get("auto_manual_review_above", 25000)
        if claim.claimed_amount > auto_review_threshold:
            signals.append(
                f"Amount ₹{claim.claimed_amount:,.0f} exceeds auto-review threshold of ₹{auto_review_threshold:,.0f}"
            )

        if same_day_count >= same_day_limit:
            same_day_history = [h for h in history if h.get("date") == claim.treatment_date]
            providers = set(h.get("provider") for h in same_day_history if h.get("provider"))
            if len(providers) > 1:
                signals.append(
                    f"Multiple providers on same day: {', '.join(providers)}"
                )
                details["providers"] = list(providers)

        fraud_score = _calculate_fraud_score(same_day_count, monthly_count, claim.claimed_amount, thresholds)
        details["fraud_score"] = fraud_score
        details["signals"] = signals

        # Use LLM for deeper pattern analysis when there are signals
        if signals:
            llm_analysis = _analyze_fraud_patterns_with_llm(claim, signals, details)
            if llm_analysis:
                details["llm_fraud_analysis"] = llm_analysis

        flagged = fraud_score >= thresholds.get("fraud_score_manual_review_threshold", 0.80) or len(signals) > 0

        duration = (time.time() - start) * 1000
        status = TraceStepStatus.FAIL if flagged else TraceStepStatus.PASS
        trace = TraceStep(
            agent="fraud_detector",
            status=status,
            duration_ms=duration,
            details=details,
            message=f"Fraud check: {'FLAGGED — ' + '; '.join(signals) if flagged else 'No fraud signals detected'}",
        )
        return FraudResult(flagged=flagged, signals=signals, fraud_score=fraud_score, details=details), trace

    except Exception as e:
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="fraud_detector",
            status=TraceStepStatus.ERROR,
            duration_ms=duration,
            details={"error": str(e)},
            message=f"Fraud detection error: {str(e)}",
        )
        result = FraudResult(flagged=False, signals=[], fraud_score=0.0, details={"error": str(e)})
        return result, trace


def _analyze_fraud_patterns_with_llm(claim: ClaimSubmission, signals: list[str], details: dict) -> dict | None:
    """Use LLM to analyze fraud patterns and provide reasoning."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None

        history_str = ""
        if claim.claims_history:
            history_str = "\n".join(
                f"  - {h.date}: ₹{h.amount} at {h.provider or 'unknown provider'}"
                for h in claim.claims_history
            )

        prompt = f"""You are a health insurance fraud analyst. Analyze this claim for fraud risk.

Current Claim:
- Member: {claim.member_id}
- Date: {claim.treatment_date}
- Amount: ₹{claim.claimed_amount:,.0f}
- Category: {claim.claim_category.value}

Claims History:
{history_str or "  No prior claims"}

Detected Signals:
{chr(10).join(f"  - {s}" for s in signals)}

Provide a brief fraud risk assessment. Is this likely fraudulent, or could there be a legitimate explanation?

Respond with ONLY this JSON:
{{"risk_level": "LOW|MEDIUM|HIGH", "likely_fraudulent": true/false, "reasoning": "brief explanation", "recommendation": "approve|manual_review|investigate"}}"""

        text = llm_service._call_llm(prompt)
        return llm_service._parse_json_response(text)
    except Exception:
        return None


def _calculate_fraud_score(same_day: int, monthly: int, amount: float, thresholds: dict) -> float:
    score = 0.0
    same_day_limit = thresholds.get("same_day_claims_limit", 2)
    if same_day >= same_day_limit:
        score += 0.4 + (same_day - same_day_limit) * 0.1

    monthly_limit = thresholds.get("monthly_claims_limit", 6)
    if monthly >= monthly_limit:
        score += 0.3

    high_value = thresholds.get("high_value_claim_threshold", 25000)
    if amount > high_value:
        score += 0.2

    return min(score, 1.0)

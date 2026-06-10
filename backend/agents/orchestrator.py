from __future__ import annotations

import time
import uuid
from models import (
    ClaimDecision,
    ClaimSubmission,
    Decision,
    Deduction,
    LineItemDecision,
    TraceStep,
    TraceStepStatus,
)
from agents.document_validator import validate_documents
from agents.extraction import extract_data
from agents.fraud_detector import detect_fraud, FraudResult
from agents.adjudicator import adjudicate
from policy_engine import get_document_requirements


def process_claim(claim: ClaimSubmission) -> ClaimDecision:
    """Main pipeline orchestrator. Runs all agents in sequence, handles failures gracefully."""
    claim_id = f"CLM_{uuid.uuid4().hex[:8].upper()}"
    trace: list[TraceStep] = []
    confidence_penalty = 0.0
    component_failures = []

    # Stage 0: Verify member identity
    import database
    if claim.member_id:
        member = database.get_member(claim.member_id)
        if not member:
            trace.append(TraceStep(
                agent="member_lookup",
                status=TraceStepStatus.STOP,
                duration_ms=0,
                details={"member_id": claim.member_id},
                message=f"Employee ID '{claim.member_id}' not found in our system.",
            ))
            return ClaimDecision(
                claim_id=claim_id,
                status=Decision.REJECTED,
                claimed_amount=claim.claimed_amount,
                confidence=0.99,
                summary=f"Employee ID '{claim.member_id}' not found in our system.",
                error_message="Please check your Employee ID and try again.",
                trace=trace,
            )
        # If both name and ID provided, verify they match
        if claim.member_name and member["name"].lower() != claim.member_name.strip().lower():
            trace.append(TraceStep(
                agent="member_lookup",
                status=TraceStepStatus.STOP,
                duration_ms=0,
                details={"member_id": claim.member_id, "name_provided": claim.member_name, "name_on_record": member["name"]},
                message=f"Name mismatch: you entered '{claim.member_name}' but ID '{claim.member_id}' belongs to '{member['name']}'.",
            ))
            return ClaimDecision(
                claim_id=claim_id,
                status=Decision.REJECTED,
                claimed_amount=claim.claimed_amount,
                confidence=0.99,
                summary=f"Identity mismatch: name '{claim.member_name}' does not match Employee ID '{claim.member_id}' (registered to '{member['name']}').",
                error_message="The name and Employee ID don't match. Please verify your details.",
                trace=trace,
            )
    elif claim.member_name:
        member = database.get_member_by_name(claim.member_name)
        if member:
            claim.member_id = member["member_id"]
        else:
            trace.append(TraceStep(
                agent="member_lookup",
                status=TraceStepStatus.STOP,
                duration_ms=0,
                details={"name_searched": claim.member_name},
                message=f"Member '{claim.member_name}' not found in our system.",
            ))
            return ClaimDecision(
                claim_id=claim_id,
                status=Decision.REJECTED,
                claimed_amount=claim.claimed_amount,
                confidence=0.99,
                summary=f"Member '{claim.member_name}' not found in our system.",
                error_message="No member found with that name. Please ensure the name matches your policy records.",
                trace=trace,
            )
    else:
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.REJECTED,
            claimed_amount=claim.claimed_amount,
            confidence=0.99,
            summary="No member information provided.",
            error_message="Please provide your full name and Employee ID.",
            trace=trace,
        )


    # Stage 1: Document Validation
    validation_result, validation_trace = validate_documents(claim)
    trace.append(validation_trace)

    if not validation_result.passed:
        action = validation_result.details.get("action_required") or "Please re-upload the correct documents and try again."
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.ACTION_REQUIRED,
            claimed_amount=claim.claimed_amount,
            confidence=0.95,
            summary=validation_result.message,
            error_message=action,
            trace=trace,
            requires_action=action,
        )

    # If vision was unavailable (rate limited), route to manual review — not the user's fault
    if validation_result.details.get("vision_unavailable"):
        trace.append(TraceStep(
            agent="document_validator",
            status=TraceStepStatus.PASS,
            duration_ms=0,
            details={"note": "Vision verification unavailable — documents accepted pending manual review"},
            message="Documents accepted but could not be verified automatically. Routing to manual review.",
        ))
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.MANUAL_REVIEW,
            claimed_amount=claim.claimed_amount,
            confidence=0.5,
            summary="Your claim has been received. Our document verification system is temporarily busy, so your claim will be reviewed manually. No action needed from you.",
            trace=trace,
        )

    # Stage 2: Data Extraction
    simulate_extraction_failure = claim.simulate_component_failure or False
    extraction_failed = False
    try:
        extracted, extraction_trace = extract_data(claim, simulate_failure=simulate_extraction_failure)
        trace.append(extraction_trace)
        if extraction_trace.status == TraceStepStatus.ERROR:
            extraction_failed = True
            confidence_penalty += 0.25
            component_failures.append("extraction")
    except Exception as e:
        extraction_failed = True
        confidence_penalty += 0.25
        component_failures.append("extraction")
        trace.append(TraceStep(
            agent="extraction",
            status=TraceStepStatus.ERROR,
            details={"error": str(e)},
            message=f"Extraction agent crashed: {str(e)} — routing to manual review",
        ))
        from models import ExtractedData
        extracted = ExtractedData(
            total_amount=claim.claimed_amount,
            hospital_name=claim.hospital_name,
            confidence=0.3,
        )

    # Stage 2.5: If extraction failed or produced nothing usable, don't auto-approve
    if extraction_failed or (extracted.confidence <= 0.2 and not extracted.patient_name and not extracted.diagnosis):
        trace.append(TraceStep(
            agent="extraction_gate",
            status=TraceStepStatus.STOP,
            duration_ms=0,
            details={
                "confidence": extracted.confidence,
                "reason": "Insufficient data extracted from documents",
            },
            message="Cannot process claim — documents could not be read or contain no usable information. Routing to manual review.",
        ))
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.MANUAL_REVIEW,
            claimed_amount=claim.claimed_amount,
            confidence=0.2,
            summary="Claim routed to manual review — the uploaded documents could not be read or did not contain sufficient information (patient name, diagnosis, amounts). Please re-upload clearer documents or contact support.",
            trace=trace,
        )

    # Stage 2.6: Hospital name mismatch check
    if claim.hospital_name and claim.hospital_name != "Other" and extracted.hospital_name:
        claimed_hospital = claim.hospital_name.lower().strip()
        doc_hospital = extracted.hospital_name.lower().strip()
        if claimed_hospital not in doc_hospital and doc_hospital not in claimed_hospital:
            trace.append(TraceStep(
                agent="hospital_verifier",
                status=TraceStepStatus.FAIL,
                duration_ms=0,
                details={
                    "selected_hospital": claim.hospital_name,
                    "hospital_on_document": extracted.hospital_name,
                },
                message=f"Hospital mismatch: you selected '{claim.hospital_name}' but the document shows '{extracted.hospital_name}'.",
            ))
            return ClaimDecision(
                claim_id=claim_id,
                status=Decision.ACTION_REQUIRED,
                claimed_amount=claim.claimed_amount,
                confidence=0.90,
                summary=f"Hospital mismatch: you selected '{claim.hospital_name}' but your bill/prescription shows '{extracted.hospital_name}'.",
                error_message=f"Please select the correct hospital from the dropdown, or choose 'Other' if '{extracted.hospital_name}' is not listed.",
                trace=trace,
            )

    # Stage 2.7: Date mismatch check — does the date ON the document match the claimed date?
    if extracted.treatment_date and claim.treatment_date:
        doc_date = extracted.treatment_date.strip()
        claimed_date = claim.treatment_date.strip()
        if doc_date and claimed_date and doc_date != claimed_date:
            trace.append(TraceStep(
                agent="date_verifier",
                status=TraceStepStatus.FAIL,
                duration_ms=0,
                details={
                    "date_on_document": doc_date,
                    "claimed_treatment_date": claimed_date,
                },
                message=f"Date mismatch: document shows {doc_date} but claim states {claimed_date}.",
            ))
            return ClaimDecision(
                claim_id=claim_id,
                status=Decision.MANUAL_REVIEW,
                claimed_amount=claim.claimed_amount,
                confidence=0.85,
                summary=f"Date discrepancy detected: the document shows a date of {doc_date}, but the claimed treatment date is {claimed_date}.",
                error_message="The date on your document doesn't match the treatment date you entered. Please verify and correct the treatment date, or upload the correct document.",
                trace=trace,
            )

    # Stage 2.7: Check for duplicate claims based on extracted details
    doc_dicts = [d.model_dump() for d in claim.documents]
    extracted_dict = extracted.model_dump()
    extracted_dict["treatment_date"] = claim.treatment_date
    duplicates = database.check_duplicate_claim(claim.member_id, extracted_dict, doc_dicts)
    if duplicates:
        dup_details = [d["detail"] for d in duplicates]
        trace.append(TraceStep(
            agent="duplicate_checker",
            status=TraceStepStatus.FAIL,
            duration_ms=0,
            details={"duplicates": duplicates},
            message=f"Potential duplicate claim: {'; '.join(dup_details)}",
        ))
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.REJECTED,
            claimed_amount=claim.claimed_amount,
            confidence=0.95,
            summary=f"Potential duplicate claim detected: {'; '.join(dup_details)}.",
            error_message="This appears to be a duplicate of a previously submitted claim. If this is a new visit, please ensure the documents are different from your previous submission.",
            trace=trace,
        )

    # Stage 3: Fraud Detection
    try:
        fraud_result, fraud_trace = detect_fraud(claim)
        trace.append(fraud_trace)
    except Exception as e:
        component_failures.append("fraud_detector")
        trace.append(TraceStep(
            agent="fraud_detector",
            status=TraceStepStatus.ERROR,
            details={"error": str(e)},
            message=f"Fraud detector crashed: {str(e)} — routing to manual review",
        ))
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.MANUAL_REVIEW,
            claimed_amount=claim.claimed_amount,
            confidence=0.3,
            summary="Claim routed to manual review — fraud detection system unavailable. Cannot verify claim safety.",
            trace=trace,
        )

    # Stage 4: Adjudication
    try:
        adj_result, adj_trace = adjudicate(claim, extracted, fraud_result)
        trace.append(adj_trace)
    except Exception as e:
        confidence_penalty += 0.3
        component_failures.append("adjudicator")
        trace.append(TraceStep(
            agent="adjudicator",
            status=TraceStepStatus.ERROR,
            details={"error": str(e)},
            message=f"Adjudicator crashed: {str(e)} — routing to manual review",
        ))
        adj_result = None

    # Assemble final decision
    if adj_result is None:
        final_confidence = max(0.3 - confidence_penalty, 0.1)
        summary = "Claim could not be fully processed due to component failures. Routed to manual review."
        if component_failures:
            summary += f" Failed components: {', '.join(component_failures)}."
        return ClaimDecision(
            claim_id=claim_id,
            status=Decision.MANUAL_REVIEW,
            claimed_amount=claim.claimed_amount,
            confidence=final_confidence,
            summary=summary,
            trace=trace,
        )

    final_confidence = adj_result.confidence - confidence_penalty
    final_confidence = max(final_confidence, 0.1)

    summary = _build_summary(adj_result, claim, component_failures)

    # Use LLM to generate a more natural summary
    llm_summary = _generate_llm_summary(adj_result, claim, component_failures)
    if llm_summary:
        summary = llm_summary

    deductions = [
        Deduction(type=d["type"], amount=d["amount"], detail=d["detail"])
        for d in adj_result.deductions
    ]

    line_item_decisions = [
        LineItemDecision(
            description=li["description"],
            amount=li["amount"],
            covered=li["covered"],
            reason=li.get("reason"),
        )
        for li in adj_result.line_item_decisions
    ]

    return ClaimDecision(
        claim_id=claim_id,
        status=adj_result.decision,
        approved_amount=adj_result.approved_amount,
        claimed_amount=claim.claimed_amount,
        confidence=final_confidence,
        summary=summary,
        rejection_reasons=adj_result.reasons if adj_result.decision == Decision.REJECTED else [],
        deductions=deductions,
        line_item_decisions=line_item_decisions,
        trace=trace,
    )


def _build_summary(adj_result, claim: ClaimSubmission, component_failures: list[str]) -> str:
    parts = []

    if adj_result.decision == Decision.APPROVED:
        parts.append(f"Claim approved for ₹{adj_result.approved_amount:,.0f} (claimed: ₹{claim.claimed_amount:,.0f}).")
        if adj_result.deductions:
            deduction_parts = [d["detail"] for d in adj_result.deductions]
            parts.append("Deductions: " + "; ".join(deduction_parts) + ".")
    elif adj_result.decision == Decision.PARTIAL:
        parts.append(f"Claim partially approved for ₹{adj_result.approved_amount:,.0f} (claimed: ₹{claim.claimed_amount:,.0f}).")
        parts.append("Some items were excluded — see line-item breakdown.")
    elif adj_result.decision == Decision.REJECTED:
        parts.append("Claim rejected.")
        if adj_result.reasons:
            parts.append("Reason: " + "; ".join(adj_result.reasons))
    elif adj_result.decision == Decision.MANUAL_REVIEW:
        parts.append("Claim routed to manual review.")
        if adj_result.reasons:
            parts.append("Reason: " + "; ".join(adj_result.reasons))

    if component_failures:
        parts.append(f"⚠ Note: Components [{', '.join(component_failures)}] experienced failures during processing. "
                     f"Confidence reduced. Manual review recommended.")

    return " ".join(parts)


def _friendly_type(doc_type: str) -> str:
    names = {
        "PRESCRIPTION": "a prescription",
        "HOSPITAL_BILL": "a hospital bill",
        "LAB_REPORT": "a lab report",
        "PHARMACY_BILL": "a pharmacy bill",
        "DIAGNOSTIC_REPORT": "a diagnostic report",
        "DISCHARGE_SUMMARY": "a discharge summary",
        "DENTAL_REPORT": "a dental report",
    }
    return names.get(doc_type, doc_type.lower().replace("_", " "))


def _generate_llm_summary(adj_result, claim: ClaimSubmission, component_failures: list[str]) -> str | None:
    """Use LLM to generate a clear, human-readable decision summary."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None

        checks_summary = []
        for check in adj_result.checks:
            checks_summary.append(f"{check['check']}: {check['result']} - {check['detail']}")

        prompt = f"""You are writing a clear, concise summary for a health insurance claim decision. This will be read by operations staff.

Decision: {adj_result.decision.value}
Claimed Amount: ₹{claim.claimed_amount:,.0f}
Approved Amount: {"₹" + f"{adj_result.approved_amount:,.0f}" if adj_result.approved_amount else "N/A"}
Member: {claim.member_id}
Category: {claim.claim_category.value}
Checks: {"; ".join(checks_summary)}
Deductions: {adj_result.deductions if adj_result.deductions else "None"}
Component Failures: {component_failures if component_failures else "None"}

Write a 1-2 sentence summary explaining the decision. Be specific about amounts and reasons. No jargon.
Respond with ONLY the summary text, nothing else."""

        result = llm_service._call_llm(prompt)
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception:
        pass
    return None

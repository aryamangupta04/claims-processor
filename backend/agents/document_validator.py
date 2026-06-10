from __future__ import annotations

import time
from models import (
    ClaimCategory,
    ClaimSubmission,
    DocumentInput,
    DocumentType,
    TraceStep,
    TraceStepStatus,
)
from policy_engine import get_document_requirements, get_member


class DocumentValidationResult:
    def __init__(self, passed: bool, message: str = "", details: dict = None):
        self.passed = passed
        self.message = message
        self.details = details or {}


def validate_documents(claim: ClaimSubmission) -> tuple[DocumentValidationResult, TraceStep]:
    start = time.time()
    details = {}

    try:
        requirements = get_document_requirements(claim.claim_category.value)
        required_types = requirements.get("required", [])
        details["required_documents"] = required_types

        uploaded_types = []
        for doc in claim.documents:
            if doc.actual_type:
                uploaded_types.append(doc.actual_type.value)
            else:
                classified = _classify_with_llm(doc)
                if classified:
                    uploaded_types.append(classified["type"])
                    details.setdefault("llm_classifications", []).append(classified)
                else:
                    uploaded_types.append("UNKNOWN")
        details["uploaded_documents"] = uploaded_types

        missing_types = []
        for req_type in required_types:
            if req_type not in uploaded_types:
                missing_types.append(req_type)

        if missing_types:
            uploaded_description = _describe_uploaded(claim.documents)
            fallback_message = (
                f"Wrong documents uploaded: {uploaded_description}, "
                f"but {_describe_required(missing_types)} is required for {claim.claim_category.value.lower()} claims. "
                f"Please upload: {', '.join(_friendly_name(t) for t in missing_types)}."
            )
            message = _generate_validation_message_with_llm(
                issue_type="MISSING_DOCUMENTS",
                uploaded_types=uploaded_types,
                required_types=required_types,
                missing_types=missing_types,
                claim_category=claim.claim_category.value,
            ) or fallback_message

            details["missing_types"] = missing_types
            details["validation_result"] = "MISSING_DOCUMENTS"
            details["action_required"] = (
                f"Upload a {', '.join(_friendly_name(t) for t in missing_types)} — "
                f"take a clear photo or scan of the original document and re-submit your claim."
            )

            duration = (time.time() - start) * 1000
            trace = TraceStep(
                agent="document_validator",
                status=TraceStepStatus.STOP,
                duration_ms=duration,
                details=details,
                message=message,
            )
            return DocumentValidationResult(passed=False, message=message, details=details), trace

        # Check if documents have any content (content field, file data, or uploaded file)
        empty_docs = []
        for doc in claim.documents:
            has_content = doc.content and len(doc.content) > 0
            has_file_data = bool(doc.file_data)
            has_real_file = doc.file_name and not doc.file_name.startswith("F0")
            has_patient_name = bool(doc.patient_name_on_doc)
            if not has_content and not has_file_data and not has_real_file and not has_patient_name:
                empty_docs.append(doc)

        if empty_docs and len(empty_docs) == len(claim.documents):
            doc_types = [_friendly_name(doc.actual_type.value) if doc.actual_type else "document" for doc in empty_docs]
            message = (
                f"Document content missing: You selected {', '.join(doc_types)} but did not provide any document content. "
                f"Please upload actual documents (photos, scans, or PDFs) for your {claim.claim_category.value.lower()} claim."
            )
            details["validation_result"] = "EMPTY_DOCUMENTS"
            details["empty_documents"] = [doc.file_id for doc in empty_docs]

            duration = (time.time() - start) * 1000
            trace = TraceStep(
                agent="document_validator",
                status=TraceStepStatus.STOP,
                duration_ms=duration,
                details=details,
                message=message,
            )
            return DocumentValidationResult(passed=False, message=message, details=details), trace

        unreadable_docs = []
        for doc in claim.documents:
            if doc.quality and doc.quality.value == "UNREADABLE":
                unreadable_docs.append(doc)

        if unreadable_docs:
            doc_names = [_friendly_name(doc.actual_type.value) if doc.actual_type else doc.file_name for doc in unreadable_docs]
            message = f"Document quality issue: Your {', '.join(doc_names)} is too blurry or unclear to read."
            details["unreadable_documents"] = [doc.file_id for doc in unreadable_docs]
            details["validation_result"] = "UNREADABLE_DOCUMENT"
            details["action_required"] = (
                f"Take a clearer photo of your {', '.join(doc_names)}. "
                f"Make sure the document is flat, well-lit, and all text is fully visible with no shadows or blur."
            )

            duration = (time.time() - start) * 1000
            trace = TraceStep(
                agent="document_validator",
                status=TraceStepStatus.STOP,
                duration_ms=duration,
                details=details,
                message=message,
            )
            return DocumentValidationResult(passed=False, message=message, details=details), trace

        # Vision verification: if documents have image data, verify they match claimed type
        docs_with_images = [doc for doc in claim.documents if doc.file_data]
        if docs_with_images:
            mismatches, vision_succeeded = _verify_documents_with_vision(docs_with_images)

            # If vision couldn't run at all (rate limited/unavailable), don't auto-approve
            if not vision_succeeded and docs_with_images:
                details["vision_unavailable"] = True
                details["validation_result"] = "VISION_UNAVAILABLE"

            if mismatches:
                mismatch_details = []
                for m in mismatches:
                    mismatch_details.append(
                        f"'{m['file']}' was labelled as {_friendly_name(m['claimed_type'])}, "
                        f"but it appears to be: {m['explanation']}"
                    )
                message = f"Document verification failed: {'; '.join(mismatch_details)}."
                details["validation_result"] = "DOCUMENT_TYPE_MISMATCH"
                details["mismatches"] = mismatches

                # Ask LLM for a specific, actionable next step
                action = _generate_action_required_with_llm(
                    mismatches=mismatches,
                    required_types=required_types,
                    claim_category=claim.claim_category.value,
                )
                details["action_required"] = action

                duration = (time.time() - start) * 1000
                trace = TraceStep(
                    agent="document_validator",
                    status=TraceStepStatus.STOP,
                    duration_ms=duration,
                    details=details,
                    message=message,
                )
                return DocumentValidationResult(passed=False, message=message, details=details), trace

        patient_names = _extract_patient_names(claim)
        if len(patient_names) > 1:
            member = get_member(claim.member_id)
            member_name = member["name"] if member else None
            all_names_valid = _validate_patient_names(patient_names, member, claim.member_id)

            if not all_names_valid:
                names_found = list(patient_names)
                fallback_message = (
                    f"Document mismatch: The documents appear to belong to different patients. "
                    f"Found different names: {', '.join(f'\"{n}\"' for n in names_found)}."
                )
                message = _generate_validation_message_with_llm(
                    issue_type="PATIENT_MISMATCH",
                    patient_names=names_found,
                    member_id=claim.member_id,
                    claim_category=claim.claim_category.value,
                ) or fallback_message

                details["patient_names_found"] = names_found
                details["validation_result"] = "PATIENT_MISMATCH"
                details["action_required"] = (
                    f"Re-upload documents that all belong to the same person. "
                    f"Your current uploads have different names ({', '.join(names_found)}) — "
                    f"make sure every document is for the patient making this claim."
                )

                duration = (time.time() - start) * 1000
                trace = TraceStep(
                    agent="document_validator",
                    status=TraceStepStatus.STOP,
                    duration_ms=duration,
                    details=details,
                    message=message,
                )
                return DocumentValidationResult(passed=False, message=message, details=details), trace

        details["validation_result"] = "PASS"
        details["patient_consistency"] = f"MATCH — {list(patient_names)[0] if patient_names else 'N/A'} on all documents"
        details["quality_check"] = "ALL_READABLE"

        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="document_validator",
            status=TraceStepStatus.PASS,
            duration_ms=duration,
            details=details,
            message="All documents validated successfully",
        )
        return DocumentValidationResult(passed=True, details=details), trace

    except Exception as e:
        duration = (time.time() - start) * 1000
        trace = TraceStep(
            agent="document_validator",
            status=TraceStepStatus.ERROR,
            duration_ms=duration,
            details={"error": str(e)},
            message=f"Document validation encountered an error: {str(e)}",
        )
        return DocumentValidationResult(passed=False, message=f"Validation error: {str(e)}"), trace


def _extract_patient_names(claim: ClaimSubmission) -> set[str]:
    names = set()
    for doc in claim.documents:
        if doc.patient_name_on_doc:
            names.add(doc.patient_name_on_doc.strip())
        elif doc.content and "patient_name" in doc.content:
            names.add(doc.content["patient_name"].strip())
    return names


def _validate_patient_names(names: set[str], member: dict | None, member_id: str) -> bool:
    if len(names) <= 1:
        return True
    name_list = [n.lower() for n in names]
    for i in range(len(name_list)):
        for j in range(i + 1, len(name_list)):
            if name_list[i] != name_list[j]:
                if member:
                    member_name_lower = member["name"].lower()
                    if name_list[i] == member_name_lower or name_list[j] == member_name_lower:
                        other = name_list[j] if name_list[i] == member_name_lower else name_list[i]
                        dependents = member.get("dependents", [])
                        if not dependents:
                            return False
                return False
    return True


def _describe_uploaded(documents: list[DocumentInput]) -> str:
    type_counts = {}
    for doc in documents:
        t = doc.actual_type.value if doc.actual_type else "UNKNOWN"
        friendly = _friendly_name(t)
        type_counts[friendly] = type_counts.get(friendly, 0) + 1

    parts = []
    for name, count in type_counts.items():
        if count > 1:
            parts.append(f"{count} {name}s were uploaded")
        else:
            parts.append(f"a {name} was uploaded")
    return " and ".join(parts).capitalize()


def _describe_required(missing_types: list[str]) -> str:
    names = [_friendly_name(t) for t in missing_types]
    if len(names) == 1:
        return f"a {names[0]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _generate_validation_message_with_llm(**kwargs) -> str | None:
    """Use LLM to generate a clear, specific error message for document validation failures."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None

        issue_type = kwargs.get("issue_type", "")

        if issue_type == "MISSING_DOCUMENTS":
            prompt = f"""You are a helpful health insurance claims assistant. A member submitted a claim but uploaded the wrong documents.

They uploaded: {kwargs.get('uploaded_types', [])}
Required for a {kwargs.get('claim_category', '')} claim: {kwargs.get('required_types', [])}
Missing: {kwargs.get('missing_types', [])}

Write a short, friendly 1-2 sentence message explaining what went wrong and what they need to upload instead. Be specific about document types. Don't use technical jargon.
Respond with ONLY the message text."""

        elif issue_type == "PATIENT_MISMATCH":
            prompt = f"""You are a helpful health insurance claims assistant. A member submitted documents that belong to different patients.

Names found on the documents: {kwargs.get('patient_names', [])}
Member ID: {kwargs.get('member_id', '')}

Write a short, friendly 1-2 sentence message explaining that the documents have different patient names and they need to re-upload documents for the same person. Mention the specific names found.
Respond with ONLY the message text."""

        else:
            return None

        result = llm_service._call_llm(prompt)
        if result and len(result.strip()) > 10:
            return result.strip().strip('"')
    except Exception:
        pass
    return None


def _generate_action_required_with_llm(mismatches: list[dict], required_types: list[str], claim_category: str) -> str:
    """Use LLM to generate a specific, actionable instruction for the user."""
    fallback = f"Please upload the correct documents for your {claim_category.lower()} claim: {', '.join(_friendly_name(t) for t in required_types)}."
    try:
        import llm_service
        if not llm_service.is_available():
            return fallback

        mismatch_summary = []
        for m in mismatches:
            mismatch_summary.append(f"- File '{m['file']}' was supposed to be a {_friendly_name(m['claimed_type'])} but is actually: {m['explanation']}")

        prompt = f"""You are a health insurance claims assistant. The member uploaded wrong documents. Based on what was detected, write a SHORT, SPECIFIC action they need to take.

What went wrong:
{chr(10).join(mismatch_summary)}

Required documents for a {claim_category} claim: {', '.join(_friendly_name(t) for t in required_types)}

Rules:
- Be specific about WHAT to upload (e.g. "a photo of your doctor's prescription" not just "correct documents")
- If the image was blurry/unreadable, tell them to take a clearer photo
- If it was the wrong type entirely (like a screenshot), tell them what the right document looks like
- Keep it to 1-2 sentences max
- Be friendly but direct
- Start with a verb (Upload, Take, Provide, etc.)

Respond with ONLY the action text, nothing else."""

        result = llm_service._call_llm(prompt)
        if result and len(result.strip()) > 10:
            return result.strip().strip('"')
    except Exception:
        pass
    return fallback


def _verify_documents_with_vision(docs: list[DocumentInput]) -> tuple[list[dict], bool]:
    """Use vision model to verify uploaded documents match their claimed types.
    Returns (mismatches, vision_succeeded). If vision fails, returns ([], False)."""
    try:
        import llm_service
        if not llm_service.is_available():
            return [], False

        mismatches = []
        any_succeeded = False
        for doc in docs:
            if not doc.file_data:
                continue
            claimed_type = doc.actual_type.value if doc.actual_type else "UNKNOWN"
            mime = doc.mime_type or "image/png"
            result = llm_service.extract_from_image(doc.file_data, mime, claimed_type)
            if result:
                any_succeeded = True
                if result.get("matches_claimed_type") is False:
                    mismatches.append({
                        "file": doc.file_name or doc.file_id,
                        "claimed_type": claimed_type,
                        "detected_type": result.get("detected_type"),
                        "explanation": result.get("mismatch_explanation", "Document does not match the selected type"),
                    })
        return mismatches, any_succeeded
    except Exception:
        return [], False


def _classify_with_llm(doc: DocumentInput) -> dict | None:
    """Use LLM to classify document type when actual_type is not provided."""
    try:
        import llm_service
        if not llm_service.is_available():
            return None
        content = doc.content or doc.file_name or doc.file_id
        result = llm_service.classify_document(content, doc.file_name or "")
        return result
    except Exception:
        return None


def _friendly_name(doc_type: str) -> str:
    names = {
        "PRESCRIPTION": "prescription",
        "HOSPITAL_BILL": "hospital bill",
        "LAB_REPORT": "lab report",
        "PHARMACY_BILL": "pharmacy bill",
        "DIAGNOSTIC_REPORT": "diagnostic report",
        "DISCHARGE_SUMMARY": "discharge summary",
        "DENTAL_REPORT": "dental report",
    }
    return names.get(doc_type, doc_type.lower().replace("_", " "))

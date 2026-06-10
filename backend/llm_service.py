"""LLM service wrapping Groq (Llama 3.3 70B) for document understanding and reasoning."""
from __future__ import annotations

import json
import os
from typing import Optional

from groq import Groq

_client: Optional[Groq] = None


def _get_client() -> Optional[Groq]:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if api_key:
            _client = Groq(api_key=api_key)
    return _client


def is_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def _call_llm(prompt: str) -> Optional[str]:
    client = _get_client()
    if not client:
        return None
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.1,
        )
        return response.choices[0].message.content
    except Exception:
        return None


def _call_vision(prompt: str, image_base64: str, mime_type: str = "image/png") -> Optional[str]:
    """Call the vision model with an image."""
    client = _get_client()
    if not client:
        return None
    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                ],
            }],
            max_tokens=1024,
            temperature=0.1,
        )
        return response.choices[0].message.content
    except Exception:
        return None


def extract_from_image(image_base64: str, mime_type: str = "image/png", claimed_type: str = "") -> Optional[dict]:
    """Extract structured data from a document image using vision model."""
    if not is_available():
        return None

    prompt = f"""You are a medical document data extraction system for Indian health insurance claims.

Analyze this uploaded medical document image. The user claims this is a: {claimed_type or "unknown type"}

Extract ALL information you can see and return this JSON:
{{
    "detected_type": "PRESCRIPTION|HOSPITAL_BILL|LAB_REPORT|PHARMACY_BILL|DIAGNOSTIC_REPORT|DISCHARGE_SUMMARY|DENTAL_REPORT",
    "matches_claimed_type": true/false,
    "mismatch_explanation": "explain what the document actually is vs what was claimed (only if mismatch)",
    "patient_name": "string or null",
    "doctor_name": "string or null",
    "doctor_registration": "string or null",
    "hospital_name": "string or null",
    "diagnosis": "string or null",
    "treatment": "string or null",
    "date": "YYYY-MM-DD or null",
    "medicines": ["list"] or [],
    "tests_ordered": ["list"] or [],
    "line_items": [{{"description": "string", "amount": number}}] or [],
    "total_amount": number or null,
    "quality": "GOOD|FAIR|POOR|UNREADABLE",
    "confidence": 0.0 to 1.0
}}

Respond with ONLY the JSON object."""

    text = _call_vision(prompt, image_base64, mime_type)
    return _parse_json_response(text)


def _parse_json_response(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                pass
        return None


def classify_document(document_content: str | dict, file_name: str = "") -> Optional[dict]:
    """Classify a document into a type and assess quality."""
    if not is_available():
        return None

    prompt = f"""You are a medical document classifier for Indian health insurance claims.

Given this document content, classify it into exactly ONE of these types:
- PRESCRIPTION (doctor's prescription/Rx)
- HOSPITAL_BILL (hospital or clinic bill/invoice/receipt)
- LAB_REPORT (diagnostic/lab test report)
- PHARMACY_BILL (pharmacy/chemist bill)
- DIAGNOSTIC_REPORT (MRI/CT/X-ray report)
- DISCHARGE_SUMMARY (hospital discharge summary)
- DENTAL_REPORT (dental examination report)

Also assess the document quality:
- GOOD (all text clearly readable)
- FAIR (mostly readable, some parts unclear)
- POOR (significant portions unclear)
- UNREADABLE (cannot extract meaningful information)

Document filename: {file_name}
Document content: {json.dumps(document_content) if isinstance(document_content, dict) else document_content}

Respond in this exact JSON format only, no other text:
{{"type": "DOCUMENT_TYPE", "quality": "QUALITY", "confidence": 0.95, "reasoning": "brief explanation"}}"""

    text = _call_llm(prompt)
    return _parse_json_response(text)


def extract_document_data(document_content: str | dict, document_type: str = "") -> Optional[dict]:
    """Extract structured data from a medical document."""
    if not is_available():
        return None

    prompt = f"""You are a medical document data extraction system for Indian health insurance claims.

Extract all relevant structured information from this document.

Document type: {document_type}
Document content: {json.dumps(document_content) if isinstance(document_content, dict) else document_content}

Extract and return this JSON (include only fields you can find, use null for missing):
{{
    "patient_name": "string or null",
    "doctor_name": "string or null",
    "doctor_registration": "string or null",
    "hospital_name": "string or null",
    "diagnosis": "string or null",
    "treatment": "string or null",
    "date": "YYYY-MM-DD or null",
    "medicines": ["list of medicines"] or [],
    "tests_ordered": ["list of tests"] or [],
    "line_items": [{{"description": "string", "amount": number}}] or [],
    "total_amount": number or null,
    "confidence": 0.0 to 1.0
}}

Respond with ONLY the JSON object, no other text."""

    text = _call_llm(prompt)
    return _parse_json_response(text)


def match_diagnosis_to_conditions(diagnosis: str, treatment: str = "") -> Optional[dict]:
    """Use LLM to semantically match a diagnosis to policy conditions."""
    if not is_available():
        return None

    from policy_engine import get_exclusions, get_waiting_periods

    exclusions = get_exclusions()
    waiting_periods = get_waiting_periods()

    prompt = f"""You are a health insurance policy analyst. Given a diagnosis and treatment, determine:
1. Does this match any EXCLUDED conditions?
2. Does this match any conditions with WAITING PERIODS?

Diagnosis: {diagnosis}
Treatment: {treatment or "Not specified"}

EXCLUDED CONDITIONS (if the diagnosis/treatment matches ANY of these, it is excluded):
{json.dumps(exclusions['conditions'], indent=2)}

CONDITIONS WITH WAITING PERIODS (use these exact keys):
{json.dumps(list(waiting_periods.get('specific_conditions', {}).keys()), indent=2)}

Be precise:
- "Type 2 Diabetes Mellitus" or "T2DM" → matches "diabetes"
- "Morbid Obesity BMI 37" or "Bariatric Consultation" → matches "Obesity and weight loss programs" (excluded) AND "obesity_treatment" (waiting period)
- "Lumbar Disc Herniation" → does NOT match "hernia" (disc herniation is a spinal condition, hernia is abdominal wall)
- "Viral Fever" → matches nothing
- "Teeth Whitening" → matches "Cosmetic or aesthetic procedures" (excluded)
- "Chronic Joint Pain" → matches nothing (it's a symptom, not an excluded condition)
- "Panchakarma Therapy" → matches nothing (it's alternative medicine, not excluded)

Respond with ONLY this JSON, no other text:
{{
    "matched_exclusions": ["exact exclusion text from the list above"] or [],
    "matched_waiting_period_conditions": ["exact condition key like diabetes, hypertension"] or [],
    "is_excluded": true/false,
    "reasoning": "brief explanation"
}}"""

    text = _call_llm(prompt)
    return _parse_json_response(text)

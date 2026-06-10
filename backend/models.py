from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    UNREADABLE = "UNREADABLE"


class Decision(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTION_REQUIRED = "ACTION_REQUIRED"


class TraceStepStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    STOP = "STOP"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class DocumentInput(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    actual_type: Optional[DocumentType] = None
    quality: Optional[DocumentQuality] = None
    content: Optional[dict] = None
    patient_name_on_doc: Optional[str] = None
    file_data: Optional[str] = None
    mime_type: Optional[str] = None


class ClaimHistoryItem(BaseModel):
    claim_id: str
    date: str
    amount: float
    provider: Optional[str] = None


class ClaimSubmission(BaseModel):
    member_id: Optional[str] = None
    member_name: Optional[str] = None
    policy_id: str = "PLUM_GHI_2024"
    claim_category: ClaimCategory
    treatment_date: str
    claimed_amount: float
    hospital_name: Optional[str] = None
    documents: list[DocumentInput]
    ytd_claims_amount: Optional[float] = 0
    claims_history: Optional[list[ClaimHistoryItem]] = None
    simulate_component_failure: Optional[bool] = False


class TraceStep(BaseModel):
    agent: str
    status: TraceStepStatus
    duration_ms: float = 0
    details: dict = Field(default_factory=dict)
    message: Optional[str] = None


class LineItemDecision(BaseModel):
    description: str
    amount: float
    covered: bool
    reason: Optional[str] = None


class Deduction(BaseModel):
    type: str
    amount: float
    detail: str


class ClaimDecision(BaseModel):
    claim_id: str
    status: Decision
    approved_amount: Optional[float] = None
    claimed_amount: float
    confidence: float = 0.0
    summary: str = ""
    rejection_reasons: list[str] = Field(default_factory=list)
    line_item_decisions: list[LineItemDecision] = Field(default_factory=list)
    deductions: list[Deduction] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    requires_action: Optional[str] = None
    error_message: Optional[str] = None


class ExtractedData(BaseModel):
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    hospital_name: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    treatment_date: Optional[str] = None
    medicines: list[str] = Field(default_factory=list)
    tests_ordered: list[str] = Field(default_factory=list)
    line_items: list[dict] = Field(default_factory=list)
    total_amount: Optional[float] = None
    confidence: float = 0.0

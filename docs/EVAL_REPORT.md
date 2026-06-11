# Eval Report
## Summary
**12/12 test cases matched expected outcomes.**

---

## TC001: Wrong Document Uploaded
**Result: MATCH**

### System Decision
- **Status**: ACTION_REQUIRED
- **Confidence**: 0.95
- **Summary**: Wrong documents uploaded: 2 prescriptions were uploaded, but a hospital bill is required for consultation claims. Please upload: hospital bill.
- **Error Message**: Upload a hospital bill — take a clear photo or scan of the original document and re-submit your claim.

### Processing Trace
| ⊘ | **document_validator** | STOP | Wrong documents uploaded: 2 prescriptions were uploaded, but a hospital bill is required for consultation claims. Please upload: hospital bill. |

### Expected vs Actual

### System Must (Manual Check)
- [ ] Stop before making any claim decision
- [ ] Tell the member specifically what document type was uploaded and what is needed instead
- [ ] Not return a generic error — the message must name the uploaded document type and the required document type

---

## TC002: Unreadable Document
**Result: MATCH**

### System Decision
- **Status**: ACTION_REQUIRED
- **Confidence**: 0.95
- **Summary**: Document quality issue: Your pharmacy bill is too blurry or unclear to read.
- **Error Message**: Take a clearer photo of your pharmacy bill. Make sure the document is flat, well-lit, and all text is fully visible with no shadows or blur.

### Processing Trace
| ⊘ | **document_validator** | STOP | Document quality issue: Your pharmacy bill is too blurry or unclear to read. |

### Expected vs Actual

### System Must (Manual Check)
- [ ] Identify that the pharmacy bill cannot be read
- [ ] Ask the member to re-upload that specific document
- [ ] Not reject the claim outright

---

## TC003: Documents Belong to Different Patients
**Result: MATCH**

### System Decision
- **Status**: ACTION_REQUIRED
- **Confidence**: 0.95
- **Summary**: Document mismatch: The documents appear to belong to different patients. Found different names: "Rajesh Kumar", "Arjun Mehta".
- **Error Message**: Re-upload documents that all belong to the same person. Your current uploads have different names (Rajesh Kumar, Arjun Mehta) — make sure every document is for the patient making this claim.

### Processing Trace
| ⊘ | **document_validator** | STOP | Document mismatch: The documents appear to belong to different patients. Found different names: "Rajesh Kumar", "Arjun Mehta". |

### Expected vs Actual

### System Must (Manual Check)
- [ ] Detect that the documents belong to different people
- [ ] Surface this to the member with the specific names found on each document
- [ ] Not proceed to a claim decision

---

## TC004: Clean Consultation — Full Approval
**Result: MATCH**

### System Decision
- **Status**: APPROVED
- **Approved Amount**: ₹1,350
- **Confidence**: 0.95
- **Summary**: Claim approved for ₹1,350 (claimed: ₹1,500). Deductions: 10% co-pay deducted (₹150).

### Deductions
- 10% co-pay deducted (₹150)

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✓ | **adjudicator** | COMPLETE | Decision: APPROVED — ₹1,350 approved. Base amount: ₹1,500 → After 10% co-pay: ₹1,350 → Approved amount: ₹1,350 |
|   | ✓ member_eligible | PASS | Rajesh Kumar (EMP001) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ✓ exclusions | PASS | Viral Fever not excluded |
|   | ✓ pre_authorization | PASS | No pre-authorization required |
|   | ✓ per_claim_limit | PASS | ₹1,500 within per-claim limit of ₹5,000 |
|   | ✓ sub_limit | PASS | ₹1,500 within consultation sub-limit of ₹2,000 |
|   | ◐ network_discount | N/A | Not a network hospital |
|   | ✓ copay | APPLIED | 10% co-pay applied |

### Expected vs Actual
- Decision: ✓ Expected `APPROVED`, Got `APPROVED`
- Amount: ✓ Expected ₹1,350, Got ₹1,350

---

## TC005: Waiting Period — Diabetes
**Result: MATCH**

### System Decision
- **Status**: REJECTED
- **Confidence**: 0.95
- **Summary**: Claim rejected. Reason: Within diabetes waiting period (44 days since joining, 90 required) Eligible from: 2024-11-30.
- **Rejection Reasons**: Within diabetes waiting period (44 days since joining, 90 required) Eligible from: 2024-11-30.

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✗ | **adjudicator** | FAIL | Rejected: Within diabetes waiting period (44 days since joining, 90 required). Eligible from: 2024-11-30. |
|   | ✓ member_eligible | PASS | Vikram Joshi (EMP005) active since 2024-09-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✗ waiting_period | FAIL | Within diabetes waiting period (44 days since joining, 90 required) |

### Expected vs Actual
- Decision: ✓ Expected `REJECTED`, Got `REJECTED`

### System Must (Manual Check)
- [ ] State the date from which the member will be eligible for diabetes-related claims

---

## TC006: Dental Partial Approval — Cosmetic Exclusion
**Result: MATCH**

### System Decision
- **Status**: PARTIAL
- **Approved Amount**: ₹8,000
- **Confidence**: 0.85
- **Summary**: Claim partially approved for ₹8,000 (claimed: ₹12,000). Some items were excluded — see line-item breakdown.

### Line Item Decisions
- Root Canal Treatment: ₹8,000 — **Covered** (Covered under policy)
- Teeth Whitening: ₹4,000 — **Excluded** (Excluded: cosmetic/aesthetic procedure)

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✓ | **adjudicator** | COMPLETE | Decision: PARTIAL — ₹8,000 approved. Base amount: ₹8,000 → Approved amount: ₹8,000 |
|   | ✓ member_eligible | PASS | Priya Singh (EMP002) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ◐ exclusions | PARTIAL | Some procedures are excluded under dental policy |
|   | ✓ pre_authorization | PASS | No pre-authorization required |
|   | ✓ per_claim_limit | PASS | ₹8,000 within dental sub-limit of ₹10,000 |
|   | ✓ sub_limit | PASS | ₹8,000 within dental sub-limit of ₹10,000 |
|   | ◐ network_discount | N/A | Not a network hospital |

### Expected vs Actual
- Decision: ✓ Expected `PARTIAL`, Got `PARTIAL`
- Amount: ✓ Expected ₹8,000, Got ₹8,000

### System Must (Manual Check)
- [ ] Itemize which line items were approved and which were rejected
- [ ] State the reason for each rejection at the line-item level

---

## TC007: MRI Without Pre-Authorization
**Result: MATCH**

### System Decision
- **Status**: REJECTED
- **Confidence**: 0.95
- **Summary**: Claim rejected. Reason: Pre-authorization required for MRI Lumbar Spine (amount ₹15,000 exceeds ₹10,000 threshold) Please obtain pre-authorization and resubmit.
- **Rejection Reasons**: Pre-authorization required for MRI Lumbar Spine (amount ₹15,000 exceeds ₹10,000 threshold) Please obtain pre-authorization and resubmit.

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✗ | **adjudicator** | FAIL | Rejected: Pre-authorization required for MRI Lumbar Spine (amount ₹15,000 exceeds ₹10,000 threshold). Member must obtain pre-authorization and resubmit. |
|   | ✓ member_eligible | PASS | Suresh Patil (EMP007) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ✓ exclusions | PASS | Suspected Lumbar Disc Herniation not excluded |
|   | ✗ pre_authorization | FAIL | Pre-authorization required for MRI Lumbar Spine (amount ₹15,000 exceeds ₹10,000 threshold) |

### Expected vs Actual
- Decision: ✓ Expected `REJECTED`, Got `REJECTED`

### System Must (Manual Check)
- [ ] Explain that pre-authorization was required and not obtained
- [ ] Tell the member what they should do to resubmit with pre-auth

---

## TC008: Per-Claim Limit Exceeded
**Result: MATCH**

### System Decision
- **Status**: REJECTED
- **Confidence**: 0.95
- **Summary**: Claim rejected. Reason: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000
- **Rejection Reasons**: Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✗ | **adjudicator** | FAIL | Rejected: Claimed amount ₹7,500 exceeds per-claim limit of ₹5,000 |
|   | ✓ member_eligible | PASS | Amit Verma (EMP003) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ✓ exclusions | PASS | Gastroenteritis not excluded |
|   | ✓ pre_authorization | PASS | No pre-authorization required |
|   | ✗ per_claim_limit | FAIL | Claimed amount ₹7,500 exceeds per-claim limit of ₹5,000 |

### Expected vs Actual
- Decision: ✓ Expected `REJECTED`, Got `REJECTED`

### System Must (Manual Check)
- [ ] State the per-claim limit and the claimed amount clearly in the rejection message

---

## TC009: Fraud Signal — Multiple Same-Day Claims
**Result: MATCH**

### System Decision
- **Status**: MANUAL_REVIEW
- **Confidence**: 0.75
- **Summary**: Claim routed to manual review. Reason: Multiple same-day claims detected: 3 previous claims on 2024-10-30 (limit: 2). This is claim #4 for today.; Multiple providers on same day: City Clinic B, City Clinic A, Wellness Center

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✗ | **fraud_detector** | FAIL | Fraud check: FLAGGED — Multiple same-day claims detected: 3 previous claims on 2024-10-30 (limit: 2). This is claim #4 for today.; Multiple providers on same day: City Clinic B, City Clinic A, Wellness Center |
| ✓ | **adjudicator** | COMPLETE | Routed to manual review due to fraud signals: Multiple same-day claims detected: 3 previous claims on 2024-10-30 (limit: 2). This is claim #4 for today.; Multiple providers on same day: City Clinic B, City Clinic A, Wellness Center |
|   | ✓ member_eligible | PASS | Ravi Menon (EMP008) active since 2024-04-01 |
|   | ◐ fraud_check | FLAG | Fraud signals detected: Multiple same-day claims detected: 3 previous claims on 2024-10-30 (limit: 2). This is claim #4 for today.; Multiple providers on same day: City Clinic B, City Clinic A, Wellness Center |

### Expected vs Actual
- Decision: ✓ Expected `MANUAL_REVIEW`, Got `MANUAL_REVIEW`

### System Must (Manual Check)
- [ ] Flag the unusual same-day claim pattern
- [ ] Route to manual review rather than auto-rejecting
- [ ] Include the specific signals that triggered the flag in the output

---

## TC010: Network Hospital — Discount Applied
**Result: MATCH**

### System Decision
- **Status**: APPROVED
- **Approved Amount**: ₹3,240
- **Confidence**: 0.95
- **Summary**: Claim approved for ₹3,240 (claimed: ₹4,500). Deductions: 20% network hospital discount applied (₹900); 10% co-pay deducted (₹360).

### Deductions
- 20% network hospital discount applied (₹900)
- 10% co-pay deducted (₹360)

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✓ | **adjudicator** | COMPLETE | Decision: APPROVED — ₹3,240 approved. Base amount: ₹4,500 → After 20% network discount: ₹3,600 → After 10% co-pay: ₹3,240 → Approved amount: ₹3,240 |
|   | ✓ member_eligible | PASS | Deepak Shah (EMP010) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ✓ exclusions | PASS | Acute Bronchitis not excluded |
|   | ✓ pre_authorization | PASS | No pre-authorization required |
|   | ✓ per_claim_limit | PASS | ₹4,500 within per-claim limit of ₹5,000 |
|   | ✓ sub_limit | PASS | ₹4,500 within consultation sub-limit of ₹2,000 |
|   | ✓ network_discount | APPLIED | Network hospital (Apollo Hospitals) — discount applied |
|   | ✓ copay | APPLIED | 10% co-pay applied |

### Expected vs Actual
- Decision: ✓ Expected `APPROVED`, Got `APPROVED`
- Amount: ✓ Expected ₹3,240, Got ₹3,240

### System Must (Manual Check)
- [ ] Apply network discount before co-pay, not after
- [ ] Show the breakdown of discount and co-pay in the decision output

---

## TC011: Component Failure — Graceful Degradation
**Result: MATCH**

### System Decision
- **Status**: APPROVED
- **Approved Amount**: ₹4,000
- **Confidence**: 0.75
- **Summary**: Claim approved for ₹4,000 (claimed: ₹4,000). ⚠ Note: Components [extraction (partial)] experienced failures during processing. Confidence reduced. Manual review recommended.

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ◐ | **extraction** | PARTIAL | Extraction agent partially failed — basic data extracted, LLM validation skipped. Confidence reduced. |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✓ | **adjudicator** | COMPLETE | Decision: APPROVED — ₹4,000 approved. Base amount: ₹4,000 → Approved amount: ₹4,000 |
|   | ✓ member_eligible | PASS | Kavita Nair (EMP006) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✓ waiting_period | PASS | All waiting periods cleared (joined 2024-04-01) |
|   | ✓ exclusions | PASS | Chronic Joint Pain not excluded |
|   | ✓ pre_authorization | PASS | No pre-authorization required |
|   | ✓ per_claim_limit | PASS | ₹4,000 within alternative_medicine sub-limit of ₹8,000 |
|   | ✓ sub_limit | PASS | ₹4,000 within alternative_medicine sub-limit of ₹8,000 |
|   | ◐ network_discount | N/A | Not a network hospital |

### Expected vs Actual
- Decision: ✓ Expected `APPROVED`, Got `APPROVED`

### System Must (Manual Check)
- [ ] Not crash or return a 500 error
- [ ] Indicate in the output that a component failed and was skipped
- [ ] Return a confidence score lower than a normal full-pipeline approval
- [ ] Include a note that manual review is recommended due to incomplete processing

---

## TC012: Excluded Treatment
**Result: MATCH**

### System Decision
- **Status**: REJECTED
- **Confidence**: 0.95
- **Summary**: Claim rejected. Reason: Within obesity treatment waiting period (200 days since joining, 365 required) Eligible from: 2025-04-01.
- **Rejection Reasons**: Within obesity treatment waiting period (200 days since joining, 365 required) Eligible from: 2025-04-01.

### Processing Trace
| ✓ | **document_validator** | PASS | All documents validated successfully |
| ✓ | **extraction** | COMPLETE | Data extracted successfully from all documents |
| ✓ | **fraud_detector** | PASS | Fraud check: No fraud signals detected |
| ✗ | **adjudicator** | FAIL | Rejected: Within obesity treatment waiting period (200 days since joining, 365 required). Eligible from: 2025-04-01. |
|   | ✓ member_eligible | PASS | Anita Desai (EMP009) active since 2024-04-01 |
|   | ✓ fraud_check | PASS | No fraud signals |
|   | ✗ waiting_period | FAIL | Within obesity treatment waiting period (200 days since joining, 365 required) |

### Expected vs Actual
- Decision: ✓ Expected `REJECTED`, Got `REJECTED`

---

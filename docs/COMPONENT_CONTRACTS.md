# Component Contracts

Each component below defines its interface precisely. Another engineer can reimplement any component by satisfying this contract without reading the implementation code.

---

## 1. Orchestrator Agent

### Input
```typescript
interface ClaimSubmission {
  member_id: string;              // e.g. "EMP001"
  policy_id: string;              // e.g. "PLUM_GHI_2024"
  claim_category: "CONSULTATION" | "DIAGNOSTIC" | "PHARMACY" | "DENTAL" | "VISION" | "ALTERNATIVE_MEDICINE";
  treatment_date: string;         // ISO date "YYYY-MM-DD"
  claimed_amount: number;         // in INR
  hospital_name?: string;         // optional, used for network discount
  documents: DocumentInput[];     // 1 or more
  ytd_claims_amount?: number;     // year-to-date claims total
  claims_history?: ClaimHistoryItem[];  // previous claims for fraud detection
  simulate_component_failure?: boolean; // test flag
}
```

### Output
```typescript
interface ClaimDecision {
  claim_id: string;               // generated UUID
  status: "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";
  approved_amount: number | null; // null if rejected/manual_review
  claimed_amount: number;
  confidence: number;             // 0.0 to 1.0
  summary: string;                // human-readable one-line summary
  rejection_reasons: string[];    // populated only if rejected
  line_item_decisions: LineItemDecision[];  // for PARTIAL decisions
  deductions: Deduction[];        // network discount, co-pay
  trace: TraceStep[];             // ordered list of pipeline steps
  requires_action?: string;       // what the member needs to do
  error_message?: string;         // early-stop error for document issues
}
```

### Errors
- Never crashes. All exceptions are caught, logged to trace, and reflected in reduced confidence.
- Returns `MANUAL_REVIEW` if critical components fail.

### Behavior
1. Calls Document Validator → if STOP, returns immediately with error_message
2. Calls Extraction Agent → if fails, continues with partial data
3. Calls Fraud Detector → if fails, skips fraud check
4. Calls Adjudicator → if fails, returns MANUAL_REVIEW
5. Each failed component reduces confidence by 0.1-0.3

---

## 2. Document Validator Agent

### Input
```typescript
interface ValidatorInput {
  claim_category: string;         // determines required document types
  documents: DocumentInput[];     // uploaded documents with type and quality
}

interface DocumentInput {
  file_id: string;
  file_name?: string;
  actual_type?: "PRESCRIPTION" | "HOSPITAL_BILL" | "LAB_REPORT" | "PHARMACY_BILL" | "DIAGNOSTIC_REPORT" | "DISCHARGE_SUMMARY" | "DENTAL_REPORT";
  quality?: "GOOD" | "FAIR" | "POOR" | "UNREADABLE";
  content?: object;               // structured content (test mode)
  patient_name_on_doc?: string;   // for consistency checking
}
```

### Output
```typescript
interface ValidationResult {
  passed: boolean;
  message: string;    // empty if passed, specific error if failed
  details: {
    required_documents: string[];
    uploaded_documents: string[];
    validation_result: "PASS" | "MISSING_DOCUMENTS" | "UNREADABLE_DOCUMENT" | "PATIENT_MISMATCH";
    missing_types?: string[];
    unreadable_documents?: string[];
    patient_names_found?: string[];
    patient_consistency?: string;
    quality_check?: string;
  }
}
```

### Errors
- Catches all exceptions internally
- Returns `passed: false` with error detail on exception

### Behavior
- Check 1: All required doc types present (from policy_terms.json document_requirements)
- Check 2: No UNREADABLE quality documents
- Check 3: All patient_name_on_doc / content.patient_name values are consistent
- On failure: message MUST name specific document types (not generic errors)

### Error Message Requirements
- WRONG DOC: "You uploaded [X], but [Y] is required for [category] claims. Please upload: [list]"
- UNREADABLE: "Your [doc type] is too blurry or unclear to read. Please re-upload a clearer photo."
- MISMATCH: "Documents appear to belong to different patients: [name1], [name2]. All documents must belong to the same patient."

---

## 3. Extraction Agent

### Input
```typescript
interface ExtractionInput {
  documents: DocumentInput[];     // with content field populated
  simulate_failure: boolean;      // test flag
}
```

### Output
```typescript
interface ExtractedData {
  patient_name: string | null;
  doctor_name: string | null;
  doctor_registration: string | null;
  hospital_name: string | null;
  diagnosis: string | null;
  treatment: string | null;
  treatment_date: string | null;
  medicines: string[];
  tests_ordered: string[];
  line_items: Array<{description: string, amount: number}>;
  total_amount: number | null;
  confidence: number;             // 0.0-1.0 based on field coverage
}
```

### Errors
- On LLM timeout/failure: returns partial ExtractedData with confidence 0.3-0.5
- On simulate_failure=true: returns minimal data with confidence 0.4

### Confidence Calculation
- Base: 0.5
- +0.1 per critical field extracted (patient_name, doctor_name, diagnosis, line_items, total_amount)
- Max: 1.0

---

## 4. Fraud Detector Agent

### Input
```typescript
interface FraudInput {
  member_id: string;
  treatment_date: string;
  claimed_amount: number;
  claims_history?: Array<{
    claim_id: string;
    date: string;
    amount: number;
    provider?: string;
  }>;
}
```

### Output
```typescript
interface FraudResult {
  flagged: boolean;               // true = route to manual review
  signals: string[];              // specific reasons for flagging
  fraud_score: number;            // 0.0-1.0
  details: {
    same_day_claims: number;
    monthly_claims: number;
    high_value: boolean;
    providers?: string[];
  }
}
```

### Errors
- On failure: returns `{flagged: false, signals: [], fraud_score: 0.0}`
- Orchestrator notes the skipped check in trace

### Rules (from policy_terms.json fraud_thresholds)
- same_day_claims >= same_day_claims_limit → flag
- monthly_claims >= monthly_claims_limit → flag  
- claimed_amount > high_value_claim_threshold → flag
- claimed_amount > auto_manual_review_above → flag

---

## 5. Adjudicator Agent

### Input
```typescript
interface AdjudicationInput {
  claim: ClaimSubmission;
  extracted: ExtractedData;
  fraud_result: FraudResult;
}
```

### Output
```typescript
interface AdjudicationResult {
  decision: "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";
  approved_amount: number | null;
  reasons: string[];              // explanation for decision
  confidence: number;
  deductions: Array<{type: string, amount: number, detail: string}>;
  line_item_decisions: Array<{description: string, amount: number, covered: boolean, reason: string}>;
  checks: Array<{check: string, result: string, detail: string}>;
}
```

### Errors
- On failure: orchestrator catches and returns MANUAL_REVIEW

### Check Order (strict — must be in this sequence)
1. **member_eligible**: Member exists in policy members list
2. **fraud_check**: If fraud_result.flagged → MANUAL_REVIEW (short-circuit)
3. **waiting_period**: Days since join_date vs condition-specific waiting days
4. **exclusions**: Condition/treatment in exclusions list; line-item level for dental/vision
5. **pre_authorization**: Required for MRI/CT/PET > threshold
6. **per_claim_limit**: Consultation uses per_claim_limit; others use category sub_limit
7. **network_discount**: Applied FIRST if hospital is in network_hospitals list
8. **copay**: Applied SECOND on the post-discount amount

### Critical Calculation: Network Discount + Co-pay
```
effective = claimed_amount
if network_hospital:
    effective = effective * (1 - network_discount_pct/100)    // FIRST
copay_deduction = effective * (copay_pct/100)
approved = effective - copay_deduction                        // SECOND
```

---

## 6. Policy Engine

### Interface
```python
load_policy(path?: str) -> dict
get_member(member_id: str) -> dict | None
get_document_requirements(claim_category: str) -> {required: str[], optional: str[]}
get_category_config(claim_category: str) -> dict | None
is_network_hospital(hospital_name: str) -> bool
check_waiting_period(member, treatment_date, diagnosis) -> {passed, reason, eligible_date?}
check_exclusions(diagnosis, treatment, category, line_items) -> {excluded, fully_excluded, excluded_items, covered_items, reason}
check_pre_authorization(category, line_items, amount) -> {required, reason}
calculate_approved_amount(amount, category, hospital, line_items, covered_items?) -> {approved_amount, deductions, breakdown}
```

### Constraints
- ALL rules read from policy_terms.json at runtime
- ZERO hardcoded policy values
- Policy loaded once on startup, cached in memory

---

## 7. Trace Step Format

Every agent produces a TraceStep:

```typescript
interface TraceStep {
  agent: string;              // "document_validator" | "extraction" | "fraud_detector" | "adjudicator"
  status: "PASS" | "FAIL" | "STOP" | "COMPLETE" | "PARTIAL" | "SKIPPED" | "ERROR";
  duration_ms: number;
  details: object;            // agent-specific structured data
  message: string;            // human-readable summary of what happened
}
```

The trace is an ordered array of TraceSteps, one per agent that executed. An ops person reads the trace top-to-bottom to understand exactly what happened to any claim.

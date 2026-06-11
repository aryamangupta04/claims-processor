# Architecture Document

## System Overview

The Claims Processing System is a multi-agent pipeline that automates health insurance claim adjudication. It receives a claim submission, validates documents, extracts structured data, checks for fraud patterns, applies policy rules, and produces an explainable decision.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FRONTEND (Next.js / React)                       │
│   ┌────────────────────┐          ┌──────────────────────────────┐ │
│   │  Claim Submission   │          │  Decision + Trace Viewer      │ │
│   │  Form               │          │  (step-by-step reasoning)     │ │
│   └────────┬───────────┘          └──────────▲───────────────────┘ │
└────────────┼──────────────────────────────────┼─────────────────────┘
             │ POST /api/claims                 │ Response (inline)
             ▼                                  │
┌────────────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI / Python)                         │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                     ORCHESTRATOR AGENT                            │ │
│  │   Sequential pipeline: Validate → Extract → Fraud → Adjudicate   │ │
│  │   Catches failures per stage, adjusts confidence, never crashes   │ │
│  └──┬─────────────┬───────────────┬───────────────┬────────────────┘ │
│     │             │               │               │                  │
│     ▼             ▼               ▼               ▼                  │
│  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────────┐       │
│  │DOC     │  │EXTRACTION│  │ FRAUD    │  │  ADJUDICATOR    │       │
│  │VALID.  │  │AGENT     │  │ DETECTOR │  │  AGENT          │       │
│  │AGENT   │  │          │  │          │  │                 │       │
│  └────────┘  └──────────┘  └──────────┘  └─────────────────┘       │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                    POLICY ENGINE (Pure Functions)                  │ │
│  │         Reads policy_terms.json — zero hardcoded rules            │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Orchestrator Agent (`agents/orchestrator.py`)
The central coordinator. Receives a claim, runs it through all pipeline stages in sequence, collects trace output from each agent, and assembles the final decision. If any stage throws an exception, it catches it, logs the failure to the trace, reduces confidence, and continues with remaining stages.

**Design choice**: Sequential pipeline rather than parallel execution. Claims processing is inherently sequential — you can't adjudicate before extracting, and extraction is meaningless if documents are invalid. Parallelism would add complexity without benefit.

### 2. Document Validator Agent (`agents/document_validator.py`)
First gate in the pipeline. Checks three things:
1. **Completeness**: Are all required document types present for this claim category?
2. **Quality**: Are documents readable (not blurry/unreadable)?
3. **Consistency**: Do all documents belong to the same patient?

Returns STOP with a specific, actionable error message if any check fails. The error messages name exact document types and tell the member precisely what to do.

### 3. Extraction Agent (`agents/extraction.py`)
Pulls structured data from documents: patient name, doctor details, diagnosis, treatment, line items, amounts. Currently operates in two modes:
- **Structured mode** (test cases): Documents provide content as JSON objects
- **Vision mode** (production): Would call Gemini Flash to extract from images/PDFs

Returns an `ExtractedData` object with a confidence score based on how many fields were successfully extracted.

### 4. Fraud Detector Agent (`agents/fraud_detector.py`)
Pattern-based anomaly detection. Checks:
- Same-day claim frequency (limit: 2)
- Monthly claim frequency (limit: 6)
- High-value claims (threshold: ₹25,000)
- Multiple providers on same day

Produces a fraud score and list of specific signals. If flagged, the orchestrator routes to MANUAL_REVIEW rather than auto-rejecting.

### 5. Adjudicator Agent (`agents/adjudicator.py`)
The decision engine. Applies policy rules in strict order:
1. Member eligibility
2. Fraud check result
3. Waiting periods
4. Exclusions (full or partial)
5. Pre-authorization requirements
6. Per-claim / sub-limit checks
7. Network discount (BEFORE co-pay)
8. Co-pay calculation (AFTER discount)

Each check is logged with pass/fail status and detail. The order matters — network discount before co-pay produces different intermediate values that matter for the trace even though the final math is commutative.

### 6. Policy Engine (`policy_engine.py`)
Pure functions that read and interpret `policy_terms.json`. Zero hardcoded rules. Provides:
- Member lookup
- Document requirement lookup
- Waiting period calculation
- Exclusion checking (with line-item granularity for dental/vision)
- Pre-authorization requirement checking
- Amount calculation (discount → co-pay)

## Design Decisions

### Why multi-agent over a single function?
- **Failure isolation**: If extraction fails, fraud detection and basic adjudication can still proceed
- **Testability**: Each agent can be tested independently
- **Extensibility**: New checks (e.g., duplicate claim detection) can be added as new agents
- **Observability**: Each agent naturally produces its own trace segment

### Why sequential over event-driven?
Claims processing has strict ordering dependencies. An event bus would add infrastructure complexity (message queues, eventual consistency) without benefit for a request-response flow that takes <100ms.

### Why SQLite (in-memory for now)?
The system stores claims in a dictionary for the demo. In production, SQLite → PostgreSQL migration is trivial because the data model is simple (claims + decisions + traces). No ORM needed.

### Alternatives Rejected
- **LangChain/LangGraph**: Too much abstraction for what amounts to sequential function calls with error handling. Direct Python is clearer and faster.
- **Microservices per agent**: Over-engineering for this scale. A monolith with clean module boundaries achieves the same separation without network overhead.
- **Rules engine (Drools-style)**: The policy logic is complex but not dynamic at runtime. Pure functions reading JSON are simpler, testable, and sufficient.

## Scaling to 10x

At 750,000 claims/year (10x current 75,000):

1. **Stateless backend → horizontal scaling**: Each claim is independent. Deploy N instances behind a load balancer.
2. **PostgreSQL with read replicas**: Claims table, decisions table, traces as JSONB.
3. **Async extraction**: Vision LLM calls are the bottleneck (~2-5s each). Queue them and process asynchronously. Return a pending status and notify via webhook.
4. **Redis for fraud checks**: Same-day and monthly counts need fast lookups. Redis counters with TTL.
5. **Kafka for audit trail**: Every decision event published to a stream for compliance and reprocessing.

The architecture as-is handles 10x with just horizontal scaling of the FastAPI service. The bottleneck is LLM calls, which are already isolated to a single agent and can be made async without touching other components.

## Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|------------|
| LLM timeout | Extraction returns partial data | Fallback to metadata, reduce confidence |
| Invalid document content | Extraction fields missing | Calculate confidence based on field coverage |
| Policy JSON corrupt | All claims fail | Load and validate on startup, reject start if invalid |
| Fraud service down | Can't check patterns | Skip fraud, flag in trace, reduce confidence |
| Adjudicator crash | No decision possible | Route to MANUAL_REVIEW with explanation |

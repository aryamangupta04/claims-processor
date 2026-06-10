# Plum Claims Processing System

A multi-agent AI-powered health insurance claims processing pipeline that automates claim adjudication with full explainability.

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+

### Setup & Run

**Terminal 1 — Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 in your browser.

### Run Tests
```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v
```

All 12 test cases from `test_cases.json` pass.

---

## Architecture

Multi-agent pipeline with 5 specialized agents:

```
Claim → [Document Validator] → [Extraction Agent] → [Fraud Detector] → [Adjudicator] → Decision
              ↓ STOP                                                          ↓
         Specific error                                                  APPROVED / PARTIAL /
         message to member                                               REJECTED / MANUAL_REVIEW
```

Each agent produces a trace step explaining what it checked and what it found. The full trace is returned with every decision.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design document.

---

## Key Features

- **Multi-agent architecture** — 5 specialized agents with clear interfaces
- **Full explainability** — every decision includes a step-by-step trace
- **Graceful degradation** — component failures don't crash the system
- **Specific error messages** — document problems get actionable, specific feedback
- **Policy-driven** — all rules read from `policy_terms.json`, nothing hardcoded

---

## Project Structure

```
claims-processor/
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── models.py                # Pydantic data models
│   ├── policy_engine.py         # Policy rules (reads JSON)
│   ├── policy_terms.json        # Policy configuration
│   ├── agents/
│   │   ├── orchestrator.py      # Pipeline coordinator
│   │   ├── document_validator.py
│   │   ├── extraction.py
│   │   ├── fraud_detector.py
│   │   └── adjudicator.py
│   └── tests/
│       └── test_pipeline.py     # All 12 test cases
├── frontend/
│   └── app/
│       ├── page.tsx             # Main UI
│       └── components/
│           ├── ClaimForm.tsx     # Submission form
│           └── DecisionView.tsx  # Decision + trace viewer
└── docs/
    ├── ARCHITECTURE.md          # Design document
    ├── COMPONENT_CONTRACTS.md   # Interface specifications
    └── EVAL_REPORT.md           # Test case results
```

---

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/claims` | POST | Submit a claim for processing |
| `/api/claims/{id}` | GET | Retrieve a processed claim |
| `/api/claims` | GET | List all processed claims |
| `/api/policy/members` | GET | List policy members |
| `/api/policy/categories` | GET | List claim categories |

---

## Documentation

- [Architecture Document](docs/ARCHITECTURE.md) — system design, trade-offs, scaling strategy
- [Component Contracts](docs/COMPONENT_CONTRACTS.md) — input/output specs for each agent
- [Eval Report](docs/EVAL_REPORT.md) — all 12 test case results with traces

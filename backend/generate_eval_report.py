"""Generate the eval report by running all 12 test cases and showing full output."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from models import ClaimSubmission
from agents.orchestrator import process_claim

TEST_CASES_PATH = Path(__file__).parent.parent.parent / "test_cases.json"

with open(TEST_CASES_PATH) as f:
    test_data = json.load(f)


def run_test_case(tc):
    inp = tc["input"]
    docs = []
    for d in inp["documents"]:
        doc = {"file_id": d.get("file_id", "F000")}
        if "actual_type" in d:
            doc["actual_type"] = d["actual_type"]
        if "quality" in d:
            doc["quality"] = d["quality"]
        if "content" in d:
            doc["content"] = d["content"]
        if "patient_name_on_doc" in d:
            doc["patient_name_on_doc"] = d["patient_name_on_doc"]
        if "file_name" in d:
            doc["file_name"] = d["file_name"]
        docs.append(doc)

    claim_data = {
        "member_id": inp["member_id"],
        "policy_id": inp.get("policy_id", "PLUM_GHI_2024"),
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "claimed_amount": inp["claimed_amount"],
        "documents": docs,
    }

    if "hospital_name" in inp:
        claim_data["hospital_name"] = inp["hospital_name"]
    if "ytd_claims_amount" in inp:
        claim_data["ytd_claims_amount"] = inp["ytd_claims_amount"]
    if "claims_history" in inp:
        # Seed prior claims into the DB (fraud detection reads server-side history)
        import database
        conn = database.get_connection()
        for h in inp["claims_history"]:
            conn.execute(
                "INSERT INTO claims_history (member_id, claim_id, claim_date, amount, provider, status) VALUES (?, ?, ?, ?, ?, ?)",
                (inp.get("member_id"), h["claim_id"], h["date"], h["amount"], h.get("provider"), "APPROVED"),
            )
        conn.commit()
    if "simulate_component_failure" in inp:
        claim_data["simulate_component_failure"] = inp["simulate_component_failure"]

    claim = ClaimSubmission(**claim_data)
    return process_claim(claim)


def check_match(tc, result):
    expected = tc["expected"]
    issues = []

    if expected.get("decision"):
        if result.status.value != expected["decision"]:
            issues.append(f"Decision: expected {expected['decision']}, got {result.status.value}")

    if "approved_amount" in expected and expected["approved_amount"] is not None:
        if result.approved_amount != expected["approved_amount"]:
            issues.append(f"Amount: expected {expected['approved_amount']}, got {result.approved_amount}")

    if "confidence_score" in expected:
        conf_spec = expected["confidence_score"]
        if "above" in conf_spec:
            threshold = float(conf_spec.split(" ")[1])
            if result.confidence <= threshold:
                issues.append(f"Confidence: expected above {threshold}, got {result.confidence:.2f}")

    if "system_must" in expected:
        for requirement in expected["system_must"]:
            pass  # logged for manual review

    return issues


def main():
    report_lines = []
    report_lines.append("# Eval Report\n")
    report_lines.append("## Summary\n")

    results = []
    for tc in test_data["test_cases"]:
        result = run_test_case(tc)
        issues = check_match(tc, result)
        results.append((tc, result, issues))

    passed = sum(1 for _, _, issues in results if not issues)
    total = len(results)
    report_lines.append(f"**{passed}/{total} test cases matched expected outcomes.**\n\n")
    report_lines.append("---\n")

    for tc, result, issues in results:
        case_id = tc["case_id"]
        case_name = tc["case_name"]
        expected = tc["expected"]
        match_status = "MATCH" if not issues else "MISMATCH"

        report_lines.append(f"\n## {case_id}: {case_name}\n")
        report_lines.append(f"**Result: {match_status}**\n\n")

        report_lines.append(f"### System Decision\n")
        report_lines.append(f"- **Status**: {result.status.value}\n")
        if result.approved_amount is not None:
            report_lines.append(f"- **Approved Amount**: ₹{result.approved_amount:,.0f}\n")
        report_lines.append(f"- **Confidence**: {result.confidence:.2f}\n")
        report_lines.append(f"- **Summary**: {result.summary}\n")

        if result.error_message:
            report_lines.append(f"- **Error Message**: {result.error_message}\n")

        if result.rejection_reasons:
            report_lines.append(f"- **Rejection Reasons**: {'; '.join(result.rejection_reasons)}\n")

        if result.line_item_decisions:
            report_lines.append(f"\n### Line Item Decisions\n")
            for li in result.line_item_decisions:
                status = "Covered" if li.covered else "Excluded"
                report_lines.append(f"- {li.description}: ₹{li.amount:,.0f} — **{status}** ({li.reason})\n")

        if result.deductions:
            report_lines.append(f"\n### Deductions\n")
            for d in result.deductions:
                report_lines.append(f"- {d.detail}\n")

        report_lines.append(f"\n### Processing Trace\n")
        for step in result.trace:
            icon = {"PASS": "✓", "COMPLETE": "✓", "FAIL": "✗", "STOP": "⊘", "ERROR": "⚠", "PARTIAL": "◐"}.get(step.status.value, "?")
            report_lines.append(f"| {icon} | **{step.agent}** | {step.status.value} | {step.message} |\n")

            if step.details.get("checks"):
                for check in step.details["checks"]:
                    check_icon = "✓" if check["result"] in ("PASS", "APPLIED") else "✗" if check["result"] == "FAIL" else "◐"
                    report_lines.append(f"|   | {check_icon} {check['check']} | {check['result']} | {check['detail']} |\n")

        report_lines.append(f"\n### Expected vs Actual\n")
        if expected.get("decision"):
            exp_dec = expected["decision"]
            act_dec = result.status.value
            match = "✓" if exp_dec == act_dec else "✗"
            report_lines.append(f"- Decision: {match} Expected `{exp_dec}`, Got `{act_dec}`\n")

        if "approved_amount" in expected and expected["approved_amount"] is not None:
            exp_amt = expected["approved_amount"]
            act_amt = result.approved_amount
            match = "✓" if exp_amt == act_amt else "✗"
            report_lines.append(f"- Amount: {match} Expected ₹{exp_amt:,.0f}, Got ₹{act_amt:,.0f}\n")

        if "system_must" in expected:
            report_lines.append(f"\n### System Must (Manual Check)\n")
            for req in expected["system_must"]:
                report_lines.append(f"- [ ] {req}\n")

        if issues:
            report_lines.append(f"\n### Mismatch Explanation\n")
            for issue in issues:
                report_lines.append(f"- {issue}\n")

        report_lines.append("\n---\n")

    output_path = Path(__file__).parent.parent / "docs" / "EVAL_REPORT.md"
    with open(output_path, "w") as f:
        f.write("".join(report_lines))

    print(f"Eval report written to {output_path}")
    print(f"Result: {passed}/{total} test cases passed")


if __name__ == "__main__":
    main()

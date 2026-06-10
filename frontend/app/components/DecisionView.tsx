"use client";

import { useState } from "react";

interface Props {
  decision: any;
}

const STATUS_COLORS: Record<string, string> = {
  APPROVED: "bg-green-950/50 text-green-300 border-green-500/30",
  PARTIAL: "bg-yellow-950/50 text-yellow-300 border-yellow-500/30",
  REJECTED: "bg-red-950/50 text-red-300 border-red-500/30",
  MANUAL_REVIEW: "bg-orange-950/50 text-orange-300 border-orange-500/30",
};

const TRACE_STATUS_ICONS: Record<string, string> = {
  PASS: "✓",
  COMPLETE: "✓",
  FAIL: "✗",
  STOP: "⊘",
  ERROR: "⚠",
  PARTIAL: "◐",
  SKIPPED: "○",
};

const TRACE_STATUS_COLORS: Record<string, string> = {
  PASS: "text-green-600",
  COMPLETE: "text-green-600",
  FAIL: "text-red-600",
  STOP: "text-red-600",
  ERROR: "text-orange-600",
  PARTIAL: "text-yellow-600",
  SKIPPED: "text-gray-400",
};

export default function DecisionView({ decision }: Props) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([0, 1, 2, 3]));

  const toggleStep = (idx: number) => {
    const next = new Set(expandedSteps);
    if (next.has(idx)) next.delete(idx);
    else next.add(idx);
    setExpandedSteps(next);
  };

  return (
    <div className="space-y-4">
      {/* Decision Card */}
      <div className={`rounded-lg border p-4 ${STATUS_COLORS[decision.status] || "bg-gray-100"}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-lg font-bold">{decision.status}</span>
          <span className="text-sm font-mono">
            Confidence: {(decision.confidence * 100).toFixed(0)}%
          </span>
        </div>
        {decision.approved_amount !== null && decision.approved_amount !== undefined && (
          <p className="text-sm font-medium">
            Approved: ₹{decision.approved_amount.toLocaleString("en-IN")} / Claimed: ₹{decision.claimed_amount.toLocaleString("en-IN")}
          </p>
        )}
        <p className="text-sm mt-2">{decision.summary}</p>
        {decision.error_message && (
          <div className="mt-3 p-3 bg-purple-950/50 rounded-xl border border-purple-500/30">
            <p className="text-sm font-medium text-purple-200">Action Required:</p>
            <p className="text-sm mt-1 text-purple-100">{decision.error_message}</p>
          </div>
        )}
      </div>

      {/* Rejection Reasons */}
      {decision.rejection_reasons && decision.rejection_reasons.length > 0 && (
        <div className="bg-[#1A0533] rounded-2xl border border-purple-800/50 p-4">
          <h3 className="text-sm font-semibold text-purple-200 mb-2">Rejection Reasons</h3>
          <ul className="space-y-1">
            {decision.rejection_reasons.map((r: string, i: number) => (
              <li key={i} className="text-sm text-red-700 flex items-start gap-2">
                <span className="text-red-500 mt-0.5">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Line Item Decisions */}
      {decision.line_item_decisions && decision.line_item_decisions.length > 0 && (
        <div className="bg-[#1A0533] rounded-2xl border border-purple-800/50 p-4">
          <h3 className="text-sm font-semibold text-purple-200 mb-2">Line Item Breakdown</h3>
          <div className="space-y-2">
            {decision.line_item_decisions.map((item: any, i: number) => (
              <div key={i} className={`flex items-center justify-between p-2 rounded text-sm ${item.covered ? "bg-green-950/30" : "bg-red-950/30"}`}>
                <span className={item.covered ? "text-green-800" : "text-red-800"}>
                  {item.covered ? "✓" : "✗"} {item.description}
                </span>
                <div className="text-right">
                  <span className="font-mono">₹{item.amount.toLocaleString("en-IN")}</span>
                  {item.reason && (
                    <p className="text-xs text-purple-400">{item.reason}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Deductions */}
      {decision.deductions && decision.deductions.length > 0 && (
        <div className="bg-[#1A0533] rounded-2xl border border-purple-800/50 p-4">
          <h3 className="text-sm font-semibold text-purple-200 mb-2">Deductions Applied</h3>
          <div className="space-y-1">
            {decision.deductions.map((d: any, i: number) => (
              <div key={i} className="flex justify-between text-sm">
                <span className="text-purple-300">{d.detail}</span>
                <span className="font-mono text-red-600">-₹{d.amount.toLocaleString("en-IN")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Processing Trace */}
      {decision.trace && decision.trace.length > 0 && (
        <div className="bg-[#1A0533] rounded-2xl border border-purple-800/50 p-4">
          <h3 className="text-sm font-semibold text-purple-200 mb-3">Processing Trace</h3>
          <div className="space-y-2">
            {decision.trace.map((step: any, idx: number) => (
              <div key={idx} className="border border-purple-800/30 rounded-xl">
                <button
                  onClick={() => toggleStep(idx)}
                  className="w-full flex items-center gap-2 p-2 text-left hover:bg-purple-900/30"
                >
                  <span className={`font-mono text-lg ${TRACE_STATUS_COLORS[step.status] || "text-purple-400"}`}>
                    {TRACE_STATUS_ICONS[step.status] || "?"}
                  </span>
                  <span className="text-sm font-medium text-purple-100 flex-1">
                    {step.agent.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                  </span>
                  <span className="text-xs text-purple-400 font-mono">
                    {step.duration_ms.toFixed(0)}ms
                  </span>
                  <span className="text-xs text-purple-400">
                    {expandedSteps.has(idx) ? "▼" : "▶"}
                  </span>
                </button>
                {expandedSteps.has(idx) && (
                  <div className="px-3 pb-3 pt-1 border-t border-purple-800/30">
                    {step.message && (
                      <p className="text-sm text-purple-300 mb-2">{step.message}</p>
                    )}
                    {step.details && (
                      <div className="bg-purple-950/50 rounded-lg p-2 overflow-x-auto">
                        {step.details.checks ? (
                          <div className="space-y-1">
                            {step.details.checks.map((check: any, ci: number) => (
                              <div key={ci} className="flex items-start gap-2 text-xs">
                                <span className={
                                  check.result === "PASS" || check.result === "APPLIED" ? "text-green-600" :
                                  check.result === "FAIL" ? "text-red-600" :
                                  check.result === "PARTIAL" || check.result === "CAPPED" ? "text-yellow-600" :
                                  "text-purple-400"
                                }>
                                  {check.result === "PASS" || check.result === "APPLIED" ? "✓" :
                                   check.result === "FAIL" ? "✗" : "◐"}
                                </span>
                                <span className="font-medium text-purple-200 min-w-[120px]">
                                  {check.check.replace(/_/g, " ")}
                                </span>
                                <span className="text-purple-300">{check.detail}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <pre className="text-xs text-purple-300 whitespace-pre-wrap">
                            {JSON.stringify(step.details, null, 2)}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Claim ID */}
      <p className="text-xs text-purple-500 text-center font-mono">
        Claim ID: {decision.claim_id}
      </p>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import ClaimForm from "./components/ClaimForm";

interface UserSession {
  member_id: string;
  name: string;
  role: string;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("authToken");
  return token ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}

export default function Home() {
  const [user, setUser] = useState<UserSession | null>(null);
  const [loginId, setLoginId] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  // Restore session on load
  useEffect(() => {
    const saved = localStorage.getItem("userSession");
    if (saved) {
      setUser(JSON.parse(saved));
    }
    const lastClaimId = localStorage.getItem("lastClaimId");
    if (lastClaimId) {
      fetch(`${API}/api/claims/${lastClaimId}`, { headers: authHeaders() })
        .then((res) => res.json())
        .then((data) => {
          if (data.claim_id) setResult(data);
          if (data.status === "UNDER_REVIEW") pollForResult(data.claim_id);
        })
        .catch(() => {});
    }
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    try {
      const res = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ member_id: loginId, password: loginPassword }),
      });
      if (!res.ok) {
        setLoginError("Invalid Employee ID or password");
        return;
      }
      const data = await res.json();
      const session: UserSession = {
        member_id: data.user.member_id,
        name: data.user.name,
        role: data.user.role,
      };
      setUser(session);
      localStorage.setItem("userSession", JSON.stringify(session));
      localStorage.setItem("authToken", data.token);
    } catch {
      setLoginError("Connection error");
    }
  };

  const handleLogout = () => {
    setUser(null);
    setResult(null);
    localStorage.removeItem("userSession");
    localStorage.removeItem("lastClaimId");
    localStorage.removeItem("authToken");
  };

  const pollForResult = async (claimId: string) => {
    setPolling(true);
    const maxAttempts = 120;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const res = await fetch(`${API}/api/claims/${claimId}`, { headers: authHeaders() });
        const data = await res.json();
        setResult(data);
        // Stop polling only when we get a final decision (not UNDER_REVIEW or MANUAL_REVIEW)
        if (data.status && data.status !== "UNDER_REVIEW" && data.status !== "MANUAL_REVIEW") {
          setPolling(false);
          return;
        }
      } catch {}
    }
    setPolling(false);
  };

  const handleSubmit = async (claim: any) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/api/claims`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(claim),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
      setLoading(false);

      if (data.claim_id) {
        localStorage.setItem("lastClaimId", data.claim_id);
      }

      if (data.status === "UNDER_REVIEW" || data.status === "MANUAL_REVIEW") {
        pollForResult(data.claim_id);
      }
    } catch (e: any) {
      setError(e.message || "Failed to process claim");
      setLoading(false);
    }
  };

  const [testResults, setTestResults] = useState<any>(null);
  const [runningTests, setRunningTests] = useState(false);

  const runTestSuite = async () => {
    setRunningTests(true);
    setTestResults(null);
    setResult(null);
    setError(null);
    try {
      const res = await fetch(`${API}/api/run-test-suite`, {
        method: "POST",
        headers: authHeaders(),
      });
      if (res.ok) {
        setTestResults(await res.json());
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(`Test suite failed: ${errData.detail || res.status}`);
      }
    } catch (e: any) {
      setError(e.message || "Failed to run test suite");
    }
    setRunningTests(false);
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "APPROVED": return "bg-green-500/20 text-green-300 border-green-500/30";
      case "PARTIAL": return "bg-yellow-500/20 text-yellow-300 border-yellow-500/30";
      case "REJECTED": return "bg-red-500/20 text-red-300 border-red-500/30";
      case "UNDER_REVIEW": return "bg-blue-500/20 text-blue-300 border-blue-500/30";
      case "MANUAL_REVIEW": return "bg-orange-500/20 text-orange-300 border-orange-500/30";
      case "ACTION_REQUIRED": return "bg-amber-500/20 text-amber-300 border-amber-500/30";
      default: return "bg-purple-500/20 text-purple-300 border-purple-500/30";
    }
  };

  // Login screen
  if (!user) {
    return (
      <main className="min-h-screen bg-[#0D0118] flex items-center justify-center">
        <div className="bg-[#130525] rounded-2xl border border-purple-900/40 p-10 w-full max-w-sm">
          <div className="flex items-center gap-3 mb-8">
            <img
              src="https://cdn.prod.website-files.com/63413ad4dec8a91fe53f4fb0/6875d6002f4ee75eaa3bed48_plum%20logo.svg"
              alt="Plum"
              className="h-7"
            />
            <div className="border-l border-purple-700/50 pl-3">
              <p className="text-sm text-purple-100">Member Login</p>
            </div>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm text-purple-300 mb-1.5">Employee ID</label>
              <input
                type="text"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none"
                placeholder="e.g. EMP001"
              />
            </div>
            <div>
              <label className="block text-sm text-purple-300 mb-1.5">Password</label>
              <input
                type="password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none"
                placeholder="••••••••"
              />
            </div>
            {loginError && <p className="text-red-400 text-sm">{loginError}</p>}
            <button
              type="submit"
              className="w-full bg-purple-600 text-white py-2.5 rounded-lg font-medium text-sm hover:bg-purple-500 transition-colors"
            >
              Sign In
            </button>
          </form>

          <p className="text-xs text-purple-600 text-center mt-3">
            Password is your Employee ID in lowercase (e.g. emp001)
          </p>
          <a href="/admin" className="block text-center text-xs text-purple-500 hover:text-purple-300 mt-2">
            Admin Login
          </a>
        </div>
      </main>
    );
  }

  // Main claims page (logged in)
  return (
    <main className="min-h-screen bg-[#0D0118]">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-purple-900/40 px-8 py-5 bg-[#0D0118]/90 backdrop-blur-md">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <img
              src="https://cdn.prod.website-files.com/63413ad4dec8a91fe53f4fb0/6875d6002f4ee75eaa3bed48_plum%20logo.svg"
              alt="Plum"
              className="h-10"
            />
            <div className="border-l border-purple-700/50 pl-4">
              <p className="text-lg text-white font-medium">Claims Portal</p>
              <p className="text-sm text-purple-400">Submit and track your claims</p>
            </div>
          </div>
          <div className="flex items-center gap-5">
            <span className="text-base text-purple-300">
              {user.name} <span className="text-purple-500">({user.member_id})</span>
            </span>
            <button onClick={handleLogout} className="text-base text-purple-500 hover:text-red-400 transition-colors">
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
          {/* Left: Form */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <p className="text-base text-purple-400">Submit a Claim</p>
              <button
                onClick={runTestSuite}
                disabled={runningTests}
                className="text-xs px-3 py-1.5 bg-purple-900/50 text-purple-300 border border-purple-700/40 rounded-lg hover:bg-purple-800/50 disabled:opacity-50 transition-colors"
              >
                {runningTests ? "Running..." : "Run 12 Test Cases"}
              </button>
            </div>
            <ClaimForm onSubmit={handleSubmit} loading={loading} user={user} />
          </div>

          {/* Right: Status / Test Results */}
          <div>
            <p className="text-base text-purple-400 mb-4">{testResults ? "Test Suite Results" : "Claim Status"}</p>

            {/* Test Suite Results */}
            {runningTests && (
              <div className="bg-[#130525] rounded-xl border border-purple-900/40 p-10 text-center">
                <div className="animate-spin h-6 w-6 border-2 border-purple-400 border-t-transparent rounded-full mx-auto mb-3"></div>
                <p className="text-sm text-purple-400">Running all 12 test cases through the LLM pipeline...</p>
              </div>
            )}

            {testResults && !runningTests && (
              <div className="bg-[#130525] rounded-xl border border-purple-900/40 p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-green-400 font-medium text-sm">{testResults.passed}/{testResults.total} passed</span>
                  <button onClick={() => setTestResults(null)} className="text-xs text-purple-500 hover:text-purple-300">Clear</button>
                </div>
                <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
                  {testResults.results.map((r: any) => (
                    <details key={r.case_id} className="border border-purple-900/30 rounded-lg bg-[#0a0215]">
                      <summary className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-purple-900/20 text-sm">
                        <span className={r.matched ? "text-green-400" : "text-red-400"}>
                          {r.matched ? "✓" : "✗"}
                        </span>
                        <span className="text-purple-200 flex-1">{r.case_id}: {r.case_name}</span>
                        <span className="text-xs text-purple-500">{r.actual_decision}</span>
                      </summary>
                      <div className="px-3 pb-3 text-xs space-y-1">
                        <p className="text-purple-400">Expected: {r.expected_decision || "N/A"} | Got: <span className={r.matched ? "text-green-300" : "text-red-300"}>{r.actual_decision}</span> | Confidence: {(r.confidence * 100).toFixed(0)}%</p>
                        <p className="text-purple-300">{r.summary}</p>
                        {r.trace?.map((step: any, idx: number) => (
                          <p key={idx} className="text-purple-500">
                            <span className={step.status === "PASS" || step.status === "COMPLETE" ? "text-green-500" : step.status === "FAIL" || step.status === "STOP" ? "text-red-500" : "text-orange-500"}>
                              {step.status === "PASS" || step.status === "COMPLETE" ? "✓" : step.status === "FAIL" || step.status === "STOP" ? "✗" : "◐"}
                            </span>{" "}{step.agent}: {step.message?.substring(0, 100)}
                          </p>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            )}

            {/* Normal claim status (hidden when test results showing) */}
            {!testResults && !runningTests && (<>
            <p className="text-base text-purple-400 mb-4"></p>

            {loading && (
              <div className="bg-[#130525] rounded-xl border border-purple-900/40 p-10 text-center">
                <div className="animate-spin h-6 w-6 border-2 border-purple-400 border-t-transparent rounded-full mx-auto mb-3"></div>
                <p className="text-sm text-purple-400">Submitting...</p>
              </div>
            )}

            {error && (
              <div className="bg-red-950/30 border border-red-900/40 rounded-xl p-5">
                <p className="text-red-300 font-medium">Error</p>
                <p className="text-red-400/80 text-sm mt-1">{error}</p>
              </div>
            )}

            {result && (
              <div className="bg-[#130525] rounded-xl border border-purple-900/40 p-6 space-y-4">
                <div className={`inline-flex items-center px-4 py-2 rounded-full text-sm font-semibold border ${statusColor(result.status)}`}>
                  {(result.status === "UNDER_REVIEW" && polling) && (
                    <div className="animate-spin h-3 w-3 border-2 border-current border-t-transparent rounded-full mr-2"></div>
                  )}
                  {result.status === "UNDER_REVIEW" ? "Under Review" :
                   result.status === "APPROVED" ? "Approved" :
                   result.status === "PARTIAL" ? "Partially Approved" :
                   result.status === "REJECTED" ? "Rejected" :
                   result.status === "MANUAL_REVIEW" ? "Sent for Manual Review" :
                   result.status === "ACTION_REQUIRED" ? "Action Required" :
                   result.status}
                </div>

                <p className="text-xs text-purple-500 font-mono">Claim ID: {result.claim_id}</p>

                {result.approved_amount != null && (
                  <div className="flex gap-6">
                    <div>
                      <p className="text-xs text-purple-500">Claimed</p>
                      <p className="text-lg text-purple-100 font-semibold">₹{result.claimed_amount?.toLocaleString("en-IN")}</p>
                    </div>
                    <div>
                      <p className="text-xs text-purple-500">Approved</p>
                      <p className="text-lg text-green-300 font-semibold">₹{result.approved_amount?.toLocaleString("en-IN")}</p>
                    </div>
                  </div>
                )}

                {result.error_message ? (
                  <div className="bg-purple-950/50 rounded-lg border border-purple-700/30 p-4">
                    <p className="text-xs text-purple-400 font-medium mb-1">What to do:</p>
                    <p className="text-sm text-purple-200">{result.error_message}</p>
                  </div>
                ) : (
                  <p className="text-sm text-purple-200">{result.summary}</p>
                )}

                {polling && (
                  <p className="text-xs text-blue-400 animate-pulse">Processing your claim... this usually takes a few seconds.</p>
                )}
              </div>
            )}

            {!loading && !error && !result && (
              <div className="bg-[#130525] rounded-xl border border-purple-900/40 p-10 text-center">
                <div className="text-purple-700 mb-2">
                  <svg className="mx-auto h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <p className="text-sm text-purple-500">Submit a claim to see its status here</p>
              </div>
            )}
            </>)}
          </div>
        </div>
      </div>
    </main>
  );
}

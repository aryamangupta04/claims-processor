"use client";

import { useState, useEffect } from "react";

interface Claim {
  claim_id: string;
  member_id: string;
  member_name: string;
  status: string;
  claim_category: string;
  claimed_amount: number;
  approved_amount: number | null;
  confidence: number | null;
  created_at: string;
}

export default function AdminPage() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [claims, setClaims] = useState<Claim[]>([]);
  const [selectedClaim, setSelectedClaim] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const [token, setToken] = useState("");
  const authHeader = token ? `Bearer ${token}` : "Basic " + btoa(`${username}:${password}`);

  useEffect(() => {
    const saved = localStorage.getItem("adminSession");
    if (saved) {
      const { username: u, token: t } = JSON.parse(saved);
      if (t) {
        setUsername(u);
        setToken(t);
        setLoggedIn(true);
        loadDashboardWithAuth(`Bearer ${t}`);
      }
    }
  }, []);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (res.ok) {
        const data = await res.json();
        const t = data.token || "";
        setToken(t);
        setLoggedIn(true);
        localStorage.setItem("adminSession", JSON.stringify({ username, token: t }));
        loadDashboard();
      } else {
        setLoginError("Invalid username or password");
      }
    } catch {
      setLoginError("Connection error");
    }
  };

  const loadDashboardWithAuth = async (auth: string) => {
    setLoading(true);
    try {
      const [claimsRes, statsRes] = await Promise.all([
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/claims`, { headers: { Authorization: auth } }),
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/stats`, { headers: { Authorization: auth } }),
      ]);
      if (claimsRes.ok) setClaims((await claimsRes.json()).claims || []);
      if (statsRes.ok) setStats(await statsRes.json());
    } catch {}
    setLoading(false);
  };

  const loadDashboard = async () => { await loadDashboardWithAuth(authHeader); };

  const handleLogout = () => {
    setLoggedIn(false);
    setUsername("");
    setPassword("");
    localStorage.removeItem("adminSession");
  };

  const loadClaimDetail = async (claimId: string) => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/claims/${claimId}`, {
        headers: { Authorization: authHeader },
      });
      if (res.ok) setSelectedClaim(await res.json());
    } catch {}
  };

  const handleOverride = async (claimId: string, newStatus: string) => {
    const reason = prompt("Reason for override:");
    if (!reason) return;
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/admin/claims/${claimId}/override`, {
        method: "POST",
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus, reason }),
      });
      loadDashboard();
      setSelectedClaim(null);
    } catch {}
  };

  useEffect(() => {
    if (loggedIn) {
      const interval = setInterval(loadDashboard, 5000);
      return () => clearInterval(interval);
    }
  }, [loggedIn]);

  const statusBadge = (status: string) => {
    const map: Record<string, string> = {
      APPROVED: "text-green-400 bg-green-400/10",
      PARTIAL: "text-yellow-400 bg-yellow-400/10",
      REJECTED: "text-red-400 bg-red-400/10",
      UNDER_REVIEW: "text-blue-400 bg-blue-400/10",
      MANUAL_REVIEW: "text-orange-400 bg-orange-400/10",
      ACTION_REQUIRED: "text-amber-400 bg-amber-400/10",
    };
    return map[status] || "text-purple-400 bg-purple-400/10";
  };

  if (!loggedIn) {
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
              <p className="text-sm text-purple-100">Admin Login</p>
            </div>
          </div>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm text-purple-300 mb-1.5">Username</label>
              <input
                type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none"
                placeholder="admin"
              />
            </div>
            <div>
              <label className="block text-sm text-purple-300 mb-1.5">Password</label>
              <input
                type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none"
                placeholder="••••••••"
              />
            </div>
            {loginError && <p className="text-red-400 text-sm">{loginError}</p>}
            <button type="submit" className="w-full bg-purple-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-purple-500 transition-colors">
              Sign in
            </button>
          </form>
          <a href="/" className="block text-center text-xs text-purple-500 hover:text-purple-300 mt-4">Back to Member Portal</a>
        </div>
      </main>
    );
  }

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
              <p className="text-lg text-white font-medium">Admin Dashboard</p>
              <p className="text-sm text-purple-400">Claims Operations</p>
            </div>
          </div>
          <div className="flex items-center gap-5">
            <span className="text-base text-purple-300">Logged in as <span className="text-white font-medium">{username}</span></span>
            <button onClick={handleLogout} className="text-base text-purple-500 hover:text-red-400 transition-colors">Logout</button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-8 py-8">
        {/* Stats row */}
        {stats && (
          <div className="flex gap-10 mb-8 text-base">
            <span className="text-purple-300">Total <span className="text-white font-semibold ml-1">{stats.total}</span></span>
            <span className="text-purple-300">Approved <span className="text-green-400 font-semibold ml-1">{stats.approved}</span></span>
            <span className="text-purple-300">Rejected <span className="text-red-400 font-semibold ml-1">{stats.rejected}</span></span>
            <span className="text-purple-300">Pending <span className="text-blue-400 font-semibold ml-1">{stats.pending}</span></span>
            <span className="text-purple-300">Manual Review <span className="text-orange-400 font-semibold ml-1">{stats.manual_review}</span></span>
          </div>
        )}

        <div className="flex gap-5">
          {/* Claims table */}
          <div className="w-[400px] shrink-0">
            <div className="border border-purple-900/30 rounded-lg overflow-hidden bg-[#0a0215]">
              <div className="px-5 py-4 border-b border-purple-900/30 text-base text-purple-400">
                Claims ({claims.length})
              </div>
              {claims.length === 0 ? (
                <p className="p-8 text-center text-purple-500 text-base">No claims yet</p>
              ) : (
                <div className="max-h-[calc(100vh-220px)] overflow-y-auto divide-y divide-purple-900/20">
                  {claims.map((claim) => (
                    <button
                      key={claim.claim_id}
                      onClick={() => loadClaimDetail(claim.claim_id)}
                      className={`w-full text-left px-5 py-4 hover:bg-purple-900/20 transition-colors ${
                        selectedClaim?.claim_id === claim.claim_id ? "bg-purple-900/20" : ""
                      }`}
                    >
                      <div className="flex justify-between items-center">
                        <div>
                          <p className="text-purple-100 text-base font-medium">{claim.member_name || claim.member_id}</p>
                          <p className="text-sm text-purple-500 mt-1">{claim.claim_category} · ₹{claim.claimed_amount?.toLocaleString()}</p>
                        </div>
                        <span className={`text-sm px-2.5 py-1 rounded ${statusBadge(claim.status)}`}>
                          {claim.status}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Detail panel */}
          <div className="flex-1 min-w-0">
            {selectedClaim ? (
              <div className="border border-purple-900/30 rounded-lg bg-[#0a0215] p-8 max-h-[calc(100vh-180px)] overflow-y-auto">
                {/* Header */}
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <p className="text-purple-100 text-xl font-medium">{selectedClaim.claim_id}</p>
                    <p className="text-purple-400 text-base mt-1">{selectedClaim.summary}</p>
                  </div>
                  <span className={`text-base px-3 py-1.5 rounded ${statusBadge(selectedClaim.status)}`}>
                    {selectedClaim.status}
                  </span>
                </div>

                {/* Amounts */}
                <div className="flex gap-12 mb-6">
                  <div>
                    <span className="text-base text-purple-500">Claimed</span>
                    <p className="text-purple-100 text-xl mt-1">₹{selectedClaim.claimed_amount?.toLocaleString()}</p>
                  </div>
                  <div>
                    <span className="text-base text-purple-500">Approved</span>
                    <p className="text-green-300 text-xl mt-1">
                      {selectedClaim.approved_amount != null ? `₹${selectedClaim.approved_amount.toLocaleString()}` : "—"}
                    </p>
                  </div>
                  {selectedClaim.status !== "ACTION_REQUIRED" && selectedClaim.status !== "MANUAL_REVIEW" && (
                    <div>
                      <span className="text-base text-purple-500">Confidence</span>
                      <p className="text-purple-100 text-xl mt-1">
                        {selectedClaim.confidence != null ? `${(selectedClaim.confidence * 100).toFixed(0)}%` : "—"}
                      </p>
                    </div>
                  )}
                </div>

                {/* Override */}
                {(selectedClaim.status === "MANUAL_REVIEW" || selectedClaim.status === "UNDER_REVIEW") && (
                  <div className="flex gap-3 mb-6">
                    <button onClick={() => handleOverride(selectedClaim.claim_id, "APPROVED")}
                      className="px-5 py-2.5 text-base text-green-400 border border-green-800/40 rounded-lg hover:bg-green-900/20">
                      Approve
                    </button>
                    <button onClick={() => handleOverride(selectedClaim.claim_id, "REJECTED")}
                      className="px-5 py-2.5 text-base text-red-400 border border-red-800/40 rounded-lg hover:bg-red-900/20">
                      Reject
                    </button>
                  </div>
                )}

                {/* Rejection reasons */}
                {selectedClaim.rejection_reasons?.length > 0 && (
                  <div className="mb-6">
                    <p className="text-base text-purple-500 mb-2">Rejection reasons</p>
                    {selectedClaim.rejection_reasons.map((r: string, i: number) => (
                      <p key={i} className="text-base text-red-300">· {r}</p>
                    ))}
                  </div>
                )}

                {/* Deductions */}
                {selectedClaim.deductions?.length > 0 && (
                  <div className="mb-6">
                    <p className="text-base text-purple-500 mb-2">Deductions</p>
                    {selectedClaim.deductions.map((d: any, i: number) => (
                      <p key={i} className="text-base text-purple-300">· {d.detail}</p>
                    ))}
                  </div>
                )}

                {/* Trace */}
                {selectedClaim.trace?.length > 0 && (
                  <div>
                    <p className="text-base text-purple-500 mb-3">Processing trace</p>
                    <div className="space-y-2">
                      {selectedClaim.trace.map((step: any, idx: number) => (
                        <details key={idx} className="group">
                          <summary className="flex items-center gap-3 cursor-pointer text-base py-2.5 px-4 rounded-lg hover:bg-purple-900/20">
                            <span className={
                              step.status === "PASS" || step.status === "COMPLETE" ? "text-green-400" :
                              step.status === "FAIL" || step.status === "STOP" ? "text-red-400" :
                              step.status === "ERROR" ? "text-orange-400" : "text-purple-400"
                            }>
                              {step.status === "PASS" || step.status === "COMPLETE" ? "✓" :
                               step.status === "FAIL" || step.status === "STOP" ? "✗" :
                               step.status === "ERROR" ? "!" : "○"}
                            </span>
                            <span className="text-purple-200">{step.agent?.replace(/_/g, " ")}</span>
                            <span className="text-purple-600 ml-auto">{step.duration_ms?.toFixed(0)}ms</span>
                          </summary>
                          <div className="ml-8 mt-2 mb-4 text-base text-purple-400">
                            <p>{step.message}</p>
                            {step.details?.checks && (
                              <div className="mt-2 space-y-1.5 text-sm">
                                {step.details.checks.map((c: any, ci: number) => (
                                  <p key={ci} className="text-purple-400">
                                    <span className={c.result === "PASS" || c.result === "APPLIED" ? "text-green-500" : c.result === "FAIL" ? "text-red-500" : "text-yellow-500"}>
                                      {c.result}
                                    </span>{" "}
                                    {c.check?.replace(/_/g, " ")}: {c.detail}
                                  </p>
                                ))}
                              </div>
                            )}
                            {step.details && !step.details.checks && (
                              <pre className="mt-2 text-sm text-purple-600 overflow-x-auto whitespace-pre-wrap">
                                {JSON.stringify(step.details, null, 2)}
                              </pre>
                            )}
                          </div>
                        </details>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="border border-purple-900/30 rounded-lg bg-[#0a0215] p-12 text-center">
                <p className="text-sm text-purple-500">Select a claim to view details</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

"use client";

import { useState, useRef } from "react";

const CATEGORIES = [
  "CONSULTATION",
  "DIAGNOSTIC",
  "PHARMACY",
  "DENTAL",
  "VISION",
  "ALTERNATIVE_MEDICINE",
];

const HOSPITALS = [
  "Apollo Hospitals",
  "Fortis Healthcare",
  "Max Healthcare",
  "Manipal Hospitals",
  "Narayana Health",
  "Medanta",
  "Kokilaben Dhirubhai Ambani Hospital",
  "Aster CMI Hospital",
  "Columbia Asia",
  "Sakra World Hospital",
  "Other",
];


const DOC_TYPES = [
  "PRESCRIPTION",
  "HOSPITAL_BILL",
  "LAB_REPORT",
  "PHARMACY_BILL",
  "DIAGNOSTIC_REPORT",
  "DISCHARGE_SUMMARY",
  "DENTAL_REPORT",
];

interface UploadedDoc {
  file: File;
  preview: string;
  name: string;
  docType: string;
}

interface Props {
  onSubmit: (claim: any) => void;
  loading: boolean;
  user?: { member_id: string; name: string } | null;
}

export default function ClaimForm({ onSubmit, loading, user }: Props) {
  const [memberName, setMemberName] = useState(user?.name || "");
  const [memberId, setMemberId] = useState(user?.member_id || "");
  const [category, setCategory] = useState("CONSULTATION");
  const [treatmentDate, setTreatmentDate] = useState("2024-11-01");
  const [amount, setAmount] = useState("1500");
  const [hospitalName, setHospitalName] = useState("");
  const [otherHospital, setOtherHospital] = useState("");
  const [documents, setDocuments] = useState<UploadedDoc[]>([]);
  const [simulateFailure, setSimulateFailure] = useState(false);
  const [jsonMode, setJsonMode] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    const newDocs: UploadedDoc[] = [];
    Array.from(files).forEach((file) => {
      const preview = URL.createObjectURL(file);
      const guessedType = guessDocType(file.name);
      newDocs.push({ file, preview, name: file.name, docType: guessedType });
    });
    setDocuments([...documents, ...newDocs]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const updateDocType = (idx: number, docType: string) => {
    const updated = [...documents];
    updated[idx].docType = docType;
    setDocuments(updated);
  };

  const removeDocument = (idx: number) => {
    const updated = [...documents];
    URL.revokeObjectURL(updated[idx].preview);
    updated.splice(idx, 1);
    setDocuments(updated);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (jsonMode) {
      try {
        const parsed = JSON.parse(rawJson);
        onSubmit(parsed);
      } catch {
        alert("Invalid JSON");
      }
      return;
    }

    if (documents.length === 0) {
      alert("Please upload at least one document");
      return;
    }

    // Convert files to base64 and send to backend
    const docs = await Promise.all(
      documents.map(async (d, idx) => {
        const base64 = await fileToBase64(d.file);
        return {
          file_id: `F${String(idx + 1).padStart(3, "0")}`,
          file_name: d.name,
          actual_type: d.docType,
          file_data: base64,
          mime_type: d.file.type,
        };
      })
    );

    const claim: any = {
      member_id: user?.member_id || memberId || undefined,
      member_name: user?.name || memberName || undefined,
      policy_id: "PLUM_GHI_2024",
      claim_category: category,
      treatment_date: treatmentDate,
      claimed_amount: parseFloat(amount),
      documents: docs,
      simulate_component_failure: simulateFailure,
    };

    const finalHospital = hospitalName === "Other" ? otherHospital : hospitalName;
    if (finalHospital) claim.hospital_name = finalHospital;

    onSubmit(claim);
  };

  return (
    <form onSubmit={handleSubmit} className="bg-[#130525] rounded-xl border border-purple-900/40 p-6 space-y-4">
      <div className="flex items-center justify-end">
        <label className="flex items-center gap-1.5 text-xs text-purple-500 cursor-pointer hover:text-purple-300 transition-colors">
          <input
            type="checkbox"
            checked={jsonMode}
            onChange={(e) => setJsonMode(e.target.checked)}
            className="rounded border-purple-700 bg-purple-950 h-3 w-3"
          />
          JSON mode
        </label>
      </div>

      {jsonMode ? (
        <div>
          <label className="block text-sm text-purple-300/80 mb-1">
            Paste full claim JSON
          </label>
          <textarea
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            rows={15}
            className="w-full border border-purple-700/50 bg-purple-950/50 text-purple-100 rounded-xl px-3 py-2 text-sm font-mono placeholder-purple-500"
            placeholder='{"member_id": "EMP001", "claim_category": "CONSULTATION", ...}'
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-5">
            <div>
              <label className="block text-sm text-purple-300/80 mb-1">Full Name</label>
              <input
                type="text"
                value={user?.name || memberName}
                onChange={(e) => !user && setMemberName(e.target.value)}
                placeholder="e.g. Rajesh Kumar"
                readOnly={!!user}
                className={`w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors ${user ? "opacity-70 cursor-not-allowed" : ""}`}
                required
              />
            </div>
            <div>
              <label className="block text-sm text-purple-300/80 mb-1">Employee ID</label>
              <input
                type="text"
                value={user?.member_id || memberId}
                onChange={(e) => !user && setMemberId(e.target.value)}
                placeholder="e.g. EMP001"
                readOnly={!!user}
                className={`w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors ${user ? "opacity-70 cursor-not-allowed" : ""}`}
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm text-purple-300/80 mb-1">Claim Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-5">
            <div>
              <label className="block text-sm text-purple-300/80 mb-1">Treatment Date</label>
              <input
                type="date"
                value={treatmentDate}
                onChange={(e) => setTreatmentDate(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors"
              />
            </div>
            <div>
              <label className="block text-sm text-purple-300/80 mb-1">Amount (INR)</label>
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm text-purple-300/80 mb-1">Hospital / Clinic</label>
            <select
              value={hospitalName}
              onChange={(e) => setHospitalName(e.target.value)}
              className="w-full border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm focus:border-purple-500 focus:outline-none transition-colors"
              required
            >
              <option value="">Select hospital</option>
              {HOSPITALS.map((h) => (
                <option key={h} value={h}>
                  {h}{h !== "Other" ? " (Network)" : ""}
                </option>
              ))}
            </select>
            {hospitalName === "Other" && (
              <input
                type="text"
                value={otherHospital}
                onChange={(e) => setOtherHospital(e.target.value)}
                placeholder="Enter hospital/clinic name"
                className="w-full mt-2 border border-purple-800/40 bg-[#0D0118] text-purple-100 rounded-lg px-3.5 py-2.5 text-sm placeholder-purple-600 focus:border-purple-500 focus:outline-none transition-colors"
                required
              />
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-purple-200 mb-2">
              Upload Documents
            </label>

            {/* Upload area */}
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border border-dashed border-purple-700/40 rounded-lg p-6 text-center cursor-pointer hover:border-purple-500 hover:bg-purple-900/20 transition-all"
            >
              <svg className="mx-auto h-8 w-8 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              <p className="mt-2 text-sm text-purple-300">
                Upload prescriptions, bills, or lab reports
              </p>
              <p className="text-xs text-purple-500 mt-0.5">
                JPG, PNG, PDF
              </p>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.pdf"
              onChange={handleFileUpload}
              className="hidden"
            />

            {/* Uploaded files list */}
            {documents.length > 0 && (
              <div className="mt-3 space-y-2">
                {documents.map((doc, idx) => (
                  <div key={idx} className="flex items-center gap-4 p-4 bg-purple-950/30 rounded-xl border border-purple-800/30">
                    {doc.file.type.startsWith("image/") ? (
                      <img
                        src={doc.preview}
                        alt={doc.name}
                        className="h-12 w-12 object-cover rounded"
                      />
                    ) : (
                      <div className="h-12 w-12 bg-red-100 rounded flex items-center justify-center">
                        <span className="text-xs font-bold text-red-600">PDF</span>
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-purple-100 truncate">{doc.name}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <select
                          value={doc.docType}
                          onChange={(e) => updateDocType(idx, e.target.value)}
                          className="border border-purple-700/50 bg-purple-950/50 text-purple-100 rounded-lg px-2 py-0.5 text-xs"
                        >
                          {DOC_TYPES.map((t) => (
                            <option key={t} value={t}>
                              {t.replace(/_/g, " ")}
                            </option>
                          ))}
                        </select>
                        <span className="text-xs text-purple-400">
                          {(doc.file.size / 1024).toFixed(0)} KB
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeDocument(idx)}
                      className="text-red-500 hover:text-red-700 text-sm"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <label className="flex items-center gap-2 text-sm text-purple-300">
            <input
              type="checkbox"
              checked={simulateFailure}
              onChange={(e) => setSimulateFailure(e.target.checked)}
              className="rounded border-purple-600 bg-purple-900/50"
            />
            Simulate component failure (TC011)
          </label>
        </>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-purple-600 text-white py-3 px-5 rounded-lg hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm transition-all mt-3"
      >
        {loading ? "Processing..." : "Submit Claim"}
      </button>
    </form>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(",")[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function guessDocType(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.includes("prescription") || lower.includes("rx")) return "PRESCRIPTION";
  if (lower.includes("bill") || lower.includes("invoice") || lower.includes("receipt")) return "HOSPITAL_BILL";
  if (lower.includes("lab") || lower.includes("report") || lower.includes("test")) return "LAB_REPORT";
  if (lower.includes("pharmacy") || lower.includes("chemist")) return "PHARMACY_BILL";
  if (lower.includes("mri") || lower.includes("xray") || lower.includes("scan")) return "DIAGNOSTIC_REPORT";
  if (lower.includes("discharge")) return "DISCHARGE_SUMMARY";
  if (lower.includes("dental")) return "DENTAL_REPORT";
  return "HOSPITAL_BILL";
}

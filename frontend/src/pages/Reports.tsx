import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ReportJob, type ReportJobCreate } from "../api/client";

/* ── Status badge ─────────────────────────────────────────────────── */
function StatusBadge({ status }: { status: string }) {
  const color: Record<string, string> = {
    pending: "bg-yellow-500/20 text-yellow-400",
    running: "bg-blue-500/20 text-blue-400 animate-pulse",
    completed: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
  };
  return (
    <span
      className={`severity-badge ${color[status] ?? "bg-gray-500/20 text-gray-400"}`}
    >
      {status}
    </span>
  );
}

/* ── Create form ──────────────────────────────────────────────────── */
function ReportForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<ReportJobCreate>({
    region_code: "EU",
    format: "pdf",
  });

  const create = useMutation({
    mutationFn: () => api.createReport(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      onClose();
    },
  });

  return (
    <div className="glass-panel p-5 mb-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">
        Generate Intelligence Brief
      </h3>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <label className="space-y-1">
          <span className="text-gray-400">Region Code</span>
          <input
            className="input-field"
            value={form.region_code}
            onChange={(e) => setForm({ ...form, region_code: e.target.value })}
          />
        </label>
        <label className="space-y-1">
          <span className="text-gray-400">Format</span>
          <select
            className="input-field"
            value={form.format}
            onChange={(e) => setForm({ ...form, format: e.target.value })}
          >
            <option value="pdf">PDF</option>
            <option value="html">HTML</option>
          </select>
        </label>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button onClick={onClose} className="btn-secondary">
          Cancel
        </button>
        <button
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="btn-primary"
        >
          {create.isPending ? "Submitting…" : "Generate Report"}
        </button>
      </div>
      {create.isError && (
        <p className="text-xs text-red-400 mt-2">
          {(create.error as Error).message}
        </p>
      )}
    </div>
  );
}

/* ── Report row ───────────────────────────────────────────────────── */
function ReportRow({ report }: { report: ReportJob }) {
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
      <td className="px-4 py-3 text-sm font-mono text-blue-300">
        {report.region_code}
      </td>
      <td className="px-4 py-3 text-sm uppercase">{report.format}</td>
      <td className="px-4 py-3">
        <StatusBadge status={report.status} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {new Date(report.created_at).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {report.completed_at
          ? new Date(report.completed_at).toLocaleString()
          : "—"}
      </td>
      <td className="px-4 py-3">
        {report.status === "completed" && report.s3_key ? (
          <a
            href={api.downloadReportUrl(report.id)}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-blue-400 hover:text-blue-300 transition"
          >
            Download ↓
          </a>
        ) : report.error ? (
          <span className="text-xs text-red-400" title={report.error}>
            Error
          </span>
        ) : (
          <span className="text-xs text-gray-600">—</span>
        )}
      </td>
    </tr>
  );
}

/* ── Main Reports page ────────────────────────────────────────────── */
export default function ReportsPage() {
  const [showForm, setShowForm] = useState(false);

  const reports = useQuery({
    queryKey: ["reports"],
    queryFn: () => api.listReports(50),
    refetchInterval: 10_000, // poll while generating
  });

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Intelligence Reports</h2>
          <p className="text-sm text-gray-400 mt-0.5">
            Automated PDF/HTML intelligence briefs per region
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="btn-primary"
        >
          + New Report
        </button>
      </div>

      {showForm && <ReportForm onClose={() => setShowForm(false)} />}

      <div className="glass-panel overflow-hidden">
        <table className="w-full text-left">
          <thead className="border-b border-slate-700/60">
            <tr className="text-xs uppercase tracking-wider text-gray-500">
              <th className="px-4 py-3">Region</th>
              <th className="px-4 py-3">Format</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Completed</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {reports.isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {reports.data?.map((r) => <ReportRow key={r.id} report={r} />)}
            {reports.data?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No reports generated yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

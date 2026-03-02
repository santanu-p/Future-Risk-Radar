import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type DriftSnapshot, type ModelHealthSummary } from "../api/client";

/* ── Health summary cards ─────────────────────────────────────────── */
function HealthCards({ data }: { data: ModelHealthSummary }) {
  const rate = (data.alert_rate * 100).toFixed(1);
  const rateColor =
    data.alert_rate > 0.25
      ? "text-red-400"
      : data.alert_rate > 0.1
        ? "text-yellow-400"
        : "text-green-400";

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="glass-panel p-4">
        <div className="text-xs uppercase tracking-wider text-gray-500">
          Checks (7d)
        </div>
        <div className="text-2xl font-bold mt-1">{data.total_checks_7d}</div>
      </div>
      <div className="glass-panel p-4">
        <div className="text-xs uppercase tracking-wider text-gray-500">
          Drift Alerts (7d)
        </div>
        <div className="text-2xl font-bold mt-1 text-red-400">
          {data.alerts_7d}
        </div>
      </div>
      <div className="glass-panel p-4">
        <div className="text-xs uppercase tracking-wider text-gray-500">
          Alert Rate
        </div>
        <div className={`text-2xl font-bold mt-1 ${rateColor}`}>{rate}%</div>
      </div>
    </div>
  );
}

/* ── Drift type breakdown ─────────────────────────────────────────── */
function TypeBreakdown({
  byType,
}: {
  byType: ModelHealthSummary["by_type"];
}) {
  return (
    <div className="glass-panel p-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">
        By Drift Type
      </h3>
      <div className="space-y-2">
        {Object.entries(byType).map(([type, { total, alerts }]) => {
          const pct = total > 0 ? (alerts / total) * 100 : 0;
          return (
            <div key={type} className="flex items-center gap-3 text-sm">
              <span className="w-28 text-gray-400 font-mono">{type}</span>
              <div className="flex-1 h-2 rounded-full bg-slate-700 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-orange-500 to-red-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-gray-500 w-20 text-right">
                {alerts}/{total}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Detail modal ─────────────────────────────────────────────────── */
function SnapshotDetail({
  snap,
  onClose,
}: {
  snap: DriftSnapshot;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6">
      <div className="glass-panel max-w-lg w-full p-6 space-y-3 max-h-[80vh] overflow-auto">
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold">Drift Snapshot</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-white">
            ✕
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="text-gray-400">Type</div>
          <div className="font-mono">{snap.drift_type}</div>
          <div className="text-gray-400">Region</div>
          <div className="font-mono">{snap.region_code ?? "—"}</div>
          <div className="text-gray-400">Layer</div>
          <div className="font-mono">{snap.layer ?? "—"}</div>
          <div className="text-gray-400">PSI</div>
          <div className="font-mono">
            {snap.psi !== null ? snap.psi.toFixed(4) : "—"}
          </div>
          <div className="text-gray-400">KS Stat</div>
          <div className="font-mono">
            {snap.ks_stat !== null ? snap.ks_stat.toFixed(4) : "—"}
          </div>
          <div className="text-gray-400">JS Divergence</div>
          <div className="font-mono">
            {snap.js_divergence !== null
              ? snap.js_divergence.toFixed(4)
              : "—"}
          </div>
          <div className="text-gray-400">Alert</div>
          <div>
            <span
              className={`severity-badge ${snap.alert ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"}`}
            >
              {snap.alert ? "ALERT" : "OK"}
            </span>
          </div>
          <div className="text-gray-400">Checked At</div>
          <div>{new Date(snap.checked_at).toLocaleString()}</div>
        </div>
        {Object.keys(snap.details).length > 0 && (
          <div>
            <div className="text-xs text-gray-400 mb-1">Raw Details</div>
            <pre className="text-xs bg-slate-900 rounded p-3 overflow-auto max-h-48 text-gray-300">
              {JSON.stringify(snap.details, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Main ─────────────────────────────────────────────────────────── */
export default function DriftDashboard() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<string>("all");
  const [alertOnly, setAlertOnly] = useState(false);
  const [selected, setSelected] = useState<DriftSnapshot | null>(null);

  const health = useQuery({
    queryKey: ["modelHealth"],
    queryFn: api.modelHealth,
  });

  const snapshots = useQuery({
    queryKey: ["driftSnapshots", filter, alertOnly],
    queryFn: () =>
      api.listDriftSnapshots(
        100,
        0,
        filter !== "all" ? filter : undefined,
        alertOnly || undefined,
      ),
  });

  const triggerCheck = useMutation({
    mutationFn: api.triggerDriftCheck,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["driftSnapshots"] });
      qc.invalidateQueries({ queryKey: ["modelHealth"] });
    },
  });

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Model Monitoring</h2>
          <p className="text-sm text-gray-400 mt-0.5">
            Data drift, prediction drift & feature importance tracking
          </p>
        </div>
        <button
          onClick={() => triggerCheck.mutate()}
          disabled={triggerCheck.isPending}
          className="btn-primary"
        >
          {triggerCheck.isPending ? "Running…" : "Run Drift Check"}
        </button>
      </div>

      {health.data && (
        <>
          <HealthCards data={health.data} />
          <TypeBreakdown byType={health.data.by_type} />
        </>
      )}

      {/* Filters */}
      <div className="flex gap-2 items-center">
        <span className="text-xs text-gray-400">Filter:</span>
        {["all", "data", "prediction", "feature"].map((t) => (
          <button
            key={t}
            onClick={() => setFilter(t)}
            className={`text-xs rounded-full px-3 py-1 transition ${
              filter === t
                ? "bg-blue-500/30 text-blue-300"
                : "bg-slate-700/50 text-gray-500"
            }`}
          >
            {t}
          </button>
        ))}
        <label className="flex items-center gap-1 ml-4 text-xs text-gray-400">
          <input
            type="checkbox"
            checked={alertOnly}
            onChange={(e) => setAlertOnly(e.target.checked)}
            className="rounded border-slate-600"
          />
          Alerts only
        </label>
      </div>

      {/* Table */}
      <div className="glass-panel overflow-hidden">
        <table className="w-full text-left">
          <thead className="border-b border-slate-700/60">
            <tr className="text-xs uppercase tracking-wider text-gray-500">
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Region</th>
              <th className="px-4 py-3">Layer</th>
              <th className="px-4 py-3">PSI</th>
              <th className="px-4 py-3">KS</th>
              <th className="px-4 py-3">JS</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">When</th>
            </tr>
          </thead>
          <tbody>
            {snapshots.isLoading && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                  Loading…
                </td>
              </tr>
            )}
            {snapshots.data?.map((s) => (
              <tr
                key={s.id}
                onClick={() => setSelected(s)}
                className="border-b border-slate-700/40 hover:bg-slate-800/40 transition cursor-pointer"
              >
                <td className="px-4 py-2 text-sm font-mono">{s.drift_type}</td>
                <td className="px-4 py-2 text-sm font-mono text-blue-300">
                  {s.region_code ?? "—"}
                </td>
                <td className="px-4 py-2 text-sm">{s.layer ?? "—"}</td>
                <td className="px-4 py-2 text-sm font-mono">
                  {s.psi?.toFixed(3) ?? "—"}
                </td>
                <td className="px-4 py-2 text-sm font-mono">
                  {s.ks_stat?.toFixed(3) ?? "—"}
                </td>
                <td className="px-4 py-2 text-sm font-mono">
                  {s.js_divergence?.toFixed(3) ?? "—"}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`severity-badge text-xs ${
                      s.alert
                        ? "bg-red-500/20 text-red-400"
                        : "bg-green-500/20 text-green-400"
                    }`}
                  >
                    {s.alert ? "ALERT" : "OK"}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-gray-500">
                  {new Date(s.checked_at).toLocaleString()}
                </td>
              </tr>
            ))}
            {snapshots.data?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                  No drift snapshots yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <SnapshotDetail snap={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

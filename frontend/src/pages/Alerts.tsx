import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AlertRule,
  type AlertRuleCreate,
  type AlertHistory,
} from "../api/client";

/* ── Metrics & operators for the form ─────────────────────────────── */
const METRICS = ["cesi_score", "crisis_probability"] as const;
const OPERATORS = [
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
] as const;
const CHANNELS = ["email", "slack", "webhook", "websocket"] as const;

/* ── Alert Rule form ──────────────────────────────────────────────── */
function AlertRuleForm({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<AlertRuleCreate>({
    region_code: null,
    metric: "cesi_score",
    operator: "gt",
    threshold: 60,
    channels: ["websocket"],
    cooldown_minutes: 60,
  });

  const create = useMutation({
    mutationFn: () => api.createAlertRule(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alertRules"] });
      onClose();
    },
  });

  const toggle = (ch: string) =>
    setForm((f) => ({
      ...f,
      channels: f.channels.includes(ch)
        ? f.channels.filter((c) => c !== ch)
        : [...f.channels, ch],
    }));

  return (
    <div className="glass-panel p-5 mb-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">
        New Alert Rule
      </h3>
      <div className="grid grid-cols-2 gap-3 text-sm">
        {/* Region */}
        <label className="space-y-1">
          <span className="text-gray-400">Region (blank = all)</span>
          <input
            className="input-field"
            placeholder="e.g. EU"
            value={form.region_code ?? ""}
            onChange={(e) =>
              setForm({ ...form, region_code: e.target.value || null })
            }
          />
        </label>

        {/* Metric */}
        <label className="space-y-1">
          <span className="text-gray-400">Metric</span>
          <select
            className="input-field"
            value={form.metric}
            onChange={(e) => setForm({ ...form, metric: e.target.value })}
          >
            {METRICS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        {/* Operator */}
        <label className="space-y-1">
          <span className="text-gray-400">Operator</span>
          <select
            className="input-field"
            value={form.operator}
            onChange={(e) => setForm({ ...form, operator: e.target.value })}
          >
            {OPERATORS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        {/* Threshold */}
        <label className="space-y-1">
          <span className="text-gray-400">Threshold</span>
          <input
            type="number"
            className="input-field"
            value={form.threshold}
            onChange={(e) =>
              setForm({ ...form, threshold: Number(e.target.value) })
            }
          />
        </label>

        {/* Cooldown */}
        <label className="space-y-1 col-span-2">
          <span className="text-gray-400">Cooldown (minutes)</span>
          <input
            type="number"
            className="input-field"
            value={form.cooldown_minutes ?? 60}
            onChange={(e) =>
              setForm({ ...form, cooldown_minutes: Number(e.target.value) })
            }
          />
        </label>
      </div>

      {/* Channels */}
      <div className="mt-3">
        <span className="text-xs text-gray-400">Channels</span>
        <div className="flex gap-2 mt-1">
          {CHANNELS.map((ch) => (
            <button
              key={ch}
              onClick={() => toggle(ch)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                form.channels.includes(ch)
                  ? "bg-blue-500/30 text-blue-300"
                  : "bg-slate-700/50 text-gray-500"
              }`}
            >
              {ch}
            </button>
          ))}
        </div>
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
          {create.isPending ? "Creating…" : "Create Rule"}
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

/* ── Alert Rule row ───────────────────────────────────────────────── */
function RuleRow({ rule }: { rule: AlertRule }) {
  const qc = useQueryClient();
  const toggleEnabled = useMutation({
    mutationFn: () =>
      api.updateAlertRule(rule.id, { enabled: !rule.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alertRules"] }),
  });
  const deleteRule = useMutation({
    mutationFn: () => api.deleteAlertRule(rule.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alertRules"] }),
  });

  const opLabel =
    OPERATORS.find((o) => o.value === rule.operator)?.label ?? rule.operator;

  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
      <td className="px-4 py-3 text-sm">
        <span className="font-mono text-blue-300">
          {rule.region_code ?? "ALL"}
        </span>
      </td>
      <td className="px-4 py-3 text-sm">{rule.metric}</td>
      <td className="px-4 py-3 text-sm font-mono">
        {opLabel} {rule.threshold}
      </td>
      <td className="px-4 py-3 text-sm">
        <div className="flex gap-1 flex-wrap">
          {rule.channels.map((ch) => (
            <span
              key={ch}
              className="bg-slate-700/50 rounded-full px-2 py-0.5 text-xs text-gray-400"
            >
              {ch}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3 text-sm">{rule.cooldown_minutes}m</td>
      <td className="px-4 py-3">
        <button
          onClick={() => toggleEnabled.mutate()}
          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            rule.enabled
              ? "bg-green-500/20 text-green-400"
              : "bg-gray-500/20 text-gray-500"
          }`}
        >
          {rule.enabled ? "ON" : "OFF"}
        </button>
      </td>
      <td className="px-4 py-3">
        <button
          onClick={() => deleteRule.mutate()}
          className="text-xs text-red-400 hover:text-red-300 transition"
        >
          Delete
        </button>
      </td>
    </tr>
  );
}

/* ── History row ──────────────────────────────────────────────────── */
function HistoryRow({ item }: { item: AlertHistory }) {
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
      <td className="px-4 py-2 text-sm font-mono text-blue-300">
        {item.region_code}
      </td>
      <td className="px-4 py-2 text-sm">{item.metric}</td>
      <td className="px-4 py-2 text-sm font-mono">
        {item.value.toFixed(2)} / {item.threshold.toFixed(2)}
      </td>
      <td className="px-4 py-2 text-sm">
        <div className="flex gap-1 flex-wrap">
          {item.channels.map((ch) => (
            <span
              key={ch}
              className="bg-slate-700/50 rounded-full px-2 py-0.5 text-xs text-gray-400"
            >
              {ch}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-2 text-sm text-gray-500">
        {new Date(item.fired_at).toLocaleString()}
      </td>
    </tr>
  );
}

/* ── Main Alerts page ─────────────────────────────────────────────── */
export default function AlertsPage() {
  const [showForm, setShowForm] = useState(false);
  const [tab, setTab] = useState<"rules" | "history">("rules");

  const rules = useQuery({
    queryKey: ["alertRules"],
    queryFn: api.listAlertRules,
  });

  const history = useQuery({
    queryKey: ["alertHistory"],
    queryFn: () => api.listAlertHistory(100),
    enabled: tab === "history",
  });

  const count = useQuery({
    queryKey: ["alertHistoryCount"],
    queryFn: api.alertHistoryCount,
  });

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">Alert Management</h2>
          <p className="text-sm text-gray-400 mt-0.5">
            {count.data ? `${count.data.count} alerts fired` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setTab("rules")}
            className={tab === "rules" ? "btn-primary" : "btn-secondary"}
          >
            Rules ({rules.data?.length ?? 0})
          </button>
          <button
            onClick={() => setTab("history")}
            className={tab === "history" ? "btn-primary" : "btn-secondary"}
          >
            History
          </button>
          {tab === "rules" && (
            <button
              onClick={() => setShowForm(!showForm)}
              className="btn-primary"
            >
              + New Rule
            </button>
          )}
        </div>
      </div>

      {/* Form */}
      {showForm && <AlertRuleForm onClose={() => setShowForm(false)} />}

      {/* Rules table */}
      {tab === "rules" && (
        <div className="glass-panel overflow-hidden">
          <table className="w-full text-left">
            <thead className="border-b border-slate-700/60">
              <tr className="text-xs uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Region</th>
                <th className="px-4 py-3">Metric</th>
                <th className="px-4 py-3">Condition</th>
                <th className="px-4 py-3">Channels</th>
                <th className="px-4 py-3">Cooldown</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rules.isLoading && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                    Loading…
                  </td>
                </tr>
              )}
              {rules.data?.map((r) => <RuleRow key={r.id} rule={r} />)}
              {rules.data?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                    No alert rules configured yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* History table */}
      {tab === "history" && (
        <div className="glass-panel overflow-hidden">
          <table className="w-full text-left">
            <thead className="border-b border-slate-700/60">
              <tr className="text-xs uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Region</th>
                <th className="px-4 py-3">Metric</th>
                <th className="px-4 py-3">Value / Threshold</th>
                <th className="px-4 py-3">Channels</th>
                <th className="px-4 py-3">Fired At</th>
              </tr>
            </thead>
            <tbody>
              {history.isLoading && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                    Loading…
                  </td>
                </tr>
              )}
              {history.data?.map((h) => (
                <HistoryRow key={h.id} item={h} />
              ))}
              {history.data?.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                    No alerts have fired yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

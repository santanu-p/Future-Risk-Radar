import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type NewsSignal, type NLPSummary } from "../api/client";

/* ── Category colour map ──────────────────────────────────────────── */
const CATEGORY_COLORS: Record<string, string> = {
  sanctions: "bg-red-500/20 text-red-400",
  trade_policy: "bg-orange-500/20 text-orange-400",
  monetary_policy: "bg-yellow-500/20 text-yellow-400",
  political_instability: "bg-purple-500/20 text-purple-400",
  military_conflict: "bg-red-600/20 text-red-300",
  economic_crisis: "bg-amber-500/20 text-amber-400",
};

function categoryClass(cat: string) {
  return CATEGORY_COLORS[cat] ?? "bg-gray-500/20 text-gray-400";
}

/* ── Sentiment indicator ──────────────────────────────────────────── */
function SentimentDot({ value }: { value: number }) {
  const color =
    value < -0.3
      ? "bg-red-400"
      : value > 0.3
        ? "bg-green-400"
        : "bg-gray-400";
  return (
    <div className="flex items-center gap-1">
      <div className={`w-2 h-2 rounded-full ${color}`} />
      <span className="text-xs text-gray-500">{value.toFixed(2)}</span>
    </div>
  );
}

/* ── Summary cards ────────────────────────────────────────────────── */
function SummaryPanel({ data }: { data: NLPSummary }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
      <div className="glass-panel p-3 text-center">
        <div className="text-xs text-gray-500 uppercase tracking-wider">
          Total
        </div>
        <div className="text-xl font-bold mt-1">{data.total_signals}</div>
      </div>
      {Object.entries(data.by_category).map(([cat, count]) => (
        <div key={cat} className="glass-panel p-3 text-center">
          <div className="text-xs text-gray-500 uppercase tracking-wider truncate">
            {cat.replace(/_/g, " ")}
          </div>
          <div className="text-xl font-bold mt-1">{count}</div>
        </div>
      ))}
    </div>
  );
}

/* ── Signal card ──────────────────────────────────────────────────── */
function SignalCard({ signal }: { signal: NewsSignal }) {
  return (
    <div className="glass-panel p-4 hover:bg-slate-800/50 transition">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <a
            href={signal.url}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-medium text-gray-200 hover:text-blue-300 transition line-clamp-2"
          >
            {signal.title}
          </a>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <span
              className={`severity-badge text-[10px] ${categoryClass(signal.category)}`}
            >
              {signal.category.replace(/_/g, " ")}
            </span>
            <span className="text-xs font-mono text-blue-300">
              {signal.region_code}
            </span>
            <span className="text-xs text-gray-600">
              {signal.source_domain}
            </span>
            <SentimentDot value={signal.sentiment} />
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-xs text-gray-500">
            {signal.confidence >= 0.7 ? (
              <span className="text-green-400">
                {(signal.confidence * 100).toFixed(0)}%
              </span>
            ) : (
              <span className="text-gray-500">
                {(signal.confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="text-[10px] text-gray-600 mt-0.5">
            {new Date(signal.published_at).toLocaleDateString()}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main NLP News Feed page ──────────────────────────────────────── */
export default function NewsFeedPage() {
  const qc = useQueryClient();
  const [regionFilter, setRegionFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");

  const summary = useQuery({
    queryKey: ["nlpSummary"],
    queryFn: api.nlpSummary,
  });

  const signals = useQuery({
    queryKey: ["nlpSignals", regionFilter, categoryFilter],
    queryFn: () =>
      api.listNlpSignals(
        100,
        0,
        regionFilter || undefined,
        categoryFilter || undefined,
      ),
  });

  const regions = useQuery({
    queryKey: ["regions"],
    queryFn: api.listRegions,
  });

  const scan = useMutation({
    mutationFn: api.triggerNlpScan,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["nlpSignals"] });
      qc.invalidateQueries({ queryKey: ["nlpSummary"] });
    },
  });

  const categories = Object.keys(CATEGORY_COLORS);

  return (
    <div className="h-full overflow-auto p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">NLP News Intelligence</h2>
          <p className="text-sm text-gray-400 mt-0.5">
            GDELT-powered qualitative risk signals classified by category
          </p>
        </div>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="btn-primary"
        >
          {scan.isPending ? "Scanning…" : "Run NLP Scan"}
        </button>
      </div>

      {/* Summary */}
      {summary.data && <SummaryPanel data={summary.data} />}

      {/* Filters */}
      <div className="flex gap-3 items-end flex-wrap">
        <label className="space-y-1 text-sm">
          <span className="text-gray-400">Region</span>
          <select
            className="input-field"
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
          >
            <option value="">All regions</option>
            {regions.data?.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-sm">
          <span className="text-gray-400">Category</span>
          <select
            className="input-field"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Signal list */}
      <div className="space-y-2">
        {signals.isLoading && (
          <div className="glass-panel p-8 text-center text-gray-500">
            Loading news signals…
          </div>
        )}
        {signals.data?.map((s) => <SignalCard key={s.id} signal={s} />)}
        {signals.data?.length === 0 && (
          <div className="glass-panel p-8 text-center text-gray-500">
            No signals match the current filters.
          </div>
        )}
      </div>
    </div>
  );
}

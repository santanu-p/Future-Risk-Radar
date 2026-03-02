import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type RegionSummary } from "../api/client";
import { useAppStore } from "../store/appStore";
import { severityClass } from "../lib/utils";

export default function Sidebar() {
  const { sidebarOpen, selectedRegion, setSelectedRegion } = useAppStore();
  const navigate = useNavigate();

  const { data: regions, isLoading } = useQuery({
    queryKey: ["regions"],
    queryFn: api.listRegions,
  });

  if (!sidebarOpen) return null;

  return (
    <aside className="glass-panel flex w-72 flex-col border-r border-slate-700/50">
      <div className="px-4 py-3 border-b border-slate-700/50">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
          Monitored Regions
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {isLoading && (
          <div className="text-center text-sm text-gray-500 py-8">
            Loading regions…
          </div>
        )}
        {regions?.map((region) => (
          <button
            key={region.id}
            onClick={() => {
              setSelectedRegion(region);
              navigate(`/region/${region.code}`);
            }}
            className={`w-full rounded-lg px-3 py-2.5 text-left transition hover:bg-slate-800 ${
              selectedRegion?.code === region.code ? "bg-slate-800" : ""
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{region.name}</span>
              {region.latest_cesi !== null && (
                <span
                  className={`severity-badge ${severityClass(region.severity)}`}
                >
                  {region.latest_cesi.toFixed(0)}
                </span>
              )}
            </div>
            <div className="mt-1 text-xs text-gray-500">{region.code}</div>
          </button>
        ))}
      </div>
    </aside>
  );
}

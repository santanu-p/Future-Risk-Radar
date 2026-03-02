import { useAppStore } from "../store/appStore";

export default function Header() {
  return (
    <header className="glass-panel flex h-14 items-center justify-between border-b border-slate-700/50 px-6">
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-sm font-bold">
          FR
        </div>
        <h1 className="text-lg font-semibold tracking-tight">
          Future Risk Radar
        </h1>
        <span className="rounded-md bg-amber-500/20 px-2 py-0.5 text-xs text-amber-400">
          BETA
        </span>
      </div>

      <div className="flex items-center gap-4 text-sm text-gray-400">
        <span>CESI Engine v0.1.0</span>
        <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
        <span>Live</span>
      </div>
    </header>
  );
}

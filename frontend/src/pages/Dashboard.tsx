import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import GlobeView from "../components/GlobeView";
import CESIPanel from "../components/CESIPanel";
import { useCesiScoresWS } from "../hooks/useWebSocket";

export default function Dashboard() {
  const queryClient = useQueryClient();

  const { data: regions } = useQuery({
    queryKey: ["regions"],
    queryFn: api.listRegions,
  });

  const { data: scores } = useQuery({
    queryKey: ["cesi-scores"],
    queryFn: api.latestScores,
    refetchInterval: 300_000,
  });

  // Live CESI score updates via WebSocket
  const handleWSUpdate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["cesi-scores"] });
    queryClient.invalidateQueries({ queryKey: ["regions"] });
  }, [queryClient]);
  useCesiScoresWS(handleWSUpdate);

  return (
    <div className="relative h-full w-full">
      {/* 3D Globe — full viewport */}
      <GlobeView regions={regions ?? []} />

      {/* Floating CESI summary panel */}
      <div className="absolute bottom-4 right-4 w-96">
        <CESIPanel scores={scores ?? []} regions={regions ?? []} />
      </div>
    </div>
  );
}

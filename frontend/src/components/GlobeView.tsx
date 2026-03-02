import { useMemo, useCallback } from "react";
import { DeckGL } from "@deck.gl/core";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { Map as MapLibreMap } from "maplibre-gl";
import { useNavigate } from "react-router-dom";
import type { RegionSummary } from "../api/client";
import { useAppStore } from "../store/appStore";
import { severityColor } from "../lib/utils";

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

interface Props {
  regions: RegionSummary[];
}

export default function GlobeView({ regions }: Props) {
  const { viewState, setViewState, setSelectedRegion } = useAppStore();
  const navigate = useNavigate();

  const onViewStateChange = useCallback(
    ({ viewState: vs }: any) => setViewState(vs),
    [setViewState],
  );

  const handleClick = useCallback(
    (info: any) => {
      if (info.object) {
        const region = info.object as RegionSummary;
        setSelectedRegion(region);
        navigate(`/region/${region.code}`);
      }
    },
    [navigate, setSelectedRegion],
  );

  const layers = useMemo(
    () => [
      // Region markers — size proportional to CESI score
      new ScatterplotLayer({
        id: "region-markers",
        data: regions,
        pickable: true,
        opacity: 0.8,
        stroked: true,
        filled: true,
        radiusScale: 1,
        radiusMinPixels: 12,
        radiusMaxPixels: 60,
        lineWidthMinPixels: 2,
        getPosition: (d: RegionSummary) => [d.centroid_lon, d.centroid_lat],
        getRadius: (d: RegionSummary) =>
          d.latest_cesi ? Math.max(d.latest_cesi * 800, 40000) : 40000,
        getFillColor: (d: RegionSummary) => [
          ...severityColor(d.severity),
          180,
        ] as any,
        getLineColor: (d: RegionSummary) => [
          ...severityColor(d.severity),
          255,
        ] as any,
        onClick: handleClick,
      }),

      // Region labels
      new TextLayer({
        id: "region-labels",
        data: regions,
        pickable: false,
        getPosition: (d: RegionSummary) => [d.centroid_lon, d.centroid_lat],
        getText: (d: RegionSummary) =>
          `${d.code}\n${d.latest_cesi?.toFixed(0) ?? "—"}`,
        getSize: 14,
        getColor: [255, 255, 255, 220],
        getTextAnchor: "middle",
        getAlignmentBaseline: "center",
        fontFamily: "Inter, system-ui, sans-serif",
        fontWeight: 700,
      }),
    ],
    [regions, handleClick],
  );

  return (
    <DeckGL
      viewState={viewState}
      onViewStateChange={onViewStateChange}
      controller={true}
      layers={layers}
      getTooltip={({ object }: any) => {
        if (!object) return null;
        const r = object as RegionSummary;
        return {
          html: `<div class="p-2">
            <b>${r.name}</b><br/>
            CESI: ${r.latest_cesi?.toFixed(1) ?? "N/A"}<br/>
            Severity: ${r.severity ?? "unknown"}
          </div>`,
          style: {
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            color: "#e2e8f0",
            borderRadius: "8px",
            fontSize: "13px",
          },
        };
      }}
    >
      {/* @ts-expect-error MapLibre typing */}
      <MapLibreMap mapStyle={MAP_STYLE} />
    </DeckGL>
  );
}

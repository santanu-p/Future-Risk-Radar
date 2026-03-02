/** Global application state — Zustand store. */

import { create } from "zustand";
import type { RegionSummary } from "../api/client";

interface AppState {
  // Selected region for detail view
  selectedRegion: RegionSummary | null;
  setSelectedRegion: (region: RegionSummary | null) => void;

  // Globe view state
  viewState: {
    longitude: number;
    latitude: number;
    zoom: number;
    pitch: number;
    bearing: number;
  };
  setViewState: (vs: Partial<AppState["viewState"]>) => void;

  // UI panels
  sidebarOpen: boolean;
  toggleSidebar: () => void;

  // Theme
  darkMode: boolean;
  toggleDarkMode: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedRegion: null,
  setSelectedRegion: (region) => set({ selectedRegion: region }),

  viewState: {
    longitude: 20,
    latitude: 30,
    zoom: 2.2,
    pitch: 45,
    bearing: 0,
  },
  setViewState: (vs) =>
    set((state) => ({ viewState: { ...state.viewState, ...vs } })),

  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

  darkMode: true,
  toggleDarkMode: () => set((state) => ({ darkMode: !state.darkMode })),
}));

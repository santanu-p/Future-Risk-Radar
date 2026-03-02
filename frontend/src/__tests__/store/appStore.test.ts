import { describe, expect, it } from "vitest";
import { useAppStore } from "../../store/appStore";

describe("appStore", () => {
  it("has correct initial state", () => {
    const state = useAppStore.getState();
    expect(state.selectedRegion).toBeNull();
    expect(state.sidebarOpen).toBe(true);
    expect(state.darkMode).toBe(true);
    expect(state.viewState.zoom).toBeGreaterThan(0);
  });

  it("setSelectedRegion updates state", () => {
    const region = {
      id: "test-id",
      code: "EU",
      name: "European Union",
      centroid_lat: 50.1,
      centroid_lon: 9.7,
      latest_cesi: 35.0,
      severity: "elevated",
    };
    useAppStore.getState().setSelectedRegion(region);
    expect(useAppStore.getState().selectedRegion?.code).toBe("EU");
  });

  it("toggleSidebar flips state", () => {
    const initial = useAppStore.getState().sidebarOpen;
    useAppStore.getState().toggleSidebar();
    expect(useAppStore.getState().sidebarOpen).toBe(!initial);
  });

  it("toggleDarkMode flips state", () => {
    const initial = useAppStore.getState().darkMode;
    useAppStore.getState().toggleDarkMode();
    expect(useAppStore.getState().darkMode).toBe(!initial);
  });

  it("setViewState merges partial updates", () => {
    useAppStore.getState().setViewState({ zoom: 5.0 });
    const vs = useAppStore.getState().viewState;
    expect(vs.zoom).toBe(5.0);
    // Other fields should be preserved
    expect(vs.pitch).toBe(45);
  });
});

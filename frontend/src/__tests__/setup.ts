import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Mock maplibre-gl which isn't available in jsdom
vi.mock("maplibre-gl", () => ({
  default: {
    Map: vi.fn(),
    NavigationControl: vi.fn(),
    Popup: vi.fn(),
  },
}));

// Mock deck.gl
vi.mock("@deck.gl/core", () => ({
  Deck: vi.fn(),
  MapView: vi.fn(),
}));

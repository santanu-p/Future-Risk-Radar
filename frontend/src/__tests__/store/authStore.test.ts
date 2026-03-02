import { describe, expect, it, beforeEach } from "vitest";
import { useAuthStore } from "../../store/authStore";

describe("authStore", () => {
  beforeEach(() => {
    // Reset store state between tests
    useAuthStore.setState({
      token: null,
      expiresAt: null,
      user: null,
      isAuthenticated: false,
    });
    localStorage.clear();
  });

  it("starts with unauthenticated state", () => {
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
  });

  it("login sets token and user", () => {
    const { login } = useAuthStore.getState();
    login("test-token-123", 3600, "user@example.com");

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.token).toBe("test-token-123");
    expect(state.user?.email).toBe("user@example.com");
    expect(state.expiresAt).toBeGreaterThan(Date.now());
  });

  it("login stores token in localStorage", () => {
    const { login } = useAuthStore.getState();
    login("test-token-123", 3600, "user@example.com");

    expect(localStorage.getItem("frr_token")).toBe("test-token-123");
  });

  it("logout clears state", () => {
    const { login, logout } = useAuthStore.getState();
    login("test-token-123", 3600, "user@example.com");
    logout();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.token).toBeNull();
    expect(state.user).toBeNull();
    expect(localStorage.getItem("frr_token")).toBeNull();
  });

  it("isExpired returns true when no token", () => {
    expect(useAuthStore.getState().isExpired()).toBe(true);
  });

  it("isExpired returns false for fresh token", () => {
    const { login } = useAuthStore.getState();
    login("test-token", 3600, "user@example.com");
    expect(useAuthStore.getState().isExpired()).toBe(false);
  });

  it("isExpired returns true when token has expired", () => {
    useAuthStore.setState({
      token: "expired-token",
      expiresAt: Date.now() - 1000, // 1 second ago
      user: { email: "user@example.com" },
      isAuthenticated: true,
    });
    expect(useAuthStore.getState().isExpired()).toBe(true);
  });
});

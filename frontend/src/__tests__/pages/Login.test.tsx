import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import LoginPage from "../../pages/Login";
import { useAuthStore } from "../../store/authStore";

// Mock the API client
vi.mock("../../api/client", () => ({
  api: {
    login: vi.fn(),
  },
}));

import { api } from "../../api/client";

function renderLogin(initialRoute = "/login") {
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      token: null,
      expiresAt: null,
      user: null,
      isAuthenticated: false,
    });
  });

  it("renders email and password fields", () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("renders sign in button", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("renders the title", () => {
    renderLogin();
    expect(screen.getByText("Future Risk Radar")).toBeInTheDocument();
  });

  it("shows error on failed login", async () => {
    const user = userEvent.setup();
    const mockedLogin = vi.mocked(api.login);
    mockedLogin.mockRejectedValue(new Error("API 401: Invalid credentials"));

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "bad@test.com");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it("calls api.login with correct credentials", async () => {
    const user = userEvent.setup();
    const mockedLogin = vi.mocked(api.login);
    mockedLogin.mockResolvedValue({ access_token: "tok", expires_in: 3600 });

    renderLogin();

    await user.type(screen.getByLabelText(/email/i), "analyst@company.com");
    await user.type(screen.getByLabelText(/password/i), "secret123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockedLogin).toHaveBeenCalledWith("analyst@company.com", "secret123");
    });
  });
});

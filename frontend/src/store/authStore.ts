/** Auth store — JWT token lifecycle management with Zustand. */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface User {
  email: string;
}

interface AuthState {
  token: string | null;
  expiresAt: number | null;
  user: User | null;
  isAuthenticated: boolean;

  /** Store token after successful login. */
  login: (token: string, expiresIn: number, email: string) => void;

  /** Clear token and user state. */
  logout: () => void;

  /** Check whether the current token has expired. */
  isExpired: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      expiresAt: null,
      user: null,
      isAuthenticated: false,

      login: (token, expiresIn, email) => {
        const expiresAt = Date.now() + expiresIn * 1000;
        // Also store in localStorage for the API client
        localStorage.setItem("frr_token", token);
        set({
          token,
          expiresAt,
          user: { email },
          isAuthenticated: true,
        });
      },

      logout: () => {
        localStorage.removeItem("frr_token");
        set({
          token: null,
          expiresAt: null,
          user: null,
          isAuthenticated: false,
        });
      },

      isExpired: () => {
        const { expiresAt } = get();
        if (!expiresAt) return true;
        return Date.now() > expiresAt;
      },
    }),
    {
      name: "frr-auth",
      partialize: (state) => ({
        token: state.token,
        expiresAt: state.expiresAt,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        // On rehydrate, check if token is still valid
        if (state && state.expiresAt && Date.now() > state.expiresAt) {
          state.logout();
        } else if (state?.token) {
          // Re-sync localStorage for API client
          localStorage.setItem("frr_token", state.token);
        }
      },
    },
  ),
);

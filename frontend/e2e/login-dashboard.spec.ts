// @ts-nocheck
import { test, expect } from "@playwright/test";

test.describe("login and dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/auth/login", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: "e2e-token", expires_in: 3600 }),
      });
    });

    await page.route("**/api/v1/regions/", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "11111111-1111-1111-1111-111111111111",
            code: "EU",
            name: "European Union",
            centroid_lat: 50.1,
            centroid_lon: 9.7,
            latest_cesi: 36.5,
            severity: "elevated",
          },
        ]),
      });
    });

    await page.route("**/api/v1/cesi/scores", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "22222222-2222-2222-2222-222222222222",
            region_id: "11111111-1111-1111-1111-111111111111",
            score: 36.5,
            severity: "elevated",
            layer_scores: {},
            crisis_probabilities: {},
            amplification_applied: false,
            model_version: "v0.3.0",
            scored_at: new Date().toISOString(),
          },
        ]),
      });
    });

    await page.route("**/ws/**", async (route) => {
      await route.abort();
    });
  });

  test("allows login and renders protected shell", async ({ page }) => {
    await page.goto("/login");

    await page.getByLabel("Email").fill("analyst@company.com");
    await page.getByLabel("Password").fill("secret123");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByText("CESI Engine v0.3.0")).toBeVisible();
    await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /dashboard/i })).toBeVisible();
  });
});

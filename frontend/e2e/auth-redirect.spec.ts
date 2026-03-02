// @ts-nocheck
import { test, expect } from "@playwright/test";

test.describe("auth route protection", () => {
  test("redirects unauthenticated user from / to /login", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Future Risk Radar" })).toBeVisible();
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
  });
});

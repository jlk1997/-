import { expect, test } from "@playwright/test";

test("phone create page stays a phone column and names the app", async ({ page }) => {
  await page.goto("/#/pages/create/index?view=mobile");
  await expect(page.locator(".create-appbar__brand")).toContainText("比特音");
  await expect(page.locator(".create-home")).toBeVisible();
});

test("desktop studio login is its own app", async ({ page }) => {
  await page.goto("http://127.0.0.1:10087/studio/login");
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
  await expect(page.locator("h1")).toContainText("比特音");
});

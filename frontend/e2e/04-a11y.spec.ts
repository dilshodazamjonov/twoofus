import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { connectDemo, pinDemo, resetRoom } from "./helpers";
import { SIGNED_OUT } from "./state";

async function expectNoSeriousViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
    `${label}: serious accessibility violations`,
  ).toEqual([]);
}

async function expectNoSidewaysScroll(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label}: page is wider than the screen`).toBeLessThanOrEqual(0);
}

test.describe("signed out", () => {
  test.use({ storageState: SIGNED_OUT });

  test("public pages pass axe (WCAG 2.2 AA rules)", async ({ page }) => {
    for (const path of ["/", "/sign-in", "/invite", "/privacy", "/does-not-exist"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expectNoSeriousViolations(page, path);
    }
  });

  test("public pages fit a 375 px wide phone", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    for (const path of ["/", "/sign-in", "/invite", "/privacy"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expectNoSidewaysScroll(page, path);
    }
  });
});

test("signed-in pages pass axe, in light and dark mode", async ({ page }) => {
  await connectDemo(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of ["/room", "/connect", "/settings"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expectNoSeriousViolations(page, `${path} (${scheme})`);
    }
  }
  await resetRoom(page);
});

test("signed-in pages fit a 375 px wide phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await connectDemo(page); // also shows the (wide) demo scenario picker in Settings
  for (const path of ["/room", "/connect", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expectNoSidewaysScroll(page, path);
  }
  await resetRoom(page);
});

test("keyboard: skip link first, visible focus, the nav is reachable", async ({ page, isMobile, browserName }) => {
  await page.goto("/room");
  await expect(page.getByText(/^Updated/)).toBeVisible();
  const skip = page.getByRole("link", { name: "Skip to content" });
  if (browserName === "webkit") {
    // Safari moves Tab focus to links only with "Press Tab to highlight each item" on.
    await skip.focus();
  } else {
    await page.keyboard.press("Tab");
  }
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  const outline = await skip.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
  const nav = page.getByRole("navigation", { name: "Main" }).filter({ visible: true });
  await expect(nav).toHaveCount(1);
  await expect(nav.getByRole("link", { name: "Settings" })).toBeVisible();
  if (!isMobile) {
    await nav.getByRole("link", { name: "Settings" }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/settings$/);
  }
});

test("reduced motion: the listening pulse and other animations stand still", async ({ page }) => {
  await connectDemo(page);
  await pinDemo(page, "playing");
  for (const reduced of [false, true]) {
    await page.emulateMedia({ reducedMotion: reduced ? "reduce" : "no-preference" });
    await page.goto("/room");
    const pulse = page.locator(".animate-soft-pulse").first();
    await expect(pulse).toBeAttached();
    const timing = await pulse.evaluate((el) => {
      const style = getComputedStyle(el);
      return { duration: parseFloat(style.animationDuration), iterations: style.animationIterationCount };
    });
    if (reduced) {
      expect(timing.duration).toBeLessThan(0.01); // seconds: effectively no motion
      expect(timing.iterations).toBe("1");
    } else {
      expect(timing.duration).toBeGreaterThan(0.5);
      expect(timing.iterations).toBe("infinite");
    }
  }
  await resetRoom(page);
});


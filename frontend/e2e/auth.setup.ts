import { expect, test as setup } from "@playwright/test";

import { owner } from "./helpers";
import { OWNER_STATE } from "./state";

setup("the owner signs in (protected page -> sign-in -> back)", async ({ page }) => {
  expect(owner.password, "run through ./scripts/e2e.sh").not.toBe("");
  await page.goto("/room");
  await expect(page).toHaveURL(/\/sign-in\?next=%2Froom$/);
  await page.getByLabel("Username").fill(owner.username);
  await page.getByLabel("Password", { exact: true }).fill(owner.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/room$/);
  await expect(page.getByRole("article", { name: owner.name })).toBeVisible();
  await page.context().storageState({ path: OWNER_STATE });
});

import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
const template = process.env.MOBIPEG_TEST_CIA_TEMPLATE;
const movies = JSON.parse(process.env.MOBIPEG_TEST_CIA_MOVIES || "[]");
test("browser builds and downloads a real CIA from a local template", async ({
  page,
}, testInfo) => {
  test.skip(
    !template || !movies.length,
    "Provide a local compatible CIA template and its movie inputs",
  );
  await page.goto("/cia.html");
  await page.locator("#ciaFiles").setInputFiles(movies);
  await expect(page.locator("#ciaEpisodes > li")).toHaveCount(movies.length);
  await page.locator("#ciaTemplate").setInputFiles(template);
  await page.locator("#ciaTitle").fill("Browser integration");
  await page.locator("#ciaPublisher").fill("Local test");
  await page.locator("#ciaId").fill("C2468");
  const download = page.waitForEvent("download");
  await page.locator("#ciaBuild").click();
  const file = await download,
    path = testInfo.outputPath("browser.cia");
  await file.saveAs(path);
  const result = JSON.parse(
    execFileSync("python3", ["native/cia_builder.py", "verify", path], {
      encoding: "utf8",
    }),
  );
  expect(result.title_id).toBe("000400000C246800");
  await expect(page.locator("#ciaStatus")).toContainText(
    "content hash verified",
  );
});

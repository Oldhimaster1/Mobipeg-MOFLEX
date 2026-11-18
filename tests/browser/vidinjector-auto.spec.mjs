import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  createReadStream,
  readFileSync,
  statSync,
} from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

const movies = JSON.parse(process.env.MOBIPEG_TEST_CIA_MOVIES || "[]");
const backend = process.env.MOBIPEG_CIA_BACKEND;
const fileHash = async (path) => {
  const hash = createHash("sha256");
  for await (const bytes of createReadStream(path)) hash.update(bytes);
  return hash.digest("hex");
};

test("browser obtains the pinned VidInjector player and builds a playable collection", async ({
  page,
}, testInfo) => {
  test.skip(
    process.env.MOBIPEG_TEST_VIDINJECTOR_AUTO !== "1" || movies.length < 2,
    "Enable the explicit network test and provide two local MOFLEX fixtures",
  );
  test.setTimeout(180000);
  await page.goto("/cia.html");
  await page.locator("#ciaFiles").setInputFiles(movies.slice(0, 2));
  await page.locator("#ciaTitle").fill("Automatic player test");
  await page.locator("#ciaPublisher").fill("MobiPEG QA");
  await page.locator("#ciaId").fill("C4321");
  await page.locator("#ciaUseVidInjector").check();

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#ciaBuild").click();
  const download = await downloadPromise;
  const output = testInfo.outputPath("automatic-player.cia");
  await download.saveAs(output);
  await expect(page.locator("#ciaStatus")).toContainText("content hash verified");

  const verified = JSON.parse(
    execFileSync("python3", ["native/cia_builder.py", "verify", output], {
      encoding: "utf8",
    }),
  );
  expect(verified.title_id).toBe("000400000C432100");
  expect(verified.contents_checked).toBe(1);
  expect(statSync(output).size).toBeGreaterThan(2_000_000);

  if (!backend) return;
  const extracted = testInfo.outputPath("extracted");
  execFileSync(backend, ["-ec", output, extracted]);
  for (let index = 0; index < 2; index++) {
    const actual = join(extracted, "romfs/movie/movie_" + index + ".moflex");
    expect(await fileHash(actual)).toBe(await fileHash(movies[index]));
  }
  const romfsIcon = readFileSync(join(extracted, "romfs/icon.icn"));
  const exefsIcon = readFileSync(join(extracted, "exefs/icon.bin"));
  expect(romfsIcon.subarray(0, 4).toString()).toBe("SMDH");
  expect(romfsIcon.equals(exefsIcon)).toBe(true);
});

import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { buildCia, inspectCia } from "../cia-packager.mjs";
const backend = process.env.MOBIPEG_CIA_BACKEND;
test(
  "real native templates rebuild into independently verified single and two-movie CIAs",
  { skip: !backend },
  async () => {
    const dir = mkdtempSync(join(tmpdir(), "mobipeg-cia-browser-"));
    const run = (cmd, args) =>
      execFileSync(cmd, args, { maxBuffer: 8 * 1024 * 1024 });
    try {
      const source = join(dir, "source.mkv"),
        movie = join(dir, "clip.moflex");
      run("ffmpeg", [
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=320x240:r=24:d=0.5",
        "-c:v",
        "ffv1",
        source,
      ]);
      run("python3", [
        "native/MobiPEG_Studio_V15.py",
        "-i",
        source,
        "-o",
        movie,
        "--preset",
        "small",
        "--resolution",
        "320x240",
      ]);
      for (const count of [1, 2]) {
        const project = {
          version: 1,
          title: "Template",
          publisher: "Test",
          id: "C1000",
          movies: Array.from({ length: count }, () => ({
            file: movie,
            title: "Old",
          })),
        };
        const json = join(dir, "project.json"),
          templatePath = join(dir, "template" + count + ".cia");
        writeFileSync(json, JSON.stringify(project));
        run("python3", [
          "native/cia_builder.py",
          "build",
          json,
          templatePath,
          "--backend",
          backend,
        ]);
        const template = new Blob([readFileSync(templatePath)]);
        project.title = "Browser title";
        project.publisher = "Browser publisher";
        project.id = count === 1 ? "C1234" : "C5678";
        project.movies.forEach((m, i) => (m.title = "Episode " + i));
        const blob = await buildCia({
          template,
          project,
          movies: Array.from(
            { length: count },
            () => new Blob([readFileSync(movie)]),
          ),
        });
        const destination = join(dir, "browser" + count + ".cia");
        writeFileSync(destination, new Uint8Array(await blob.arrayBuffer()));
        const result = JSON.parse(
          run("python3", ["native/cia_builder.py", "verify", destination]),
        );
        assert.equal(result.title_id, "000400000" + project.id + "00");
        const extracted = join(dir, "extracted" + count);
        run(backend, ["-ec", destination, extracted]);
        for (let i = 0; i < count; i++) {
          const path = count === 1 ? "movie.moflex" : "movie_" + i + ".moflex";
          assert.deepEqual(
            readFileSync(join(extracted, "romfs/movie", path)),
            readFileSync(movie),
          );
        }
        const custom = await buildCia({
          template,
          project,
          movies: Array.from(
            { length: count },
            () => new Blob([readFileSync(movie)]),
          ),
          icon: new Blob([readFileSync(join(extracted, "exefs/icon.bin"))]),
          banner: new Blob([readFileSync(join(extracted, "exefs/banner.bin"))]),
        });
        const customPath = join(dir, "custom" + count + ".cia");
        writeFileSync(customPath, new Uint8Array(await custom.arrayBuffer()));
        run("python3", ["native/cia_builder.py", "verify", customPath]);
        const corrupt = new Uint8Array(await blob.arrayBuffer());
        corrupt[corrupt.length - 512] ^= 1;
        await assert.rejects(() => inspectCia(new Blob([corrupt])), /hash/);
        await assert.rejects(
          () => buildCia({ template, project, movies: [] }),
          /slots/,
        );
      }
      await assert.rejects(() => inspectCia(new Blob(["bad"])), /Truncated/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  },
);

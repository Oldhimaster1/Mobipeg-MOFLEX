import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  readFileSync,
  writeFileSync,
  rmSync,
  readdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { buildCia, inspectCia } from "../cia-packager.mjs";
const backend = process.env.MOBIPEG_CIA_BACKEND;
test(
  "one collection template rebuilds into independently verified 1–27 episode CIAs",
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
      for (const count of [1, 2, 5, 10, 20, 27]) {
        const project = {
          version: 1,
          title: "Template",
          publisher: "Test",
          id: "C1000",
          movies: Array.from({ length: 2 }, () => ({
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
        project.movies = Array.from({ length: count }, (_, i) => ({
          file: movie,
          title: "Episode " + i,
        }));
        if(count===1){
          const singlePath=join(dir,'single-template.cia');writeFileSync(json,JSON.stringify(project));
          run('python3',['native/cia_builder.py','build',json,singlePath,'--backend',backend]);
          const single=new Blob([readFileSync(singlePath)]);
          const rebuilt=await buildCia({template:single,project,movies:[new Blob([readFileSync(movie)])]});
          await inspectCia(rebuilt);
          await assert.rejects(()=>buildCia({template:single,project:{...project,movies:[...project.movies,...project.movies]},movies:[new Blob([readFileSync(movie)]),new Blob([readFileSync(movie)])]}),/collection-player/);
        }
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
        const original = join(dir, "original" + count);
        run(backend, ["-ec", templatePath, original]);
        const extracted = join(dir, "extracted" + count);
        run(backend, ["-ec", destination, extracted]);
        for (let i = 0; i < count; i++) {
          const path = "movie_" + i + ".moflex";
          assert.deepEqual(
            readFileSync(join(extracted, "romfs/movie", path)),
            readFileSync(movie),
          );
        }
        const titles = readFileSync(
          join(extracted, "romfs/movie/movie_title.csv"),
        ).toString("utf16le");
        const rows = titles
          .replace(/^\ufeff/, "")
          .trim()
          .split(/\r?\n/)
          .slice(1);
        assert.equal(rows.length, count);
        rows.forEach((row, i) =>
          assert.equal(
            row,
            Array(12)
              .fill("Episode " + i)
              .join(","),
          ),
        );
        const settings = readFileSync(
          join(extracted, "romfs/settings/settingsTL.csv"),
        ).toString("utf16le");
        assert.match(settings,/# EN:\r\nBrowser title/);
        assert.match(settings,/# EN:\r\nBrowser publisher/);
        assert.match(
          settings,
          new RegExp("# 動画の数\\r?\\n" + count + "\\r?\\n"),
        );
        for (const resource of readdirSync(join(original, "romfs/layout"))) {
          assert.deepEqual(
            readFileSync(join(original, "romfs/layout", resource)),
            readFileSync(join(extracted, "romfs/layout", resource)),
          );
        }
        async function code(input) {
          const parsed = await inspectCia(input),
            header = new DataView(parsed.ncch.buffer),
            start = header.getUint32(0x1a0, true) * 512;
          const entries = new Uint8Array(
              await parsed.content.slice(start, start + 512).arrayBuffer(),
            ),
            v = new DataView(entries.buffer);
          for (let i = 0; i < 10; i++)
            if (
              new TextDecoder()
                .decode(entries.subarray(i * 16, i * 16 + 8))
                .replace(/\0.*$/s, "") === ".code"
            )
              return new Uint8Array(
                await parsed.content
                  .slice(
                    start + 512 + v.getUint32(i * 16 + 8, true),
                    start +
                      512 +
                      v.getUint32(i * 16 + 8, true) +
                      v.getUint32(i * 16 + 12, true),
                  )
                  .arrayBuffer(),
              );
          throw Error("Executable absent");
        }
        assert.deepEqual(await code(blob), await code(template));
        const thumbnail=readFileSync(join(extracted,'romfs/movie/movie_0.bimg'));
        const thumbnails=Array.from({length:count},(_,i)=>{const bytes=Uint8Array.from(thumbnail);bytes[bytes.length-1]^=i+1;return new Blob([bytes]);});
        const custom = await buildCia({
          template,
          project,
          movies: Array.from(
            { length: count },
            () => new Blob([readFileSync(movie)]),
          ),
          episodeBanners: thumbnails,
          icon: new Blob([readFileSync(join(extracted, "exefs/icon.bin"))]),
          banner: new Blob([readFileSync(join(extracted, "exefs/banner.bin"))]),
        });
        const customPath = join(dir, "custom" + count + ".cia");
        writeFileSync(customPath, new Uint8Array(await custom.arrayBuffer()));
        run("python3", ["native/cia_builder.py", "verify", customPath]);
        const customExtract=join(dir,'custom-extracted'+count);run(backend,['-ec',customPath,customExtract]);
        for(let i=0;i<count;i++)assert.deepEqual(readFileSync(join(customExtract,'romfs/movie/movie_'+i+'.bimg')),Buffer.from(await thumbnails[i].arrayBuffer()));
        const corrupt = new Uint8Array(await blob.arrayBuffer());
        corrupt[corrupt.length - 512] ^= 1;
        await assert.rejects(() => inspectCia(new Blob([corrupt])), /hash/);
        await assert.rejects(
          () => buildCia({ template, project, movies: [] }),
          /matching movie entries/,
        );
      }
      await assert.rejects(() => inspectCia(new Blob(["bad"])), /Truncated/);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  },
);

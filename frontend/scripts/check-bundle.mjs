/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
// Bundle budget: fails `npm run build` if the first visit grows past
// budget (Brotli sizes). To see why: ANALYZE=1 npm run build, then open dist/stats.html.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { brotliCompressSync } from "node:zlib";

const KB = 1024;
const BUDGET = {
  initialJs: 200 * KB, // entry + vendor + everything index.html preloads
  initialCss: 40 * KB,
  lazyChunk: 120 * KB, // any one page / feature chunk loaded later
};

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const html = readFileSync(join(dist, "index.html"), "utf8");
const brotli = (file) => {
  const br = join(dist, `${file}.br`);
  return existsSync(br) ? statSync(br).size : brotliCompressSync(readFileSync(join(dist, file))).length;
};

const initial = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1]);
const initialJs = initial.filter((f) => f.endsWith(".js"));
const initialCss = initial.filter((f) => f.endsWith(".css"));
const lazy = readdirSync(join(dist, "assets"))
  .filter((f) => f.endsWith(".js"))
  .map((f) => `assets/${f}`)
  .filter((f) => !initialJs.includes(f));

const sum = (files) => files.reduce((n, f) => n + brotli(f), 0);
const kb = (n) => `${(n / KB).toFixed(1)} KB`;
const rows = [];
const failures = [];
const check = (what, size, budget) => {
  rows.push([what, kb(size), kb(budget), size <= budget ? "ok" : "OVER"]);
  if (size > budget) failures.push(`${what}: ${kb(size)} > ${kb(budget)}`);
};

check(`first visit JS (${initialJs.length} files)`, sum(initialJs), BUDGET.initialJs);
check(`first visit CSS (${initialCss.length} files)`, sum(initialCss), BUDGET.initialCss);
const biggest = lazy.map((f) => [f, brotli(f)]).sort((a, b) => b[1] - a[1])[0];
if (biggest) check(`largest lazy chunk (${biggest[0].replace("assets/", "")})`, biggest[1], BUDGET.lazyChunk);

console.log("\nBundle budget (Brotli):");
for (const [what, size, budget, verdict] of rows) console.log(`  ${what.padEnd(52)} ${size.padStart(9)} / ${budget.padStart(9)}  ${verdict}`);
if (failures.length) {
  console.error(`\nBundle budget exceeded:\n  ${failures.join("\n  ")}\nRun ANALYZE=1 npm run build and open dist/stats.html to see why.`);
  process.exit(1);
}

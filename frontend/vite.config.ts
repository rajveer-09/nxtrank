/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 15 October 2026
 */
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig, type Plugin } from "vite";

/** Writes .br and .gz next to every compressible asset at build time, so the server
 *  (Caddy in production, or the API on its own) sends ready-made compressed files
 *  instead of compressing on every request. No extra dependency: Node's zlib. */
function precompress(): Plugin {
  const compressible = /\.(js|css|html|svg|json|txt|map)$/;
  return {
    name: "precompress",
    apply: "build",
    // After the files are on disk: earlier hooks can still see chunks before Vite's
    // final rewrites (e.g. its __VITE_PRELOAD__ placeholder), so compress what was written.
    writeBundle(options, bundle) {
      const dir = options.dir!;
      for (const fileName of Object.keys(bundle)) {
        if (!compressible.test(fileName)) continue;
        const file = join(dir, fileName);
        const data = readFileSync(file);
        if (data.length < 1024) continue; // not worth it
        writeFileSync(`${file}.br`, brotliCompressSync(data, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }));
        writeFileSync(`${file}.gz`, gzipSync(data, { level: 9 }));
      }
    },
  };
}

/** Preloads the Latin Inter font so text renders in the right font straight away. */
function preloadFont(): Plugin {
  return {
    name: "preload-font",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        const font = Object.keys(ctx.bundle ?? {}).find((f) => /inter-latin-wght-normal-.*\.woff2$/.test(f));
        if (!font) return html;
        return {
          html,
          tags: [{ tag: "link", attrs: { rel: "preload", href: `/${font}`, as: "font", type: "font/woff2", crossorigin: "" }, injectTo: "head" }],
        };
      },
    },
  };
}

// Dev: `npm run dev` on :5173 proxies /api to the backend (`python -m app.cli serve`, :8000).
// Prod: `npm run build` -> dist/ (hashed, pre-compressed assets), served by Caddy or the backend.
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as { version: string };

export default defineConfig({
  // shown in the Guide's credits
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BUILD_DATE__: JSON.stringify(new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })),
  },
  plugins: [
    react(),
    tailwindcss(),
    preloadFont(),
    precompress(),
    // ANALYZE=1 npm run build -> dist/stats.html: what each chunk is made of
    ...(process.env.ANALYZE
      ? [visualizer({ filename: "dist/stats.html", gzipSize: true, brotliSize: true, template: "treemap" }) as Plugin]
      : []),
  ],
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        // libraries change rarely: keep them in their own long-cached chunk
        manualChunks(id) {
          if (/node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@tanstack[\\/](react-query|query-core))[\\/]/.test(id)) return "vendor";
        },
      },
    },
  },
  server: {
    // keep the browser's Host: the API refuses change requests whose Origin isn't its own host
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
});

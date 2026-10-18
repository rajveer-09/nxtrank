/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
// Lighthouse CI: the main pages on a throttled connection, against the budgets below.
// Needs the API with demo data (backend/scripts/seed_demo.py) and a login:
//   LHCI_BASE_URL=http://127.0.0.1:8010 LHCI_EMAIL=... LHCI_PASSWORD=... npx lhci autorun

const base = process.env.LHCI_BASE_URL || "http://127.0.0.1:8010";
const contest = process.env.LHCI_CONTEST || "weekly-contest-351";
// how much slower than this machine the "mid-range laptop" is. 2 on a developer laptop;
// GitHub's runners are already about that slow, so CI sets LHCI_CPU_SLOWDOWN=1
const cpuSlowdown = Number(process.env.LHCI_CPU_SLOWDOWN || 2);

module.exports = {
  ci: {
    collect: {
      url: ["/", "/analytics", "/students", `/contests/${contest}`].map((p) => base + p),
      numberOfRuns: 3, // the median run is judged
      puppeteerScript: "./lighthouse/login.cjs",
      puppeteerLaunchOptions: { args: ["--no-sandbox"] },
      settings: {
        formFactor: "desktop", // staff use laptops
        screenEmulation: { mobile: false, width: 1440, height: 900, deviceScaleFactor: 1, disabled: false },
        // a typical 4G connection and a mid-range laptop
        throttlingMethod: "simulate",
        throttling: { rttMs: 150, throughputKbps: 9000, cpuSlowdownMultiplier: cpuSlowdown },
        // the login cookie is set by login.cjs; don't wipe it between pages
        disableStorageReset: true,
      },
    },
    assert: {
      assertions: {
        "largest-contentful-paint": ["error", { maxNumericValue: 1500 }],
        "cumulative-layout-shift": ["error", { maxNumericValue: 0.1 }],
        "total-blocking-time": ["error", { maxNumericValue: 200 }],
        "categories:accessibility": ["error", { minScore: 0.95 }], // axe-based; every page passes axe today
        "resource-summary:script:size": ["error", { maxNumericValue: 200 * 1024 }], // compressed bytes
      },
    },
    upload: { target: "filesystem", outputDir: ".lighthouseci" },
  },
};

/**
 * Author: Rajveer Sharma
 * © NxtWave
 * Date: 16 October 2026
 */
// Signs in once before Lighthouse measures a page (the pages behind the login are the
// ones worth measuring). Credentials come from LHCI_EMAIL / LHCI_PASSWORD.

module.exports = async (browser, context) => {
  const page = await browser.newPage();
  try {
    await page.goto(new URL("/", context.url).href, { waitUntil: "networkidle2" });
    const password = await page.$("input[type=password]");
    if (!password) return; // already signed in
    if (!process.env.LHCI_EMAIL || !process.env.LHCI_PASSWORD) throw new Error("set LHCI_EMAIL and LHCI_PASSWORD");
    await page.type("input[autocomplete=username]", process.env.LHCI_EMAIL);
    await password.type(process.env.LHCI_PASSWORD);
    await Promise.all([page.waitForSelector("nav a", { timeout: 30000 }), page.click("button[type=submit]")]);
  } finally {
    await page.close();
  }
};

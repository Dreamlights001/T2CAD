import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const browser = await chromium.launch({ channel: "chromium", args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  if (process.argv.includes("--pdf")) {
    await page.goto(pathToFileURL(path.join(root, "docs/course-report.html")).href);
    await page.evaluate(() => Promise.all([...document.images].map(img => img.complete ? Promise.resolve() : new Promise(resolve => { img.onload = resolve; img.onerror = resolve; }))));
    await page.pdf({ path: path.join(root, "docs/course-report.pdf"), format: "A4", printBackground: true, margin: { top: "16mm", bottom: "16mm", left: "14mm", right: "14mm" } });
  } else {
    const runtime = JSON.parse(fs.readFileSync(path.join(root, "logs/runtime.json"), "utf8"));
    const report = JSON.parse(fs.readFileSync(path.join(root, "docs/llm-validation.json"), "utf8"));
    const sample = report.cases.at(-1);
    if (sample.status !== "completed") throw Error("Real model sample has not passed validation");
    await page.addInitScript(id => localStorage.setItem("t2cad-project", id), sample.project_id);
    await page.goto(runtime.frontend);
    await page.locator(".view-bottom").getByText("几何已加载").waitFor();
    await page.waitForFunction(() => {
      const canvas = document.querySelector("canvas"), gl = canvas?.getContext("webgl2");
      if (!gl) return false;
      const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
      gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let colored = 0;
      for (let i = 0; i < pixels.length; i += 4) if (pixels[i + 1] > pixels[i] + 12 && pixels[i + 2] > pixels[i] + 12) colored++;
      return colored > 1000;
    });
    await page.locator(".conversation").evaluate(el => el.scrollTo({ top: el.scrollHeight, behavior: "instant" }));
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(root, "docs/screenshots/llm-flange.png") });
  }
} finally { await browser.close(); }

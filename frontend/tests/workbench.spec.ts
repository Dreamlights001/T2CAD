import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const base = process.env.T2CAD_URL || "http://127.0.0.1:5173";
const output = path.resolve("../docs/screenshots");
test.setTimeout(240000);

test("CAD workbench, dimensions, parameters, history, export and mobile", async ({
  page,
  request,
}) => {
  fs.mkdirSync(output, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const project = await (
    await request.post(base + "/api/projects", {
      data: { name: "界面验收 · 法兰" },
    })
  ).json();
  const job = await (
    await request.post(base + `/api/projects/${project.id}/examples/flange`)
  ).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(base + `/api/jobs/${job.id}`)).json()).status,
      { timeout: 120000 },
    )
    .toBe("completed");
  await page.addInitScript(
    (id) => localStorage.setItem("t2cad-project", id),
    project.id,
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base);
  await expect(page.locator(".view-bottom")).toContainText("几何已加载");
  await expect(page.locator(".dimension-label")).toHaveCount(3);
  const pixelCheck = async () =>
    page.locator("canvas").evaluate((canvas: HTMLCanvasElement) => {
      const gl = canvas.getContext("webgl2")!;
      const w = gl.drawingBufferWidth,
        h = gl.drawingBufferHeight,
        pixels = new Uint8Array(w * h * 4);
      gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      let colored = 0;
      for (let i = 0; i < pixels.length; i += 4)
        if (pixels[i + 1] > pixels[i] + 12 && pixels[i + 2] > pixels[i] + 12)
          colored++;
      return { colored, width: w, height: h };
    });
  await expect
    .poll(async () => (await pixelCheck()).colored)
    .toBeGreaterThan(1000);
  const desktopPixels = await pixelCheck();
  await page.screenshot({ path: path.join(output, "workbench-desktop.png") });
  const canvas = page.locator("canvas"),
    bounds = await canvas.boundingBox();
  const before = await canvas.screenshot();
  await page.mouse.move(
    bounds!.x + bounds!.width / 2,
    bounds!.y + bounds!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(
    bounds!.x + bounds!.width / 2 + 90,
    bounds!.y + bounds!.height / 2 + 30,
    { steps: 12 },
  );
  await page.mouse.up();
  await page.waitForTimeout(400);
  expect(Buffer.compare(before, await canvas.screenshot())).not.toBe(0);
  await page.getByRole("button", { name: "适配视图", exact: true }).click();
  await page.getByRole("button", { name: "尺寸标注", exact: true }).click();
  await expect(page.locator(".dimension-label").first()).toHaveCSS(
    "visibility",
    "hidden",
  );
  await page.getByRole("button", { name: "尺寸标注", exact: true }).click();
  await page.getByRole("button", { name: "参数", exact: true }).click();
  await page
    .getByRole("spinbutton", { name: "中心孔径", exact: true })
    .fill("28");
  await page.getByRole("button", { name: "重新计算", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await (await request.get(base + `/api/projects/${project.id}`)).json())
          .revisions.length,
      { timeout: 60000 },
    )
    .toBe(2);
  await expect(
    page.getByRole("spinbutton", { name: "中心孔径", exact: true }),
  ).toHaveValue("28");
  await page.screenshot({ path: path.join(output, "parameters-desktop.png") });
  await page.getByRole("button", { name: "版本", exact: true }).click();
  await page.getByRole("button", { name: "切换到版本1", exact: true }).click();
  await expect
    .poll(
      async () =>
        (
          await (await request.get(base + `/api/projects/${project.id}`)).json()
        ).revision.design.parameters.find((p: any) => p.name === "bore").value,
    )
    .toBe(24);
  await page.getByRole("button", { name: "播放建模过程", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "暂停回放", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "暂停回放", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出", exact: true }).click();
  await page
    .getByRole("button", { name: "STEP · 精确实体", exact: true })
    .click();
  expect((await download).suggestedFilename()).toBe("model.step");
  await page.getByRole("slider", { name: "建模步骤", exact: true }).fill("7");
  await page.getByRole("button", { name: "设计对话", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "适配视图", exact: true }).click();
  await page.waitForTimeout(300);
  const mobilePixels = await pixelCheck();
  expect(mobilePixels.colored).toBeGreaterThan(500);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(output, "workbench-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
  fs.writeFileSync(
    path.resolve("../docs/browser-validation.json"),
    JSON.stringify(
      {
        desktopPixels,
        mobilePixels,
        errors,
        checks: [
          "render",
          "rotation",
          "dimensions",
          "parameter-rebuild",
          "version-restore",
          "playback",
          "STEP-download",
          "mobile-layout",
        ],
      },
      null,
      2,
    ),
  );
});

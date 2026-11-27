/* 真实 Chromium 端到端（可选的人工/CI 核对，不属于 selftest.py 的 Python 用例）：
 *   A 有解增量 DOM、不重载、滚动位置/未动图层节点保留
 *   B 无解只更新结果
 *   C 两个标签页交错提交（409 -> 重取 /api/state -> 自动补齐重提）
 *   D 另一标签页重置后再提交
 *   E 较旧响应晚到被序号/版本守卫丢弃
 *   F 网络失败保留总图与台账，恢复后可再提交
 *   G 保留对位标记几何更新（合成 delta）
 *
 * 运行：
 *   (cd /tmp/pw && npm init -y && npm i playwright && npx playwright install chromium)
 *   BASE=http://127.0.0.1:5000 NODE_PATH=/tmp/pw/node_modules node tests/browser/e2e.js
 */
const { chromium } = require("playwright");

const BASE = process.env.BASE || "http://127.0.0.1:5000";
let passed = 0, failed = 0;
const failures = [];

function ok(cond, msg) {
  if (cond) { passed++; console.log("  ✓ " + msg); }
  else { failed++; failures.push(msg); console.log("  ✗ " + msg); }
}
async function test(name, fn) {
  console.log("\n" + name);
  try { await fn(); }
  catch (e) {
    failed++; failures.push(name + " :: " + e.message);
    console.log("  ✗ 用例异常: " + e.stack.split("\n").slice(0, 3).join(" | "));
  }
}
async function resetApi() {
  const r = await fetch(BASE + "/api/reset", { method: "POST" });
  return (await r.json()).version;
}
async function newPage(browser, hardErrors) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", (e) => hardErrors.push("pageerror: " + e.message));
  // 409/abort 是用例预期内的协议行为，浏览器会打一条 resource 控制台错误，忽略。
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/i.test(m.text())) {
      hardErrors.push("console.error: " + m.text());
    }
  });
  return page;
}
async function loadFresh(page) {
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = "auto"; });
}
async function fillSolvable(page) {
  await page.click('[data-demo="solvable"]');
  await page.waitForTimeout(450);
}
async function submitViaJs(page) {
  await page.evaluate(() => document.getElementById("align-form").requestSubmit());
}
const ver = (page) => page.evaluate(() => window.MuralApp.getVersion());
const alive = (page) => page.evaluate(() => window.__alive === "yes");
const img2tr = (page) => page.locator('[data-image-id="img2"]').getAttribute("transform");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  await test("[A] 有解提交：增量 DOM、不整页重载、保留总图位置", async () => {
    const R = await resetApi();
    const errors = [];
    const page = await newPage(browser, errors);
    await loadFresh(page);
    await page.evaluate(() => { window.__alive = "yes"; });
    ok(await ver(page) === R, "初始版本 = 重置后的 " + R);

    await fillSolvable(page);
    await page.evaluate(() => {
      window.scrollTo(0, 760);
      const mc = document.querySelector(".map-scroll");
      mc.scrollLeft = 200; mc.scrollTop = 60;
      window.__y = window.scrollY;
      window.__x = mc.scrollLeft; window.__t = mc.scrollTop;
      window.__img0 = document.querySelector('[data-image-id="img0"]');
      window.__img3 = document.querySelector('[data-image-id="img3"]');
    });

    const respP = page.waitForResponse((r) => r.url().includes("/api/submit"));
    await submitViaJs(page);
    const resp = await respP;
    const body = await resp.json();
    ok(resp.status() === 200 && body.status === "applied", "HTTP 200 applied");
    ok(body.version === R + 1, "响应新版本 " + (R + 1) + "（实际 " + body.version + "）");
    ok(body.delta.images.map((i) => i.id).join() === "img2",
      "增量只含移动的 img2：" + body.delta.images.map((i) => i.id));

    await page.waitForSelector("#result.banner-ok", { timeout: 5000 });
    await page.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 1);

    ok(await alive(page), "页面没有整页重载（window 标记保留）");
    const scroll = await page.evaluate(() => ({
      y: window.scrollY, y0: window.__y,
      x: document.querySelector(".map-scroll").scrollLeft, x0: window.__x,
      t: document.querySelector(".map-scroll").scrollTop, t0: window.__t,
    }));
    ok(Math.abs(scroll.y - scroll.y0) <= 2, "窗口滚动位置保留 (" + scroll.y + ")");
    ok(scroll.x === scroll.x0 && scroll.t === scroll.t0,
      "总图滚动视口保留 (" + scroll.x + "," + scroll.t + ")");

    const nodes = await page.evaluate(() => ({
      img0same: window.__img0 === document.querySelector('[data-image-id="img0"]'),
      img3same: window.__img3 === document.querySelector('[data-image-id="img3"]'),
      img0tr: document.querySelector('[data-image-id="img0"]').getAttribute("transform"),
    }));
    ok(nodes.img0same && nodes.img3same, "没动的样片 DOM 图层节点原样保留");
    ok(nodes.img0tr === "translate(0,0)", "基准图 transform 不变（" + nodes.img0tr + "）");
    ok(await img2tr(page) === "translate(800,0)", "img2 图层移动到 translate(800,0)，实际 " + await img2tr(page));

    ok((await page.locator('.crack-row[data-crack-id="LF-03"] [data-role="master"]').textContent())
      .includes("(960, 200)"), "裂缝台账 LF-03 更新为 (960, 200)");
    ok((await page.locator('.crack-row[data-crack-id="LF-04"] [data-role="master"]').textContent())
      .includes("(1120, 90)"), "裂缝台账 LF-04 更新为 (1120, 90)");

    const dw02 = page.locator('.alignment-row[data-code="DW-02"]');
    ok(await dw02.evaluate((tr) => tr.classList.contains("row-withdrawn") &&
      tr.getAttribute("data-status") === "withdrawn"), "台账 DW-02 标为已撤行");
    ok((await dw02.locator('[data-role="status"]').textContent()).includes("已撤下"),
      "DW-02 状态徽标 = 已撤下");
    ok(await page.locator('.alignment-mark[data-mark-code="DW-02"]').count() === 0,
      "撤下的 DW-02 标记从总图消失");
    ok(await page.locator('.alignment-mark[data-mark-code="DW-03"]').count() === 0,
      "撤下的 DW-03 标记从总图消失");
    ok(await page.locator('.alignment-mark[data-mark-code="DW-06"]').count() === 1,
      "新对位 DW-06 标记出现在总图");
    ok((await page.locator("#alignment-total").textContent()).trim() === "6", "台账总数 = 6");
    ok((await page.locator("#run-list .run-item").first().getAttribute("data-run-id")) ===
      String(body.id), "处理记录顶部插入本次 run #" + body.id);
    const resultText = await page.locator("#result").innerText();
    ok(resultText.includes("(960, 200)") && resultText.includes("DW-02"),
      "提交结果含撤下对位与新坐标");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    // 结果内联展开后，按钮仍可真实点击（无浮层遮挡）
    await page.click("#clear-points");
    ok(await page.locator("#readout-a").textContent() === "未点选", "结果展开后“清除点选”仍可点击");
    await page.close();
  });

  await test("[B] 无解提交：总图与台账不变，只更新结果", async () => {
    const R = await resetApi();
    const errors = [];
    const page = await newPage(browser, errors);
    await loadFresh(page);
    const v0 = await ver(page);
    ok(v0 === R, "版本 " + R);
    await page.click('[data-demo="no_solution"]');
    await page.waitForTimeout(400);

    const respP = page.waitForResponse((r) => r.url().includes("/api/submit"));
    await submitViaJs(page);
    const resp = await respP;
    const body = await resp.json();
    ok(body.status === "no_solution" && body.delta === null,
      "响应 no_solution 且 delta=null");
    await page.waitForSelector("#result.banner-fail");
    await page.waitForTimeout(300);
    ok(await ver(page) === v0, "版本号不变（" + v0 + "）");
    ok(await img2tr(page) === "translate(830,20)", "img2 总图位置不变：" + await img2tr(page));
    ok(await page.locator(".alignment-row").count() === 5, "台账仍是 5 条");
    ok(await page.locator(".alignment-row.row-withdrawn").count() === 0, "没有撤下标记");
    ok(await page.locator(".alignment-mark").count() === 5, "总图对位标记仍是 5 个");
    ok((await page.locator("#result").innerText()).includes("无解"), "显示无解结果");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await page.close();
  });

  await test("[C] 两标签页交错提交：B 遇 409 后重取完整状态并补齐提交", async () => {
    const R = await resetApi();
    const errors = [];
    const a = await newPage(browser, errors);
    const b = await newPage(browser, errors);
    await loadFresh(a); await loadFresh(b);

    let bStateFetches = 0;
    b.on("request", (req) => { if (req.url().includes("/api/state")) bStateFetches++; });

    await fillSolvable(a);
    await submitViaJs(a);
    await a.waitForSelector("#result.banner-ok");
    await a.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 1);
    ok(true, "标签页 A 提交成功到 v" + (R + 1));

    await fillSolvable(b);
    const staleP = b.waitForResponse((r) => r.url().includes("/api/submit") && r.status() === 409);
    await submitViaJs(b);
    ok((await (await staleP).json()).status === "stale_state", "B 第一次提交收到 409 stale_state");
    await b.waitForSelector("#result.banner-ok", { timeout: 6000 });
    await b.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 2);
    ok(bStateFetches >= 1, "B 重新请求了完整 /api/state（" + bStateFetches + " 次）");
    ok(await b.locator("#sync-notice").isVisible(), "B 显示状态补齐提示");
    ok((await b.locator("#alignment-total").textContent()).trim() === "7", "B 补齐并重提后台账共 7 条");
    ok(await img2tr(b) === "translate(800,0)", "B 总图已更新到最新 img2 位置");
    // 5 条生效对位：DW-01/04/05 + A 的 DW-06 + B 的 DW-07
    ok(await b.locator(".alignment-mark").count() === 5,
      "B 总图生效标记层为 5 个（实际 " + await b.locator(".alignment-mark").count() + "）");

    ok(await ver(a) === R + 1, "A 仍显示自己的新版本 v" + (R + 1) + "，未被 B 干扰");
    ok(await a.locator("#result").getAttribute("data-run-id") === "1", "A 的结果仍是 run #1");
    ok(await b.locator("#result").getAttribute("data-run-id") === "2", "B 的结果是新的 run #2");

    const server = await (await fetch(BASE + "/api/state")).json();
    ok(server.version === R + 2 && server.alignments.length === 7,
      "服务器最终 v" + (R + 2) + " / 7 条对位");
    ok(errors.length === 0, "两页无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await a.close(); await b.close();
  });

  await test("[D] A 重置示例后，B 下次提交补齐完整总图与台账", async () => {
    const R = await resetApi();
    const errors = [];
    const a = await newPage(browser, errors);
    const b = await newPage(browser, errors);
    await loadFresh(a); await loadFresh(b);

    await fillSolvable(a);
    await submitViaJs(a);
    await a.waitForSelector("#result.banner-ok");
    await a.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 1);

    a.on("dialog", (d) => d.accept());
    await Promise.all([
      a.waitForNavigation({ waitUntil: "networkidle" }),
      a.click('#reset-form button[type="submit"]'),
    ]);
    ok(await ver(a) === R + 2, "A 重置后整页加载，版本 v" + (R + 2) +
      "（实际 " + await ver(a) + "）");
    ok(await a.locator(".alignment-row").count() === 5, "A 台账恢复 5 条");

    await fillSolvable(b);
    const stateP = b.waitForResponse((r) => r.url().includes("/api/state"));
    await submitViaJs(b);
    const stateResp = await stateP;
    const stateJson = await stateResp.json();
    ok(stateJson.alignments.length === 5 && stateJson.runs.length === 0,
      "B 重取的是重置后的完整状态（5 对位 / 0 记录）");
    await b.waitForSelector("#result.banner-ok", { timeout: 6000 });
    await b.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 3);
    ok((await b.locator(".alignment-row").count()) === 6, "B 补齐后提交，台账变 6 条");
    ok(await img2tr(b) === "translate(800,0)", "B 在种子版上正确应用移位");
    const txt = await b.locator("#result").innerText();
    ok(txt.includes("DW-06") && txt.includes("DW-02"), "B 结果为种子上的标准 DW-06 方案");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await a.close(); await b.close();
  });

  await test("[E] 较旧响应晚到：新状态先显示，旧响应到达后被丢弃", async () => {
    const R = await resetApi();
    const errors = [];
    const page = await newPage(browser, errors);
    await loadFresh(page);

    let submitNo = 0;
    let firstFetched;
    const fetchedP = new Promise((res) => { firstFetched = res; });
    let releaseFirst;
    const releaseP = new Promise((res) => { releaseFirst = res; });

    await page.route("**/api/submit", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      submitNo += 1;
      if (submitNo === 1) {
        const response = await route.fetch();
        firstFetched();
        await releaseP;
        return route.fulfill({ response });
      }
      return route.continue();
    });

    await fillSolvable(page);
    await submitViaJs(page);
    await fetchedP;

    await submitViaJs(page);
    await page.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 2,
      { timeout: 8000 });
    const runIdWhileNew = await page.locator("#result").getAttribute("data-run-id");
    ok(runIdWhileNew === "2", "新状态已显示 run #2（实际 " + runIdWhileNew + "）");

    releaseFirst();
    await page.waitForTimeout(800);
    ok(await ver(page) === R + 2, "旧响应到达后版本仍是 v" + (R + 2));
    ok(await page.locator("#result").getAttribute("data-run-id") === "2",
      "页面保持已经显示的新结果 run #2，未被旧响应覆盖");
    ok(await page.evaluate(() => window.MuralApp.getLatestSeq()) === 2,
      "请求序号守卫 latestSeq=2");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await page.unroute("**/api/submit").catch(() => {});
    await page.close();
  });

  await test("[F] 请求失败保留现状，解除故障后可再提交", async () => {
    const R = await resetApi();
    const errors = [];
    const page = await newPage(browser, errors);
    await loadFresh(page);

    await page.route("**/api/submit", (route) => route.abort("failed"));
    await fillSolvable(page);
    await submitViaJs(page);
    await page.waitForSelector("#net-error:not([hidden])", { timeout: 5000 });
    ok(true, "显示网络失败提示");
    ok(await ver(page) === R, "失败后版本不变");
    ok(await img2tr(page) === "translate(830,20)", "失败后总图平移不变：" + await img2tr(page));
    ok(await page.locator(".alignment-row").count() === 5, "失败后台账仍是 5 条");
    ok(await page.locator("#result").count() === 0, "没有写入结果区");

    await page.unroute("**/api/submit");
    await submitViaJs(page);
    await page.waitForSelector("#result.banner-ok", { timeout: 6000 });
    await page.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 1);
    ok(await img2tr(page) === "translate(800,0)", "故障恢复后重新提交成功，总图更新");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await page.close();
  });

  await test("[G] 保留对位标记更新：合成 delta 移动 img1，DW-01/DW-04 标记几何刷新", async () => {
    const R = await resetApi();
    const errors = [];
    const page = await newPage(browser, errors);
    await loadFresh(page);

    await page.route("**/api/submit", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 99, status: "applied", version: R + 1,
        summary: "合成响应：img1 平移 10px 以验证保留标记",
        removed: [],
        shifted: [{ id: "LF-02", code: "LF-02", old: [650, 140], new: [660, 140], delta: [10, 0] }],
        new_alignment: { id: 99, code: "DW-99" },
        delta: {
          images: [{ id: "img1", name: "x", file: "samples/img1.svg", w: 480, h: 360, is_base: 0, tx: 410, ty: 0 }],
          cracks: [{ id: "LF-02", code: "LF-02", image_id: "img1", master_x: 660, master_y: 140 }],
          removed_alignment_ids: [],
          alignment_marks_remove: [],
          alignment_marks_upsert: [
            { id: 1, code: "DW-01", reviewed: 1, residual: 0,
              axm: 860, aym: 160, bxm: 860, bym: 160, mx: 860, my: 160 },
            { id: 4, code: "DW-04", reviewed: 1, residual: 0,
              axm: 630, aym: 330, bxm: 630, bym: 330, mx: 630, my: 330 },
          ],
          alignments_upsert: [{
            id: 99, code: "DW-99", image_a: "img0", image_b: "img1",
            ax: 1, ay: 2, bx: 3, by: 4, reviewed: 1, status: "active",
            origin: "submitted", note: "合成",
          }],
          alignment_total: 6,
        },
      }),
    }));

    const oldDw01X = await page.locator('.alignment-mark[data-mark-id="1"] line').getAttribute("x1");
    await fillSolvable(page);
    await submitViaJs(page);
    await page.waitForFunction((v) => window.MuralApp.getVersion() === v, R + 1);

    ok(await page.locator('[data-image-id="img1"]').getAttribute("transform") ===
      "translate(410,0)", "img1 图层按 delta 移动");
    const newDw01X = await page.locator('.alignment-mark[data-mark-id="1"] line').getAttribute("x1");
    ok(newDw01X !== oldDw01X && Math.abs(parseFloat(newDw01X) - 860) < 0.01,
      "保留对位 DW-01 标记端点更新到 860（x1=" + newDw01X + "，原 " + oldDw01X + "）");
    const dw04x = await page.locator('.alignment-mark[data-mark-id="4"] line').getAttribute("x1");
    ok(Math.abs(parseFloat(dw04x) - 630) < 0.01, "保留对位 DW-04 标记也更新");
    ok((await page.locator('.crack-row[data-crack-id="LF-02"] [data-role="master"]').textContent())
      .includes("(660, 140)"), "随 img1 移动的已贴签裂缝台账坐标也刷新（delta 驱动）");
    ok(await page.locator('.alignment-row[data-code="DW-99"]').count() === 1, "新对位行已插入台账");
    ok(errors.length === 0, "无 JS 错误" + (errors.length ? "：" + errors.join(" | ") : ""));
    await page.close();
  });

  await browser.close();
  console.log("\n========================================");
  console.log("E2E 结果：" + passed + " 通过，" + failed + " 失败");
  if (failed) { console.log("失败项：\n - " + failures.join("\n - ")); process.exit(1); }
})().catch((e) => { console.error("HARNESS ERROR", e); process.exit(2); });

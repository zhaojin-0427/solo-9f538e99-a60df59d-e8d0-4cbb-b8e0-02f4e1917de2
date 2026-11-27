/* 点选两张样片同一处纹样：把点击位置换算成 480x360 的样片坐标。
 *
 * 提交走 JSON 增量协议，不再整页重载：
 *   - 请求带 base_version（浏览器当前总图/台账版本）；
 *   - 版本一致：applied 只下发 delta（本次变动）+ run 结果，没动的样片
 *     图层节点完全保留；no_solution 时 delta=null，只更新结果；
 *   - 409 stale_state：另一标签页已提交/重置 -> 重取 /api/state 完整
 *     总图与台账，整体补齐后按同一载荷自动重试一次；
 *   - latestSeq + 版本号双重守卫：较旧的响应晚到时直接丢弃；
 *   - 网络/服务器失败：不做任何乐观改动，当前总图与台账原样保留。
 */
(function () {
  "use strict";

  var W = 480;
  var H = 360;
  var SVG_NS = "http://www.w3.org/2000/svg";

  /* ---------- 初始状态（Jinja 注入的整份 state） ---------- */
  var initialState = {};
  var stateEl = document.getElementById("page-state");
  if (stateEl) {
    try { initialState = JSON.parse(stateEl.textContent) || {}; }
    catch (e) { initialState = {}; }
  }
  var demos = initialState.demos || {};
  var baseVersion = Number.isFinite(Number(initialState.version))
    ? Number(initialState.version) : null;

  /* 每次新的提交尝试 +1；响应回来时序号不符说明已有更新的提交，丢弃旧响应。 */
  var latestSeq = 0;

  /* 供自动化/自测观察当前前端版本与请求守卫序号（只读用途）。 */
  window.MuralApp = {
    getVersion: function () { return baseVersion; },
    getLatestSeq: function () { return latestSeq; },
    hasResult: function () { return !!document.getElementById("result"); }
  };

  /* ============================================================
   * 小工具
   * ============================================================ */
  function esc(v) {
    if (v === null || v === undefined) { return ""; }
    return String(v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* 与 Jinja 的 num 过滤器一致：整数不带 .0，浮点保留一位。 */
  function num(v) {
    var f = parseFloat(v);
    if (!isFinite(f)) { return v === null || v === undefined ? "" : String(v); }
    if (Math.abs(f - Math.round(f)) < 1e-6) { return String(Math.round(f)); }
    return f.toFixed(1);
  }

  /* SVG 属性用坐标：最多两位小数，去掉无意义的 0。 */
  function attrNum(v) {
    var f = Math.round(parseFloat(v) * 100) / 100;
    return String(f);
  }

  function $(sel, root) { return (root || document).querySelector(sel); }

  function svgNode(html) {
    var tmp = document.createElementNS(SVG_NS, "svg");
    tmp.innerHTML = html.trim();
    return tmp.firstElementChild;
  }

  function flashEl(el, cls) {
    if (!el || !el.classList) { return; }
    var c = cls || "is-flash";
    el.classList.remove(c);
    /* 强制重排以重启动画 */
    void (el.getBoundingClientRect ? el.getBoundingClientRect().width : 0);
    el.classList.add(c);
    setTimeout(function () {
      if (el.classList) { el.classList.remove(c); }
    }, 1800);
  }

  /* ============================================================
   * 点选台逻辑（原有行为保持不变）
   * ============================================================ */
  var sides = {
    a: {
      select: document.getElementById("image-a"),
      canvas: document.getElementById("canvas-a"),
      img: document.getElementById("preview-a"),
      hint: document.getElementById("hint-a"),
      marker: document.getElementById("marker-a"),
      readout: document.getElementById("readout-a"),
      inputX: document.getElementById("in-ax"),
      inputY: document.getElementById("in-ay"),
      point: null
    },
    b: {
      select: document.getElementById("image-b"),
      canvas: document.getElementById("canvas-b"),
      img: document.getElementById("preview-b"),
      hint: document.getElementById("hint-b"),
      marker: document.getElementById("marker-b"),
      readout: document.getElementById("readout-b"),
      inputX: document.getElementById("in-bx"),
      inputY: document.getElementById("in-by"),
      point: null
    }
  };

  function renderPoint(side) {
    var s = sides[side];
    if (s.point) {
      var p = s.point;
      s.marker.hidden = false;
      s.marker.style.left = (p.x / W * 100) + "%";
      s.marker.style.top = (p.y / H * 100) + "%";
      if (document.activeElement !== s.inputX) { s.inputX.value = p.x; }
      if (document.activeElement !== s.inputY) { s.inputY.value = p.y; }
      s.readout.textContent = "已标记 ✓";
    } else {
      s.marker.hidden = true;
      s.readout.textContent = "未点选";
      s.inputX.value = "";
      s.inputY.value = "";
    }
  }

  function syncFromInputs(side) {
    var s = sides[side];
    var x = parseFloat(s.inputX.value);
    var y = parseFloat(s.inputY.value);
    if (isFinite(x) && isFinite(y)) {
      x = Math.max(0, Math.min(W, x));
      y = Math.max(0, Math.min(H, y));
      s.point = { x: x, y: y };
      s.marker.hidden = false;
      s.marker.style.left = (x / W * 100) + "%";
      s.marker.style.top = (y / H * 100) + "%";
      s.readout.textContent = "已标记 ✓";
    } else {
      s.point = null;
      s.marker.hidden = true;
      s.readout.textContent = "未点选";
    }
  }

  function clearPoint(side) {
    sides[side].point = null;
    renderPoint(side);
  }

  function loadSelectedImage(side, keepPoint) {
    var s = sides[side];
    var opt = s.select.options[s.select.selectedIndex];
    var src = opt && opt.dataset ? opt.dataset.src : "";
    if (src) {
      s.img.src = src;
      s.canvas.hidden = false;
      s.hint.hidden = true;
    } else {
      s.img.removeAttribute("src");
      s.canvas.hidden = true;
      s.hint.hidden = false;
    }
    if (!keepPoint) { clearPoint(side); }
  }

  function eventToCoords(side, ev) {
    var s = sides[side];
    var rect = s.img.getBoundingClientRect();
    if (!rect.width || !rect.height) { return null; }
    var x = (ev.clientX - rect.left) * (W / rect.width);
    var y = (ev.clientY - rect.top) * (H / rect.height);
    x = Math.max(0, Math.min(W, Math.round(x)));
    y = Math.max(0, Math.min(H, Math.round(y)));
    return { x: x, y: y };
  }

  Object.keys(sides).forEach(function (side) {
    var s = sides[side];
    s.select.addEventListener("change", function () { loadSelectedImage(side, false); });

    document.getElementById("stage-" + side).addEventListener("click", function (ev) {
      if (!s.select.value) { return; }
      var p = eventToCoords(side, ev);
      if (p) { s.point = p; renderPoint(side); hideJsError(); }
    });

    s.inputX.addEventListener("input", function () { syncFromInputs(side); });
    s.inputY.addEventListener("input", function () { syncFromInputs(side); });
  });

  /* 表单服务端校验失败重渲染时，恢复已有点选 */
  ["a", "b"].forEach(function (side) {
    var s = sides[side];
    if (s.select.value) {
      loadSelectedImage(side, true);
      var vx = parseFloat(s.inputX.value);
      var vy = parseFloat(s.inputY.value);
      if (isFinite(vx) && isFinite(vy)) {
        s.point = { x: Math.round(vx), y: Math.round(vy) };
        renderPoint(side);
      }
    }
  });

  var clearBtn = document.getElementById("clear-points");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      clearPoint("a");
      clearPoint("b");
      hideJsError();
    });
  }

  document.querySelectorAll("[data-demo]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.getAttribute("data-demo");
      var d = demos[key];
      if (!d) { return; }
      sides.a.select.value = d.image_a;
      sides.b.select.value = d.image_b;
      loadSelectedImage("a", false);
      loadSelectedImage("b", false);
      sides.a.point = { x: d.ax, y: d.ay };
      sides.b.point = { x: d.bx, y: d.by };
      renderPoint("a");
      renderPoint("b");
      hideJsError();
      hideNetError();
      document.getElementById("submit").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  /* ============================================================
   * 提示条
   * ============================================================ */
  var form = document.getElementById("align-form");
  var jsError = document.getElementById("js-error");
  var netError = document.getElementById("net-error");
  var syncNotice = document.getElementById("sync-notice");
  var submitStatus = document.getElementById("submit-status");

  function showJsError(msg) {
    if (!jsError) { return; }
    jsError.textContent = msg;
    jsError.hidden = false;
  }
  function hideJsError() { if (jsError) { jsError.hidden = true; } }

  function showNetError(msg) {
    if (!netError) { return; }
    netError.textContent = msg;
    netError.hidden = false;
  }
  function hideNetError() { if (netError) { netError.hidden = true; } }

  function showSyncNotice(msg) {
    if (!syncNotice) { return; }
    syncNotice.textContent = msg;
    syncNotice.hidden = false;
  }
  function hideSyncNotice() { if (syncNotice) { syncNotice.hidden = true; } }

  function setBusy(on) {
    if (!form) { return; }
    form.setAttribute("aria-busy", on ? "true" : "false");
    var btn = form.querySelector('button[type="submit"]');
    if (btn) { btn.classList.toggle("is-loading", !!on); }
    if (submitStatus) {
      submitStatus.textContent = on ? "提交中…" : "";
      submitStatus.hidden = !on;
    }
  }

  function validateForm() {
    if (!sides.a.select.value || !sides.b.select.value) {
      return "请先选择两张照片。";
    }
    if (sides.a.select.value === sides.b.select.value) {
      return "请选择两张不同的照片。";
    }
    function hasCoord(s) {
      var x = parseFloat(s.inputX.value);
      var y = parseFloat(s.inputY.value);
      return isFinite(x) && isFinite(y) && x >= 0 && y >= 0 && x <= W && y <= H;
    }
    if (!hasCoord(sides.a) || !hasCoord(sides.b)) {
      return "请分别在 A、B 两张照片上点击同一处纹样（或在 X/Y 框中填入 0–480、0–360 的坐标）。";
    }
    return null;
  }

  function collectPayload() {
    return {
      image_a: sides.a.select.value,
      image_b: sides.b.select.value,
      ax: parseFloat(sides.a.inputX.value),
      ay: parseFloat(sides.a.inputY.value),
      bx: parseFloat(sides.b.inputX.value),
      by: parseFloat(sides.b.inputY.value)
    };
  }

  /* ============================================================
   * SVG 对位标记
   * ============================================================ */
  function markHtml(m) {
    var color = m.reviewed ? "#1d6f42" : "#c8862d";
    var residual = parseFloat(m.residual) || 0;
    var badDot = residual > 2
      ? '<circle cx="' + attrNum(m.bxm) + '" cy="' + attrNum(m.bym) +
        '" r="5.5" fill="#d62828" stroke="#fff" stroke-width="1.5"/>'
      : "";
    return '' +
      '<g class="alignment-mark" data-mark-id="' + m.id +
        '" data-mark-code="' + esc(m.code) + '">' +
        "<title>" + esc(m.code) + "（" + (m.reviewed ? "已复核" : "未复核") +
          "）残差 " + esc(m.residual) + "px</title>" +
        '<line x1="' + attrNum(m.axm) + '" y1="' + attrNum(m.aym) +
          '" x2="' + attrNum(m.bxm) + '" y2="' + attrNum(m.bym) +
          '" stroke="' + color + '" stroke-width="2.4" stroke-dasharray="7 5" opacity="0.9"/>' +
        '<rect x="' + (attrNum(m.axm) - 5) + '" y="' + (attrNum(m.aym) - 5) +
          '" width="10" height="10" transform="rotate(45 ' +
          attrNum(m.axm) + " " + attrNum(m.aym) +
          ')" fill="' + color + '" stroke="#fff" stroke-width="1.6"/>' +
        badDot +
        '<text x="' + attrNum(m.mx + 9) + '" y="' + attrNum(m.my - 9) +
          '" font-size="12.5" font-weight="800" fill="' + color +
          '" stroke="#f6efdd" stroke-width="3.4" paint-order="stroke">' +
          esc(m.code) + "</text>" +
      "</g>";
  }

  /* ============================================================
   * 台账行渲染（整份补齐时用）
   * ============================================================ */
  function alignmentRowHtml(a) {
    var withdrawn = a.status === "withdrawn";
    var reviewBadge = a.reviewed
      ? '<span class="badge badge-reviewed">已复核</span>'
      : '<span class="badge badge-open">未复核</span>';
    var statusBadge = withdrawn
      ? '<span class="badge badge-withdrawn">已撤下</span>'
      : '<span class="badge badge-active">生效中</span>';
    var source = a.origin === "submitted" ? "修复师新提交" : "内置旧对位";
    var note = (a.note ? " · " + esc(a.note) : "");
    var code = a.code || ("#" + a.id);
    return '' +
      '<tr class="alignment-row' + (withdrawn ? " row-withdrawn" : "") +
        '" data-alignment-id="' + a.id + '" data-code="' + esc(code) +
        '" data-status="' + esc(a.status) + '">' +
        "<td><strong>" + esc(code) + "</strong></td>" +
        "<td>" + esc(a.image_a) + "</td>" +
        "<td>(" + num(a.ax) + ", " + num(a.ay) + ")</td>" +
        "<td>" + esc(a.image_b) + "</td>" +
        "<td>(" + num(a.bx) + ", " + num(a.by) + ")</td>" +
        '<td class="muted">(' + num(a.ax - a.bx) + ", " + num(a.ay - a.by) + ")</td>" +
        '<td data-role="review">' + reviewBadge + "</td>" +
        '<td data-role="status">' + statusBadge + "</td>" +
        '<td class="muted small">' + source + note + "</td>" +
      "</tr>";
  }

  function crackRowHtml(c) {
    var tagBadge = c.tagged
      ? '<span class="badge badge-tagged">已贴签 · 坐标固定</span>'
      : '<span class="badge badge-plain">未贴签</span>';
    return '' +
      '<tr class="crack-row" data-crack-id="' + esc(c.id) +
        '" data-code="' + esc(c.code) + '">' +
        "<td><strong>" + esc(c.code) + "</strong></td>" +
        "<td>" + esc(c.image_id) + "</td>" +
        "<td>(" + num(c.x) + ", " + num(c.y) + ")</td>" +
        '<td class="new-coord" data-role="master">(' +
          num(c.master_x) + ", " + num(c.master_y) + ")</td>" +
        "<td>" + tagBadge + "</td>" +
        '<td class="muted small">' + esc(c.note || "") + "</td>" +
      "</tr>";
  }

  function historyItemHtml(r) {
    var badge = r.status === "applied"
      ? '<span class="badge badge-applied">有解·已更新</span>'
      : '<span class="badge badge-nosolution">无解·未改动</span>';
    return '' +
      '<li class="run-item run-' + esc(r.status) + '" data-run-id="' + r.id + '">' +
        '<a href="/?run=' + r.id + '#result">' +
          '<span class="run-id">#' + r.id + "</span>" +
          badge +
          '<span class="run-summary">' + esc(r.summary || "") + "</span>" +
          "<time>" + esc(r.created_at || "") + "</time>" +
        "</a>" +
      "</li>";
  }

  /* ============================================================
   * 结果横幅渲染（与 Jinja 模板结构保持一致）
   * ============================================================ */
  function resultHtml(run) {
    var closeBtn =
      '<button type="button" class="result-close" id="result-close" ' +
      'aria-label="收起结果" title="收起结果">×</button>';
    var liveOk =
      '<p class="js-live-note">⚡ 页面未整页刷新：总图、台账与本结果已在同一版状态上一起更新。</p>';
    var liveFail =
      '<p class="js-live-note">⚡ 页面未整页刷新：仅更新本结果，总图与台账保持不变。</p>';

    if (run.status === "applied") {
      var removed = run.removed || [];
      var shifted = run.shifted || [];

      var removedBody;
      if (removed.length) {
        removedBody =
          '<table class="mini-table"><thead><tr><th>编号</th>' +
          "<th>两张照片上的点选</th><th>说明</th></tr></thead><tbody>" +
          removed.map(function (r) {
            return "<tr><td>" +
              '<span class="badge badge-withdrawn">' + esc(r.code) + "</span></td>" +
              "<td>" + esc(r.image_a) + " (" + num(r.ax) + ", " + num(r.ay) + ")<br>" +
              esc(r.image_b) + " (" + num(r.bx) + ", " + num(r.by) + ")</td>" +
              "<td>" + esc(r.note || "") + "</td></tr>";
          }).join("") +
          "</tbody></table>";
      } else {
        removedBody = '<p class="muted">无需撤下任何对位（0 条）。</p>';
      }

      var shiftedBody;
      if (shifted.length) {
        shiftedBody =
          '<table class="mini-table"><thead><tr><th>裂缝</th><th>旧坐标</th>' +
          "<th>新坐标</th><th>位移</th></tr></thead><tbody>" +
          shifted.map(function (c) {
            return "<tr><td><strong>" + esc(c.code) + "</strong></td>" +
              "<td>(" + num(c.old[0]) + ", " + num(c.old[1]) + ")</td>" +
              '<td class="new-coord">(' + num(c.new[0]) + ", " + num(c.new[1]) + ")</td>" +
              '<td class="muted">(' + num(c.delta[0]) + ", " + num(c.delta[1]) + ")</td></tr>";
          }).join("") +
          "</tbody></table>";
      } else {
        shiftedBody = '<p class="muted">没有裂缝发生移位。</p>';
      }

      return "" +
        '<section class="banner banner-ok result-inline" id="result" ' +
          'data-run-id="' + run.id + '">' + closeBtn +
          "<h2>✅ 已采用新对位并更新总图（记录 #" + run.id + "）</h2>" +
          liveOk +
          '<p class="summary-line">' + esc(run.summary || "") + "</p>" +
          '<div class="result-grid">' +
            '<div class="result-box"><h3>撤下的对位（' + removed.length +
              " 条，均为未复核）</h3>" + removedBody + "</div>" +
            '<div class="result-box"><h3>移位裂缝的新总图坐标（' + shifted.length +
              " 条）</h3>" + shiftedBody +
              '<p class="muted small">已贴签裂缝受硬约束保护，坐标均照旧不变。</p>' +
            "</div>" +
          "</div>" +
        "</section>";
    }

    var tried = (run.tried_candidates === null || run.tried_candidates === undefined)
      ? "—" : run.tried_candidates;
    return "" +
      '<section class="banner banner-fail result-inline" id="result" ' +
        'data-run-id="' + run.id + '">' + closeBtn +
        "<h2>⚠️ 无解：保留原图与全部对位（记录 #" + run.id + "）</h2>" +
        liveFail +
        "<p>" + esc(run.reason || "枚举所有可行撤法后仍无法满足约束。") + "</p>" +
        '<p class="muted small">本次尝试了 ' + esc(tried) +
          " 种撤法（仅允许撤下至多 2 条未复核对位）。数据库中的总图位置与对位台账均未改动，" +
          "提交的点选也未写入对位表。</p>" +
      "</section>";
  }

  function showResult(run) {
    /* 全页只保留一个 #result：JS 提交后把结果渲染到提交按钮上方的内联槽，
       修复师不用离开当前总图查看位置；同时清空顶部槽避免重复 id/重复文案。 */
    var topSlot = document.getElementById("result-slot");
    var inlineSlot = document.getElementById("inline-result-slot");
    if (topSlot) { topSlot.innerHTML = ""; }
    if (!inlineSlot) {
      if (topSlot) { topSlot.innerHTML = resultHtml(run); }
      return;
    }
    inlineSlot.innerHTML = resultHtml(run);
    var panel = document.getElementById("result");
    if (panel) { flashEl(panel, "is-flash"); }
  }

  /* 收起按钮（事件委托，innerHTML 重渲染后仍然有效） */
  document.addEventListener("click", function (ev) {
    var btn = ev.target && ev.target.closest ? ev.target.closest("#result-close") : null;
    if (!btn) { return; }
    var panel = document.getElementById("result");
    if (panel) {
      panel.hidden = true;
      panel.classList.remove("result-inline");
    }
  });

  /* ============================================================
   * 增量 patch：只动本次变化的节点，没动的样片图层原样保留
   * ============================================================ */
  function patchImages(delta) {
    (delta.images || []).forEach(function (im) {
      var g = $('.map-image-layer[data-image-id="' + im.id + '"]');
      if (!g) { return; }
      g.setAttribute("transform", "translate(" + im.tx + "," + im.ty + ")");
      g.setAttribute("data-tx", String(im.tx));
      g.setAttribute("data-ty", String(im.ty));
      var coord = $("[data-role='coord']", g);
      if (coord) { coord.textContent = num(im.tx) + ", " + num(im.ty); }
      flashEl(g, "layer-flash");
    });
  }

  function patchMarks(delta) {
    var layer = $(".align-layer");
    if (!layer) { return; }

    (delta.alignment_marks_remove || delta.removed_alignment_ids || [])
      .forEach(function (id) {
        var old = $('.alignment-mark[data-mark-id="' + id + '"]', layer);
        if (old && old.parentNode) { old.parentNode.removeChild(old); }
      });

    (delta.alignment_marks_upsert || []).forEach(function (m) {
      var node = svgNode(markHtml(m));
      var old = $('.alignment-mark[data-mark-id="' + m.id + '"]', layer);
      if (old) {
        old.parentNode.replaceChild(node, old);
      } else {
        layer.appendChild(node);
      }
      flashEl(node, "mark-flash");
    });
  }

  function patchCracks(delta) {
    (delta.cracks || []).forEach(function (c) {
      var row = $('.crack-row[data-crack-id="' + c.id + '"]');
      if (!row) { return; }
      var cell = $("[data-role='master']", row);
      if (cell) {
        cell.textContent = "(" + num(c.master_x) + ", " + num(c.master_y) + ")";
        flashEl(cell, "cell-flash");
      }
    });
  }

  function markAlignmentWithdrawn(row) {
    row.classList.add("row-withdrawn");
    row.setAttribute("data-status", "withdrawn");
    var cell = $("[data-role='status']", row);
    if (cell) {
      cell.innerHTML = '<span class="badge badge-withdrawn">已撤下</span>';
    }
  }

  function patchAlignmentLedger(run, delta) {
    var tb = document.getElementById("alignment-tbody");
    if (!tb) { return; }

    (run.removed || []).forEach(function (r) {
      var row = $('.alignment-row[data-alignment-id="' + r.id + '"]', tb);
      if (row) {
        markAlignmentWithdrawn(row);
        flashEl(row, "row-flash");
      }
    });

    (delta.alignments_upsert || []).forEach(function (a) {
      var sel = '.alignment-row[data-alignment-id="' + a.id + '"]';
      var row = $(sel, tb);
      if (row) {
        row.outerHTML = alignmentRowHtml(a);
      } else {
        tb.insertAdjacentHTML("beforeend", alignmentRowHtml(a));
      }
      flashEl($(sel, tb), "row-flash");
    });

    var total = document.getElementById("alignment-total");
    if (total && delta.alignment_total !== undefined && delta.alignment_total !== null) {
      total.textContent = String(delta.alignment_total);
    }
  }

  function prependHistory(run) {
    var box = document.getElementById("history-container");
    if (!box) { return; }
    var empty = document.getElementById("history-empty");
    if (empty && empty.parentNode) { empty.parentNode.removeChild(empty); }
    var ul = document.getElementById("run-list");
    if (!ul) {
      box.innerHTML = '<ul class="run-list" id="run-list"></ul>';
      ul = document.getElementById("run-list");
    }
    ul.insertAdjacentHTML("afterbegin", historyItemHtml(run));
  }

  /* 有解：总图、台账、记录、结果在同一个同步执行段内一起切换。 */
  function applyApplied(body) {
    var delta = body.delta || {};
    patchImages(delta);
    patchMarks(delta);
    patchCracks(delta);
    patchAlignmentLedger(body, delta);
    prependHistory(body);
    showResult(body);
    if (typeof body.version === "number") {
      baseVersion = body.version;
      document.body.setAttribute("data-state-version", String(baseVersion));
    }
  }

  /* 无解且总图未变：只切换结果。 */
  function applyNoSolution(body) {
    showResult(body);
    if (typeof body.version === "number") {
      baseVersion = body.version;
      document.body.setAttribute("data-state-version", String(baseVersion));
    }
  }

  /* ============================================================
   * 409：重取完整总图与台账并整体补齐（保留点选台状态）
   * ============================================================ */
  function adoptFullState(st) {
    if (!st) { return; }
    initialState = st;
    if (Number.isFinite(Number(st.version))) {
      baseVersion = Number(st.version);
      document.body.setAttribute("data-state-version", String(baseVersion));
    }

    (st.images || []).forEach(function (im) {
      var g = $('.map-image-layer[data-image-id="' + im.id + '"]');
      if (!g) { return; }
      g.setAttribute("transform", "translate(" + im.tx + "," + im.ty + ")");
      g.setAttribute("data-tx", String(im.tx));
      g.setAttribute("data-ty", String(im.ty));
      var coord = $("[data-role='coord']", g);
      if (coord) { coord.textContent = num(im.tx) + ", " + num(im.ty); }
    });

    var layer = $(".align-layer");
    if (layer) {
      layer.innerHTML = (st.alignment_marks || []).map(markHtml).join("");
    }

    var aTb = document.getElementById("alignment-tbody");
    if (aTb) {
      aTb.innerHTML = (st.alignments || []).map(alignmentRowHtml).join("");
    }
    var total = document.getElementById("alignment-total");
    if (total) { total.textContent = String((st.alignments || []).length); }

    var cTb = document.getElementById("crack-tbody");
    if (cTb) {
      cTb.innerHTML = (st.cracks || []).map(crackRowHtml).join("");
    }

    var hBox = document.getElementById("history-container");
    if (hBox) {
      if (!(st.runs || []).length) {
        hBox.innerHTML =
          '<p class="muted" id="history-empty" style="padding:12px 18px 18px;">暂无提交记录。</p>';
      } else {
        hBox.innerHTML = '<ul class="run-list" id="run-list">' +
          st.runs.map(historyItemHtml).join("") + "</ul>";
      }
    }
  }

  /* ============================================================
   * 提交网络流程
   * ============================================================ */
  function postSubmit(payload) {
    return fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        base_version: baseVersion,
        image_a: payload.image_a,
        image_b: payload.image_b,
        ax: payload.ax, ay: payload.ay,
        bx: payload.bx, by: payload.by
      })
    });
  }

  function fetchFullState() {
    return fetch("/api/state", {
      headers: { "Accept": "application/json" },
      cache: "no-store",
      credentials: "same-origin"
    }).then(function (r) {
      if (!r.ok) { throw new Error("state HTTP " + r.status); }
      return r.json();
    });
  }

  function runSubmit(payload, seq, attempt) {
    var responseVersion = null;
    postSubmit(payload).then(function (resp) {
      return resp.json().catch(function () { return null; }).then(function (body) {
        return { status: resp.status, ok: resp.ok, body: body };
      });
    }).then(function (r) {
      /* 已有更新的提交/重置发生：整个旧响应链（含补齐重试）全部丢弃。 */
      if (seq !== latestSeq) { return; }

      var body = r.body || {};

      /* 版本过期：另一标签页提交过或重置过。重取完整状态补齐后重试一次。 */
      if (r.status === 409 || body.status === "stale_state") {
        showSyncNotice("总图或台账已在另一个标签页被改动，正在重取完整总图与台账…");
        return fetchFullState().then(function (st) {
          if (seq !== latestSeq) { return; }
          adoptFullState(st);
          showSyncNotice("已补齐另一标签页的最新总图与台账，并按最新状态重新提交本次对位。");
          if (attempt < 1) {
            return runSubmit(payload, seq, attempt + 1);
          }
          setBusy(false);
          showNetError("状态在提交过程中再次变化，请核对最新总图与台账后再次点击提交。");
        }).catch(function () {
          if (seq !== latestSeq) { return; }
          setBusy(false);
          showNetError("状态已过期，且重取完整总图/台账失败，请刷新页面后重试。");
        });
      }

      if (r.status === 400 || body.status === "invalid") {
        setBusy(false);
        showNetError(body.error || "提交内容无效，请检查点选坐标。");
        return;
      }

      if (!r.ok || !r.body) {
        /* 5xx / 网关错误 / 非 JSON：不触碰当前总图与台账。 */
        setBusy(false);
        showNetError("提交失败（HTTP " + r.status +
          "），当前总图与台账保持不变，请稍后重试。");
        return;
      }

      responseVersion = typeof body.version === "number" ? body.version : null;
      /* 版本守卫：晚到的旧版本响应不得覆盖页面已经显示的新状态。 */
      if (responseVersion !== null && baseVersion !== null &&
          responseVersion < baseVersion) {
        setBusy(false);
        return;
      }

      setBusy(false);
      if (body.status === "applied") {
        applyApplied(body);
      } else if (body.status === "no_solution") {
        applyNoSolution(body);
      } else {
        showNetError(body.error || "未知响应，当前总图与台账保持不变。");
      }
    }).catch(function (err) {
      /* 网络中断 / fetch reject：保留当前总图和台账。 */
      if (seq !== latestSeq) { return; }
      setBusy(false);
      showNetError("网络请求失败，当前总图与台账保持不变" +
        (err && err.message ? "（" + err.message + "）" : "") + "。");
    });
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      /* 无论原生校验是否通过，都先阻止整页提交；JS 自行发 JSON。
         若 JS 整体加载失败，没有这个监听器，浏览器仍走传统 PRG。 */
      ev.preventDefault();
      hideJsError();
      hideNetError();

      var problem = validateForm();
      if (problem) {
        showJsError(problem);
        return;
      }

      var payload = collectPayload();
      latestSeq += 1;
      setBusy(true);
      runSubmit(payload, latestSeq, 0);
    });
  }
})();

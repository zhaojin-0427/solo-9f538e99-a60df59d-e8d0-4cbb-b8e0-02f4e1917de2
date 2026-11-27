/* 点选两张样片同一处纹样：把点击位置换算成 480x360 的样片坐标。 */
(function () {
  "use strict";

  var W = 480;
  var H = 360;

  var demos = {};
  var demoEl = document.getElementById("demo-data");
  if (demoEl) {
    try { demos = JSON.parse(demoEl.textContent) || {}; } catch (e) { demos = {}; }
  }

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

  /* 手动改数字框时同步标记 */
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

    // 在整个 stage 上监听，点到 marker 也不丢事件
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

  /* 清除点选 */
  var clearBtn = document.getElementById("clear-points");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      clearPoint("a");
      clearPoint("b");
      hideJsError();
    });
  }

  /* 示例填充 */
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
      document.getElementById("submit").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  /* 提交前校验 */
  var form = document.getElementById("align-form");
  var jsError = document.getElementById("js-error");
  function showJsError(msg) {
    if (!jsError) { return; }
    jsError.textContent = msg;
    jsError.hidden = false;
  }
  function hideJsError() {
    if (jsError) { jsError.hidden = true; }
  }

  if (form) {
    form.addEventListener("submit", function (ev) {
      if (!sides.a.select.value || !sides.b.select.value) {
        ev.preventDefault();
        showJsError("请先选择两张照片。");
        return;
      }
      if (sides.a.select.value === sides.b.select.value) {
        ev.preventDefault();
        showJsError("请选择两张不同的照片。");
        return;
      }
      function hasCoord(s) {
        var x = parseFloat(s.inputX.value);
        var y = parseFloat(s.inputY.value);
        return isFinite(x) && isFinite(y) && x >= 0 && y >= 0 && x <= W && y <= H;
      }
      if (!hasCoord(sides.a) || !hasCoord(sides.b)) {
        ev.preventDefault();
        showJsError("请分别在 A、B 两张照片上点击同一处纹样（或在 X/Y 框中填入 0–480、0–360 的坐标）。");
        return;
      }
      hideJsError();
    });
  }
})();

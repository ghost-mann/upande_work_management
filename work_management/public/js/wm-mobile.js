/* Work Management on phones (2026-11-27).
 *
 * Loaded by every screen after its own script. Below 768px it:
 *  - adds a bottom bar (Home, Plan, Assign, Work, Pay) in place of the top links,
 *  - turns tables into labelled cards, or lets wide grids scroll with the first
 *    column pinned,
 *  - folds filter rows behind a "Filters" button,
 *  - stacks multi-column layouts and wraps rows that overflow.
 * It keeps doing so as the screens re-render (MutationObserver). Above 767px it
 * does nothing at all, so desktop is untouched. Styles: css/wm-mobile.css.
 * Spec: docs/superpowers/specs/2026-11-27-wm-mobile-web-design.md
 */
(function () {
  "use strict";
  var MQ = window.matchMedia ? window.matchMedia("(max-width: 767px)") : { matches: false };
  if (/KaitetWorkApp/i.test(navigator.userAgent || "")) document.documentElement.classList.add("wm-in-app");
  if (!MQ.matches) return;

  var ROOTS = "#wmp, #wpp, #wap, #acp, #wpay";
  var FILTERS = ".pex-filters, .lfb, .fbar, .filters, [id$='-filters'], .wm-filters";
  var NAV = [
    ["/work-management", "Home", '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>'],
    ["/work-planner", "Plan", '<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M8 2v4M16 2v4M3 10h18"/>'],
    ["/work-assigner", "Assign", '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.4 3-5.5 6-5.5s5.4 2.1 6 5.5"/><path d="M17 8v6M14 11h6"/>'],
    ["/work-actuals", "Work", '<path d="M4 20h16"/><path d="M6 16l4-5 3 3 5-7"/><circle cx="18" cy="7" r="1.4"/>'],
    ["/work-payment", "Pay", '<rect x="2.5" y="6" width="19" height="13" rx="2.5"/><path d="M2.5 10.5h19"/><path d="M6.5 15h4"/>']
  ];

  function txt(el) { return (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim(); }

  // ---- bottom bar --------------------------------------------------------------
  function bar() {
    if (document.querySelector(".wm-mbar")) return;
    var here = location.pathname.replace(/\/+$/, "") || "/";
    var nav = document.createElement("nav");
    nav.className = "wm-mbar";
    nav.setAttribute("aria-label", "Sections");
    nav.innerHTML = NAV.map(function (n) {
      var on = here === n[0] || here.indexOf(n[0] + "/") === 0;
      return '<a href="' + n[0] + '"' + (on ? ' class="on" aria-current="page"' : "") + '><svg viewBox="0 0 24 24" aria-hidden="true">' +
        n[2] + "</svg><span>" + n[1] + "</span></a>";
    }).join("");
    document.body.appendChild(nav);
  }

  // ---- tables ------------------------------------------------------------------
  function headerLabels(table) {
    var rows = table.tHead ? table.tHead.rows : [];
    var head = rows.length ? rows[rows.length - 1] : null;
    if (!head) {
      var first = table.rows[0];
      if (first && first.cells.length && Array.prototype.every.call(first.cells, function (c) { return c.tagName === "TH"; })) head = first;
    }
    if (!head) return null;
    var out = [];
    Array.prototype.forEach.call(head.cells, function (c) {
      var span = parseInt(c.getAttribute("colspan") || "1", 10) || 1;
      for (var i = 0; i < span; i++) out.push(txt(c));
    });
    return { labels: out, row: head };
  }

  function isWide(table, cols) {
    if (table.closest(".wm-m-keep")) return true;
    if (/grid|matrix|cal|sheet|wide|heat/i.test(table.className + " " + (table.id || "") + " " + (table.parentElement && table.parentElement.id || ""))) return true;
    var body = table.tBodies[0] || table;
    var r = body.rows[0];
    if (!r) return cols >= 9;
    var inputs = r.querySelectorAll("input:not([type=checkbox]):not([type=radio]), select").length;
    if (inputs >= 3) return true;
    return cols >= 16;
  }

  // a grid whose columns are days or dates (calendars, worker-by-day sheets)
  function dateColumns(labels) {
    var n = labels.filter(function (l) {
      return /^(\d{1,2}|mon|tue|wed|thu|fri|sat|sun|[mtwfs])\b/i.test(l) || /\d{4}-\d{2}-\d{2}|\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/i.test(l);
    }).length;
    return labels.length >= 5 && n >= labels.length / 2;
  }

  function scrollWrap(table) {
    var p = table.parentElement;
    if (!p) return;
    if (p.children.length === 1 && !p.classList.contains("wm-m-cardwrap")) { p.classList.add("wm-m-scroll"); return; }
    if (p.classList.contains("wm-m-scroll")) return;
    var w = document.createElement("div");
    w.className = "wm-m-scroll";
    p.insertBefore(w, table);
    w.appendChild(table);
  }

  function cardify(table, labels, headRow) {
    var rows = Array.prototype.filter.call(table.rows, function (r) { return r !== headRow && !(table.tHead && table.tHead.contains(r)); });
    rows.forEach(function (r) {
      if (r.getAttribute("data-wmm") === "1" && r.cells.length && r.cells[0].hasAttribute("data-label")) return;
      var col = 0;
      var cells = Array.prototype.slice.call(r.cells);
      cells.forEach(function (c, i) {
        var label = labels[col] || "";
        col += parseInt(c.getAttribute("colspan") || "1", 10) || 1;
        if (!c.hasAttribute("data-label")) c.setAttribute("data-label", label);
        var onlyButtons = c.querySelector("button, .btn, a.btn") && !txt(c).replace(/\s/g, "").length ? true :
          (c.querySelectorAll("button, .btn").length >= 1 && txt(c).length <= 40 && i === cells.length - 1);
        if (onlyButtons) c.classList.add("wm-m-actions");
      });
      if (cells.length > 1 && !cells[0].hasAttribute("colspan") && !cells[0].classList.contains("wm-m-actions")) {
        // the first cell names the row -- unless it is only a row number
        var first = txt(cells[0]);
        if (/^\d{1,3}$/.test(first) && cells.length > 2) { cells[0].style.display = "none"; if (!cells[1].classList.contains("wm-m-actions")) cells[1].classList.add("wm-m-head"); }
        else cells[0].classList.add("wm-m-head");
      }
      r.setAttribute("data-wmm", "1");
    });
  }

  function tables(root) {
    root.querySelectorAll("table").forEach(function (t) {
      if (t.closest(".wm-mbar")) return;
      var h = headerLabels(t);
      var cols = h ? h.labels.length : (t.rows[0] ? t.rows[0].cells.length : 0);
      if (cols <= 1) return;
      var mode = t.getAttribute("data-wmm-mode");
      if (!mode) {
        mode = (!h || isWide(t, cols) || dateColumns(h.labels)) ? "wide" : "cards";
        t.setAttribute("data-wmm-mode", mode);
        t.classList.add(mode === "wide" ? "wm-m-wide" : "wm-m-cards");
      }
      if (mode === "wide") scrollWrap(t);
      else cardify(t, h.labels, h.row);
    });
  }

  // ---- filters -----------------------------------------------------------------
  function activeCount(box) {
    var n = 0;
    box.querySelectorAll("input, select").forEach(function (i) {
      if (i.type === "checkbox" || i.type === "radio") { if (i.checked) n++; return; }
      if (i.tagName === "SELECT" ? i.selectedIndex > 0 : !!(i.value || "").trim()) n++;
    });
    return n;
  }

  function filters(root) {
    root.querySelectorAll(FILTERS).forEach(function (box) {
      if (box.classList.contains("wm-m-filters")) { upd(box); return; }
      var fields = box.querySelectorAll("input, select").length;
      if (fields < 2) return;
      box.classList.add("wm-m-filters", "wm-m-folded");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "wm-m-ftoggle";
      b.onclick = function () { box.classList.toggle("wm-m-folded"); upd(box); };
      box.insertBefore(b, box.firstChild);
      box.addEventListener("change", function () { upd(box); });
      upd(box);
    });
    function upd(box) {
      var b = box.querySelector(":scope > .wm-m-ftoggle");
      if (!b) return;
      var n = activeCount(box);
      var open = !box.classList.contains("wm-m-folded");
      b.innerHTML = (open ? "Hide filters" : "Filters") + (n ? ' <span class="n">' + n + "</span>" : "");
    }
  }

  // ---- layout: grids and rows that do not fit ------------------------------------
  function layout(root) {
    var vw = document.documentElement.clientWidth;
    root.querySelectorAll("div, section, form, header, ul").forEach(function (el) {
      if (el.closest(".wm-mbar, .wm-m-scroll, table") || el.classList.contains("kpis")) return;
      var cs = window.getComputedStyle(el);
      if (cs.display === "grid" && !el.classList.contains("wm-m-stack") && !el.classList.contains("wm-m-two")) {
        var tracks = cs.gridTemplateColumns.split(" ").filter(Boolean).length;
        // calendars and other dense grids (5+ columns) keep their shape
        if (tracks >= 2 && tracks <= 4 && !/cal|month|week|heat/i.test(el.className + " " + (el.id || ""))) {
          var kids = Array.prototype.slice.call(el.children);
          var tiles = kids.length >= 3 && kids.every(function (k) { return txt(k).length <= 90 && !k.querySelector("table, textarea, select"); });
          el.classList.add(tiles && tracks >= 3 ? "wm-m-two" : "wm-m-stack");
        }
      } else if (cs.display === "flex" && cs.flexWrap === "nowrap" && cs.flexDirection.indexOf("row") === 0 &&
                 el.scrollWidth > el.clientWidth + 4 && !el.matches(".tabs, .pex-tabs, .subtabs, [id$='-tabs'], .wm-top, .wm-top *")) {
        el.classList.add("wm-m-wrap");
      }
      if (el.offsetWidth > vw && !el.matches(".wm-top, .wm-canvas")) el.classList.add("wm-m-full");
    });
  }

  // ---- run, and keep up with re-renders --------------------------------------------
  var busy = false, timer = null;
  function enhance() {
    if (busy) return;
    busy = true;
    try {
      bar();
      document.querySelectorAll(ROOTS).forEach(function (root) {
        tables(root);
        filters(root);
        layout(root);
      });
      // a dialog open full screen: hide the bottom bar under it
      var open = Array.prototype.some.call(document.querySelectorAll(".modal, .submodal, .pex-modal, #wa-subdialog, [id$='-subdialog'], #wa-late"),
        function (d) { var cs = window.getComputedStyle(d); return cs.display !== "none" && cs.visibility !== "hidden" && d.offsetHeight > 200; });
      document.body.classList.toggle("wm-m-dialog", open);
      // dialogs live outside the roots on some screens
      document.querySelectorAll(".modal, .submodal, .pex-modal, #wa-subdialog, [id$='-subdialog'], [id$='-dialog']").forEach(function (d) {
        tables(d); layout(d);
      });
    } catch (e) {
      if (window.console) console.warn("wm-mobile", e);
    } finally {
      busy = false;
    }
  }
  function soon() { clearTimeout(timer); timer = setTimeout(enhance, 120); }

  function start() {
    enhance();
    var mo = new MutationObserver(function (list) {
      if (busy) return;
      for (var i = 0; i < list.length; i++) {
        if (list[i].addedNodes && list[i].addedNodes.length) { soon(); return; }
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
    var mo2 = new MutationObserver(function () { if (!busy) soon(); });
    document.querySelectorAll(".modal, .submodal, .pex-modal, #wa-subdialog, [id$='-subdialog']").forEach(function (d) {
      mo2.observe(d, { attributes: true, attributeFilter: ["style", "class"] });
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

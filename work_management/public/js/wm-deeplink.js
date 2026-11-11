// ONE LINK CONVENTION FOR EVERY SCREEN: ?tab=<tab>&ref=<document name>
//
//   /work-planner?tab=appr&ref=WM-KenTrout Farm-00042
//
// `tab` picks the tab; `ref` opens that document's detail once its list has
// loaded. Notification emails build these with wm_screen_url(doc) -- see
// work_management/links.py -- so a reviewer lands on the document and the
// action they have to take, not on a blank New Request form.
//
// Each screen calls WMDeepLink.start() from its buildTabs() with the tabs the
// reader actually has. Everything here is the same for every screen: it asks
// the server where the document is (and whether the reader may see it), shows
// the right tab, narrows the list's search box to the name so no filter can
// hide it, and clicks its row open. Anything that fails says so in one line.
(function(WM){
  var P = new URLSearchParams(location.search);
  var started = null;   // the tab the link chose, once start() has run

  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }

  // A short line at the top of the page. Fixed, so it needs nothing from the
  // screen's own layout, and dismissible.
  function notice(msg){
    var box = document.getElementById("wm-dl-note");
    if(!box){
      box = document.createElement("div");
      box.id = "wm-dl-note";
      box.setAttribute("role", "status");
      box.style.cssText = "position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:10000;"+
        "max-width:calc(100% - 32px);width:560px;box-sizing:border-box;padding:10px 14px;border-radius:10px;"+
        "background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;font-size:12.5px;line-height:1.4;"+
        "box-shadow:0 6px 24px rgba(0,0,0,.12);display:flex;gap:10px;align-items:flex-start";
      document.body.appendChild(box);
    }
    box.innerHTML = '<span style="flex:1">'+esc(msg)+'</span>'+
      '<button type="button" aria-label="Dismiss" style="border:0;background:none;font-size:16px;line-height:1;cursor:pointer;color:inherit">&times;</button>';
    box.querySelector("button").onclick = function(){ box.parentNode && box.parentNode.removeChild(box); };
  }

  function locate(ref, doctype){
    var q = "name="+encodeURIComponent(ref)+(doctype?("&doctype="+encodeURIComponent(doctype)):"");
    return fetch("/api/method/work_management.links.locate?"+q, {
      credentials: "same-origin", headers: {"Accept": "application/json"}
    }).then(function(r){ return r.json(); }).then(function(j){ return (j && j.message) || {ok:0}; });
  }

  // Does this table row carry `ref` in one of its cells? A name may hold a
  // space (WM-KenTrout Farm-00042), so the cell is compared whole -- or as a
  // prefix followed by something that cannot continue a name's counter.
  function rowFor(panel, ref){
    var rows = panel.querySelectorAll("tr");
    for(var i=0;i<rows.length;i++){
      var tr = rows[i];
      if(tr.classList.contains("xd") || tr.classList.contains("detailrow")) continue;
      var tds = tr.children;
      for(var j=0;j<tds.length;j++){
        var t = (tds[j].textContent||"").trim();
        if(t===ref) return tr;
        if(t.indexOf(ref)===0 && !/[0-9A-Za-z]/.test(t.charAt(ref.length))) return tr;
      }
    }
    return null;
  }

  // Wait for `ref`'s row to appear in `panel`, then open it. Lists load
  // asynchronously and redraw on every filter change, so this watches the
  // panel instead of hooking every screen's renderer.
  function openRow(panel, ref, what){
    if(!panel) return;
    var searched = false, done = false, failTimer = null;
    function finish(){ done = true; obs.disconnect(); clearTimeout(failTimer); clearTimeout(giveUp); }
    function step(){
      if(done) return;
      clearTimeout(failTimer);
      if(panel.querySelector(".loading") || panel.classList.contains("loading")) return;
      var q = panel.querySelector('[data-f="q"]');
      if(q && !searched){
        searched = true;
        q.value = ref;
        q.dispatchEvent(new Event("input", {bubbles:true}));
      }
      var tr = rowFor(panel, ref);
      if(tr){
        finish();
        tr.click();
        tr.style.outline = "2px solid #f59e0b";
        tr.style.outlineOffset = "-2px";
        try { tr.scrollIntoView({block:"center"}); } catch(e){}
        return;
      }
      // the list has settled without it: say so rather than leave a list the
      // reader has to search by eye
      failTimer = setTimeout(function(){
        if(done || rowFor(panel, ref)) return;
        finish();
        notice(ref+" is not in "+(what||"this list")+" any more. It may have moved on to another step.");
      }, 1200);
    }
    var obs = new MutationObserver(step);
    obs.observe(panel, {childList:true, subtree:true});
    var giveUp = setTimeout(function(){
      if(done) return;
      finish();
      notice("Could not find "+ref+" in "+(what||"this list")+".");
    }, 20000);
    step();
  }

  // opts:
  //   tabs        the tab keys THIS reader has, in order
  //   labels      {tab: label}, for messages
  //   defaultTab  where a page with no link opens
  //   show(tab)   the screen's own showTab
  //   panel(tab)  the element holding that tab's list
  //   doctypes    the doctypes this screen opens; the first is the default
  //   alias       {param: tab}: an older link shape, e.g. {mp:"mp"} for ?mp=<name>
  //   fallbackTab where a ref goes when neither the link's tab nor the one the
  //               document is in now is the reader's -- their own list
  //   prepare(info, tab)  optional; runs before the tab is shown, e.g. to pick
  //               the approval queue the document waits in. May return
  //               {tab: another tab, open: false when the screen opens the
  //               document itself}.
  WM.start = function(opts){
    var tabs = opts.tabs || [];
    // a second buildTabs() -- the planner redraws its tabs when the rates
    // check answers -- keeps the tab the link chose instead of resetting it
    if(started){ opts.show(tabs.indexOf(started)>=0 ? started : opts.defaultTab); return; }
    var tab = P.get("tab") || "", ref = P.get("ref") || "";
    Object.keys(opts.alias||{}).forEach(function(k){
      if(!ref && P.get(k)){ ref = P.get(k); tab = tab || opts.alias[k]; }
    });
    var linkTab = tabs.indexOf(tab)>=0 ? tab : "";
    if(!ref){
      started = linkTab || opts.defaultTab;
      if(tab && !linkTab && opts.tabs.length) notice("That tab is not available to you, so the screen opened on its first tab.");
      opts.show(started);
      return;
    }
    var doctypes = opts.doctypes || [];
    started = linkTab || opts.defaultTab;   // until the server answers
    locate(ref, doctypes.length===1 ? doctypes[0] : null).then(function(info){
      if(!info.ok || (doctypes.length && doctypes.indexOf(info.doctype)<0)){
        notice(info.message || (ref+" could not be opened. It may have been deleted, or you may not have access to it."));
        opts.show(started);
        return;
      }
      // the link's tab when the reader has it; else where the document is now;
      // else the reader's own list
      var t = linkTab || (tabs.indexOf(info.tab)>=0 ? info.tab : "") || opts.fallbackTab || opts.defaultTab;
      var openList = true;
      var r = opts.prepare ? opts.prepare(info, t) : null;
      if(r){ if(r.tab) t = r.tab; if(r.open===false) openList = false; }
      started = t;
      opts.show(t);
      if(openList) openRow(opts.panel(t), info.name, (opts.labels||{})[t]);
    }).catch(function(){
      notice("Could not open "+ref+". Check your connection and reload the page.");
      opts.show(started);
    });
  };
  WM.notice = notice;
  WM.locate = locate;
  WM.params = P;
})(window.WMDeepLink = window.WMDeepLink || {});

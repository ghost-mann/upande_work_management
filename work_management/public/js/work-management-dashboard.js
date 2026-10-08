(function(){
  var NS="http://www.w3.org/2000/svg";
  var SUBS_ROWS=[];
  // Sticky headers for the capped/scrollable sections (All Records + Substitutions),
  // so column headers stay pinned while rows scroll inside the fixed-height container.
  (function injectStickyCss(){
    if(document.getElementById("wm-compact-css")) return;
    var st=document.createElement("style");
    st.id="wm-compact-css";
    st.textContent=
      "#pex-list thead th, #wm-subs thead th, #cb-list thead th{position:sticky;top:0;z-index:2;background:#fff;box-shadow:0 1px 0 #e4e4e4}"+
      "#pex-list table, #wm-subs table, #cb-list table{border-collapse:collapse}"+
      "#pex-list::-webkit-scrollbar, #wm-subs::-webkit-scrollbar, #cb-list::-webkit-scrollbar{width:9px;height:9px}"+
      "#pex-list::-webkit-scrollbar-thumb, #wm-subs::-webkit-scrollbar-thumb, #cb-list::-webkit-scrollbar-thumb{background:#cfcfcf;border-radius:5px}"+
      // top KPI strip + cost totals cards
      ".kpis{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 14px}"+
      ".kpi{flex:1 1 120px;min-width:110px;border:1px solid #e4e4e4;border-radius:6px;padding:10px 12px;background:#fafafa}"+
      ".kpi .k{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#777;font-weight:600;margin-bottom:4px}"+
      ".kpi .v{font-size:20px;font-weight:700;color:#0a0a0a;line-height:1.1}.kpi .u{font-size:10px;color:#999}"+
      ".cb-totals{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 14px}"+
      ".cb-tot-card{flex:1 1 130px;min-width:120px;border:1px solid #e4e4e4;border-radius:6px;padding:10px 12px;background:#fafafa}"+
      ".cb-tot-card span{display:block;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#777;font-weight:600;margin-bottom:4px}"+
      ".cb-tot-card b{font-size:18px;font-weight:700;color:#0a0a0a}"+
      ".cb-tot-card.paid b{color:#0a7a43}.cb-tot-card.out b{color:#b91c1c}"+
      // BETA corner ribbon (fixed, diagonal, top-right)
      "#wm-beta-ribbon{position:fixed;top:0;right:0;width:150px;height:150px;overflow:hidden;z-index:9999;pointer-events:none}"+
      "#wm-beta-ribbon span{position:absolute;display:block;width:210px;padding:6px 0;background:#0a0a0a;box-shadow:0 2px 6px rgba(0,0,0,.25);color:#fff;font:600 10px/1.3 system-ui,-apple-system,'Segoe UI',sans-serif;letter-spacing:.1em;text-transform:uppercase;text-align:center;right:-52px;top:30px;transform:rotate(45deg)}";
    document.head.appendChild(st);
    if(!document.getElementById("wm-beta-ribbon")){
      var rb=document.createElement("div");
      rb.id="wm-beta-ribbon";
      rb.innerHTML='<span>In development</span>';
      (document.body||document.documentElement).appendChild(rb);
    }
  })();

  function call(args){
    var p=new URLSearchParams();
    for(var k in args){ if(args[k]!=null) p.append(k,args[k]); }
    return fetch("/api/method/wm_dashboard?"+p.toString(),{method:"GET",headers:{"Accept":"application/json"},credentials:"same-origin"})
      .then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
      .then(function(j){ return j.message||{}; })
      .then(function(d){ rememberFarms(d); return d; });
  }
  // This installation's farms come from Work Management Settings, never from a
  // list written into the page: it ships to projects whose farms are not these
  // ones. Every response that carries a farm list refreshes the cache, and the
  // pickers below read it. Some responses send farms as row objects, so only
  // strings count.
  var FARM_LIST=[];
  function rememberFarms(d){
    if(d && d.farms && d.farms.length && typeof d.farms[0]==="string"){ FARM_LIST=d.farms.slice(); }
  }
  function farmOptions(selected){
    return [""].concat(FARM_LIST).map(function(f){
      return '<option value="'+esc(f)+'"'+(selected===f?' selected':'')+'>'+(f||("All "+esc(TX("top_plural","Farms")).toLowerCase()))+'</option>';
    }).join("");
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function money(n){ if(n==null||isNaN(n)) return "—"; if(Math.abs(n)>=1000000) return (n/1000000).toLocaleString("en-KE",{maximumFractionDigits:2})+"M"; if(Math.abs(n)>=1000) return (n/1000).toLocaleString("en-KE",{maximumFractionDigits:1})+"k"; return fmt(n); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  // What this installation calls the levels. Falls back to the shipped wording
  // so the screen still reads correctly if the template has not loaded.
  var TXN = (window.WM_TAXONOMY || {});
  function TX(key, fallback) { return TXN[key] || fallback; }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function el(id){ return document.getElementById(id); }
  function svgEl(t,a,x){ var e=document.createElementNS(NS,t); for(var k in a) e.setAttribute(k,a[k]); if(x!=null) e.textContent=x; return e; }
  function toast(m){ var t=el("wm-toast"); if(!t) return; t.textContent=m; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2000); }
  function kpi(k,v,u){ return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="u">'+(u||"")+'</div></div>'; }
  function num(v){ v=Number(v); return isNaN(v)?0:v; }

  // ── master plans: progress and money, plan by plan ───────────────────────
  // The old card drew one long track per plan and put a "Complete" figure beside
  // it that measured something else: the track was money, the figure quantity, so
  // 47% of the money sat next to "71%" and nobody could say which was true. Both
  // are true, so both are shown and both are named -- WORK DONE (each activity's
  // output against its target, capped so one over-delivered line cannot hide one
  // never started) and BUDGET USED (confirmed pay against the plan's value).
  //
  // Neither means much without time. A plan two days into its week at 20% is fine;
  // the same 20% a fortnight after it ended is not. So each plan gets a status read
  // against the share of its period that has passed, and the list can be cut to
  // the plans that need someone: behind, or over budget.
  //
  // A row is a summary. Opening it loads everything under that plan -- its
  // activities, the requests raised, the crews, the recorded actuals, the people
  // who did the work and the payment runs that carry it -- from mp_detail.
  var PC = { from:null, to:null, farm:"", quick:"8w", seq:0, chip:"all", open:{}, rows:[] };
  // a running plan is Behind once work done trails the share of its days gone by
  // this many points; an ended plan is Done from this share of its work
  var PC_BEHIND_MARGIN = 15;
  var PC_DONE_AT = 90;
  var PC_CHIPS = [["all","All"],["running","In progress"],["behind","Behind"],["short","Ended short"],["over","Over budget"]];
  var PC_STATUS = {
    upcoming:{label:"Upcoming", cls:"st-up"},
    ontrack:{label:"On track", cls:"st-ok"},
    behind:{label:"Behind", cls:"st-bad"},
    done:{label:"Done", cls:"st-ok"},
    short:{label:"Ended short", cls:"st-warn"}
  };
  (function injectAnCss(){
    if(document.getElementById("wm-an-css")) return;
    var st=document.createElement("style");
    st.id="wm-an-css";
    st.textContent=
      "#wmp .std-sub{display:block;font-size:10px;font-weight:500;color:#8a8780;margin-top:1px;white-space:normal;letter-spacing:0;text-transform:none}"+
      "#wmp .ss-sub{margin-top:3px;font-size:10.5px;color:var(--ink);font-weight:600;text-align:center;max-width:120px;line-height:1.3}"+
      "#wmp .ss-rail{flex-direction:column}"+
      "#wmp .ss-cap{display:block;margin-top:4px;font-size:9.5px;color:var(--mute);text-align:center;line-height:1.25;white-space:nowrap}"+
      "#wmp .an-sum{font-size:12px;color:#52514e;margin:2px 0 10px;line-height:1.55}"+
      "#wmp .an-sum b{color:var(--ink)}#wmp .an-sum b.an-up{color:#006300}#wmp .an-sum b.an-down{color:#b91c1c}"+
      "#wmp .an-leg{display:flex;gap:14px;flex-wrap:wrap;font-size:10.5px;color:#52514e;margin:0 0 4px}"+
      "#wmp .an-leg span{display:inline-flex;align-items:center;gap:6px}"+
      "#wmp .an-leg i{display:inline-block;width:12px;height:10px;border-radius:3px}"+
      "#wmp .an-leg i.tk{height:0;border-top:2.4px solid #1a1a18;border-radius:2px;width:16px}"+
      "#wmp .an-leg i.av{height:0;border-top:1.4px dashed #1a1a18;border-radius:0;width:16px;opacity:.6}";
    document.head.appendChild(st);
  })();
  (function injectPcCss(){
    if(document.getElementById("wm-pc-css")) return;
    var st=document.createElement("style");
    st.id="wm-pc-css";
    st.textContent=
      "#wmp .pcw{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px}"+
      "#wmp .pcw label{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:700;display:block;margin-bottom:4px}"+
      "#wmp .pcw input,#wmp .pcw select{font-family:inherit;font-size:12px;border:1px solid var(--line);padding:6px 9px;border-radius:var(--rs);background:#fff;color:var(--ink)}"+
      "#wmp .pcw-quick{display:flex;gap:5px;flex-wrap:wrap;margin-left:auto}"+
      "#wmp .pcw-quick button,#wmp .pc-chips button{font-family:inherit;font-size:10.5px;font-weight:600;background:#fff;color:var(--mute);border:1px solid var(--line);padding:6px 11px;border-radius:999px;cursor:pointer}"+
      "#wmp .pcw-quick button.on,#wmp .pc-chips button.on{background:var(--ink);color:#fff;border-color:var(--ink)}"+
      "#wmp .pc-chips{display:flex;gap:5px;flex-wrap:wrap;margin:14px 0 6px}"+
      "#wmp .pc-chips b{font-weight:700;margin-left:4px;opacity:.75}"+
      "#wmp .pc-tbl{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}"+
      "#wmp .pc-tbl th{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:700;text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}"+
      "#wmp .pc-tbl td{padding:7px 8px;border-bottom:1px solid var(--faint);vertical-align:middle}"+
      "#wmp .pc-tbl .n{text-align:right;white-space:nowrap}"+
      "#wmp .pc-scroll{max-height:520px;overflow:auto;border:1px solid var(--faint);border-radius:8px}"+
      "#wmp .pc-scroll thead th{position:sticky;top:0;z-index:2;background:#fff;box-shadow:0 1px 0 var(--line)}"+
      "#wmp .pc-sum tr.tot td{font-weight:700;border-top:1px solid var(--line)}"+
      "#wmp .pc-sum tr[data-farm]{cursor:pointer}#wmp .pc-sum tr[data-farm]:hover td{background:var(--faint)}"+
      "#wmp .pc-sum tr.sel td{background:#eef2ff}"+
      "#wmp .pc-wk td{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#94a3b8;font-weight:700;padding:14px 8px 5px;border-bottom:1px solid var(--line)}"+
      "#wmp .pc-wk td span{float:right;letter-spacing:.04em}"+
      "#wmp .pc-plan{cursor:pointer}#wmp .pc-plan:hover td{background:#fafafa}"+
      "#wmp .pc-plan.open td{background:#f5f7ff;border-bottom-color:transparent}"+
      "#wmp .pc-plan td:first-child b{display:block}#wmp .pc-plan td:first-child i{font-style:normal;color:var(--mute);font-size:10.5px}"+
      "#wmp .pc-car{color:var(--mute);width:14px;text-align:center}"+
      "#wmp .pc-st{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;white-space:nowrap}"+
      "#wmp .st-up{background:#f1f5f9;color:#475569}#wmp .st-ok{background:#dcfce7;color:#166534}"+
      "#wmp .st-bad{background:#fee2e2;color:#991b1b}#wmp .st-warn{background:#fef3c7;color:#92400e}"+
      "#wmp .pc-flag{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:#fee2e2;color:#991b1b;margin-left:4px;white-space:nowrap}"+
      "#wmp .pc-meter{display:flex;align-items:center;gap:7px;min-width:110px}"+
      "#wmp .pc-meter s{flex:1;height:6px;border-radius:3px;background:var(--faint);position:relative;overflow:hidden;text-decoration:none;min-width:48px}"+
      "#wmp .pc-meter s u{position:absolute;left:0;top:0;bottom:0;border-radius:3px}"+
      "#wmp .pc-meter s em{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink);opacity:.55}"+
      "#wmp .pc-meter b{min-width:36px;text-align:right;font-weight:700}"+
      "#wmp .pc-time{font-size:10.5px;color:var(--mute);white-space:nowrap}"+
      "#wmp .pc-over{color:var(--red);font-weight:700}"+
      "#wmp .pc-det td{padding:0 8px 14px;background:#f5f7ff;border-bottom:1px solid var(--line)}"+
      "#wmp .pcd{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px}"+
      "#wmp .pcd-h{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:11.5px;color:var(--mute);margin-bottom:12px}"+
      "#wmp .pcd-h b{color:var(--ink)}"+
      // the panel sits in a table cell, and the page's cells keep their text on one
      // line: without this the tiles' notes ran out past their borders
      "#wmp .pcd{white-space:normal}"+
      "#wmp .pcd-money{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:8px;margin-bottom:12px}"+
      "#wmp .pcd-m{border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:0;overflow-wrap:anywhere}"+
      "#wmp .pcd-m span{display:block;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:700;line-height:1.35}"+
      "#wmp .pcd-m b{display:block;font-size:15px;margin-top:3px}"+
      "#wmp .pcd-m i{display:block;font-style:normal;font-size:10px;color:var(--mute);margin-top:2px;line-height:1.35}"+
      "#wmp .pcd-m.good b{color:var(--green)}#wmp .pcd-m.warn b{color:var(--amber)}#wmp .pcd-m.bad b{color:var(--red)}"+
      "#wmp .pcd-tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin-bottom:8px}"+
      "#wmp .pcd-tabs button{font-family:inherit;font-size:11px;font-weight:600;color:var(--mute);background:none;border:0;border-bottom:2px solid transparent;padding:7px 10px;cursor:pointer}"+
      "#wmp .pcd-tabs button.on{color:var(--ink);border-bottom-color:var(--ink)}"+
      "#wmp .pcd-tabs button i{font-style:normal;opacity:.6;margin-left:3px}"+
      "#wmp .pcd-pane{max-height:360px;overflow:auto}"+
      "#wmp .pcd-pane tr[data-open]{cursor:pointer}#wmp .pcd-pane tr[data-open]:hover td{background:var(--faint)}"+
      "#wmp .pcd-note{font-size:11px;color:var(--mute);margin:8px 2px 0}"+
      "#wmp .pcd-note.warn{color:var(--amber)}"+
      "#wmp .pc-show-sm{display:none}"+
      "@media(max-width:820px){#wmp .pc-hide-sm{display:none}#wmp .pc-show-sm{display:inline}#wmp .pc-meter{min-width:80px}#wmp .pcd-money{grid-template-columns:repeat(2,minmax(0,1fr))}"+
        // on a phone the list scrolls sideways; the opened panel stays the width of
        // the screen and pinned in view instead of stretching across the whole table
        "#wmp .pc-det .pcd,#wmp .ex-det .pcd{position:sticky;left:4px;width:calc(100vw - 72px);box-sizing:border-box}}";
    document.head.appendChild(st);
  })();

  function localISO(d){ d=new Date(d.getTime()-d.getTimezoneOffset()*60000); return d.toISOString().slice(0,10); }
  function dayNum(iso){ var p=String(iso).split("-"); return Date.UTC(+p[0],+p[1]-1,+p[2])/86400000; }
  function shortDate(iso){
    if(!iso) return "";
    var M=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    // dates arrive as "2026-09-27" or, for a few fields, "2026-09-27 10:42:00"
    var p=String(iso).slice(0,10).split("-"); return (+p[2])+" "+M[(+p[1])-1];
  }
  function pctTxt(v){ return v==null?"—":fmt(v,0)+"%"; }

  // where a plan stands: its share of days gone, its work done, its money, and
  // the one-word status read from those
  function pcAssess(r){
    var today=dayNum(todayISO()), f=dayNum(r.period_from), t=dayNum(r.period_to);
    var total=Math.max(1, t-f+1);
    var gone = today<f ? 0 : Math.min(total, today-f+1);
    var time=gone/total*100;
    var work=r.completion||0;
    // status reads recorded work, approved or not: sign-off runs days behind the
    // field, and a crew working today should not read as Behind until it lands
    var recorded=Math.max(work, r.recorded_completion||0);
    var budget=r.planned_value>0 ? (r.earned_value/r.planned_value*100) : null;
    var over=(r.requested_value>r.planned_value+0.5)||(r.earned_value>r.planned_value+0.5);
    var st;
    if(today<f) st="upcoming";
    else if(today<=t) st=(recorded+PC_BEHIND_MARGIN<time)?"behind":"ontrack";
    else st=(recorded>=PC_DONE_AT)?"done":"short";
    return {status:st, time:time, gone:gone, total:total, work:work, recorded:recorded, budget:budget, over:over,
            running:(today>=f && today<=t)};
  }
  function pcChipMatch(r){
    var a=r._a;
    if(PC.chip==="running") return a.running;
    if(PC.chip==="behind") return a.status==="behind";
    if(PC.chip==="short") return a.status==="short";
    if(PC.chip==="over") return a.over;
    return true;
  }
  // pct solid; more (optional, >= pct) drawn paler behind it -- work recorded but
  // not yet approved; tick marks the share of the plan's days gone by
  function meter(pct, color, tick, more){
    var w=Math.max(0, Math.min(100, pct||0));
    var m=more!=null?Math.max(w, Math.min(100, more)):w;
    return '<span class="pc-meter"'+(m>w?' title="'+fmt(pct,0)+'% approved, '+fmt(more,0)+'% recorded"':'')+'><s>'+
      (m>w?'<u style="width:'+m+'%;background:'+color+';opacity:.3"></u>':'')+
      '<u style="width:'+w+'%;background:'+color+'"></u>'+
      (tick!=null?'<em style="left:'+Math.min(100,tick)+'%" title="share of the plan’s days gone by"></em>':'')+
      '</s><b>'+pctTxt(pct)+'</b></span>';
  }

  function planCompletion(){
    var box=el("wm-plancomp"); if(!box) return;
    var args={action:"plan_completion"};
    if(PC.from) args.from_date=PC.from;
    if(PC.to) args.to_date=PC.to;
    if(PC.farm) args.farm=PC.farm;
    // a date box now fetches on every change, and typing a year fires several
    // (0002, 0020, 0202, 2026); only the newest request may draw the card
    var seq=++PC.seq;
    call(args).then(function(d){
      if(seq!==PC.seq) return;
      PC.rows=(d.plans||[]).map(function(r){ r._a=pcAssess(r); return r; });
      PC.d=d;
      pcDraw();
    }).catch(function(e){
      if(seq!==PC.seq) return;
      box.innerHTML=pcControls({})+'<div class="empty">Could not load the master plans.</div>';
      pcWire(box);
    });
  }

  function pcDraw(){
    var box=el("wm-plancomp"); if(!box) return;
    var rows=PC.rows;
    var h=pcControls(PC.d||{});
    if(!rows.length){
      box.innerHTML=h+'<div class="empty">No master plan starts in these dates'+
        (PC.farm?(' for '+esc(PC.farm)):'')+'. Widen the range, or raise a plan for this period.</div>';
      pcWire(box); return;
    }
    h+=pcSummary(rows);
    var counts={all:rows.length, running:0, behind:0, short:0, over:0};
    rows.forEach(function(r){
      if(r._a.running) counts.running++;
      if(r._a.status==="behind") counts.behind++;
      if(r._a.status==="short") counts.short++;
      if(r._a.over) counts.over++;
    });
    h+='<div class="pc-chips">'+PC_CHIPS.map(function(c){
      return '<button type="button" data-pcchip="'+c[0]+'"'+(PC.chip===c[0]?' class="on"':'')+'>'+c[1]+'<b>'+counts[c[0]]+'</b></button>';
    }).join("")+'</div>';
    var shown=rows.filter(pcChipMatch);
    if(!shown.length){
      box.innerHTML=h+'<div class="empty">No plan here is '+esc((PC_CHIPS.filter(function(c){return c[0]===PC.chip;})[0]||[])[1]||"").toLowerCase()+'.</div>';
      pcWire(box); return;
    }
    // grouped by the week each plan starts, newest first
    var byWeek={}, order=[];
    shown.forEach(function(r){
      if(!byWeek[r.week]){ byWeek[r.week]=[]; order.push(r.week); }
      byWeek[r.week].push(r);
    });
    order.sort().reverse();
    // the list scrolls inside the card; the summary and chips above stay put
    h+='<div class="pc-scroll"><table class="pc-tbl"><thead><tr>'+
       '<th></th><th>Master plan</th><th class="pc-hide-sm">Period</th><th>Status</th>'+
       '<th title="each activity’s output against its target, capped at its own target and weighted by its planned value">Work done</th>'+
       '<th title="confirmed pay against the plan’s value">Budget used</th>'+
       '<th class="n pc-hide-sm">Planned KES</th><th class="n pc-hide-sm">Requested KES</th><th class="n">Earned KES</th></tr></thead><tbody>';
    order.forEach(function(wk){
      var list=byWeek[wk], pv=0, ev=0;
      list.forEach(function(r){ pv+=r.planned_value; ev+=r.earned_value; });
      h+='<tr class="pc-wk"><td colspan="9">Week of '+esc(shortDate(wk))+
         '<span>'+fmt(list.length)+' plan'+(list.length===1?'':'s')+' &middot; '+money(ev)+' of '+money(pv)+' KES earned</span></td></tr>';
      list.forEach(function(r){ h+=pcRow(r); });
    });
    h+='</tbody></table></div>';
    h+=pcKey();
    box.innerHTML=h;
    pcWire(box);
    Object.keys(PC.open).forEach(function(n){ if(PC.open[n]) pcLoadDetail(n); });
  }

  // one line per farm and a total: what management reads before anything else
  function pcSummary(rows){
    var farms={}, order=[];
    function add(k, r){
      if(!farms[k]){ farms[k]={plans:0, pv:0, wv:0, ev:0, behind:0, short:0, over:0}; order.push(k); }
      var f=farms[k];
      f.plans++; f.pv+=r.planned_value; f.wv+=r.planned_value*(r.completion||0)/100; f.ev+=r.earned_value;
      if(r._a.status==="behind") f.behind++;
      if(r._a.status==="short") f.short++;
      if(r._a.over) f.over++;
    }
    rows.forEach(function(r){ add(r.farm, r); add("__all", r); });
    var line=function(k, cls){
      var f=farms[k];
      var work=f.pv>0?f.wv/f.pv*100:0, bud=f.pv>0?f.ev/f.pv*100:null;
      var isAll=k==="__all";
      return '<tr'+(isAll?' class="tot"':' data-farm="'+esc(k)+'"'+(PC.farm===k?' class="sel"':''))+'>'+
        '<td>'+(isAll?('All '+esc(TX("top_plural","Farms")).toLowerCase()):esc(k))+'</td>'+
        '<td class="n">'+fmt(f.plans)+'</td>'+
        '<td>'+meter(work,"var(--green)")+'</td>'+
        '<td>'+meter(bud,"#6366f1")+'</td>'+
        '<td class="n pc-hide-sm">'+money(f.ev)+' / '+money(f.pv)+'</td>'+
        '<td class="n">'+(f.behind?'<span class="pc-st st-bad">'+f.behind+'</span>':'—')+'</td>'+
        '<td class="n pc-hide-sm">'+(f.short?'<span class="pc-st st-warn">'+f.short+'</span>':'—')+'</td>'+
        '<td class="n">'+(f.over?'<span class="pc-flag">'+f.over+'</span>':'—')+'</td></tr>';
    };
    var h='<div style="overflow-x:auto"><table class="pc-tbl pc-sum"><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Plans</th>'+
      '<th>Work done</th><th>Budget used</th><th class="n pc-hide-sm">Earned / planned KES</th><th class="n" title="running plans whose work trails the days gone by">Behind now</th><th class="n pc-hide-sm">Ended short</th><th class="n">Over budget</th></tr></thead><tbody>';
    order.filter(function(k){return k!=="__all";}).sort().forEach(function(k){ h+=line(k); });
    if(order.length>2) h+=line("__all");
    return h+'</tbody></table></div>';
  }

  function pcControls(d){
    var q=function(k,lbl){ return '<button type="button" data-pcq="'+k+'"'+(PC.quick===k?' class="on"':'')+'>'+lbl+'</button>'; };
    return '<div class="pcw">'+
      '<div><label>Starting from</label><input type="date" id="pc-from" value="'+esc(PC.from||d.from_date||"")+'"></div>'+
      '<div><label>To</label><input type="date" id="pc-to" value="'+esc(PC.to||d.to_date||"")+'"></div>'+
      '<div><label>'+esc(TX("top_singular","Farm"))+'</label><select id="pc-farm">'+
        farmOptions(PC.farm)+'</select></div>'+
      '<div class="pcw-quick">'+q("4w","4 weeks")+q("8w","8 weeks")+q("12w","12 weeks")+q("all","All")+'</div>'+
    '</div>';
  }

  function pcRow(r){
    var a=r._a, st=PC_STATUS[a.status], open=!!PC.open[r.plan];
    var over=r.requested_value>r.planned_value+0.5;
    var time = a.status==="upcoming" ? ('starts '+shortDate(r.period_from))
             : (a.running ? ('day '+a.gone+' of '+a.total) : 'ended');
    return '<tr class="pc-plan'+(open?' open':'')+'" data-pcplan="'+esc(r.plan)+'">'+
      '<td class="pc-car">'+(open?'&#9662;':'&#9656;')+'</td>'+
      '<td><b>'+esc(r.plan)+' &middot; '+esc(r.farm)+'</b></td>'+
      '<td class="pc-hide-sm">'+esc(shortDate(r.period_from))+' &ndash; '+esc(shortDate(r.period_to))+'<br><span class="pc-time">'+esc(time)+'</span></td>'+
      '<td><span class="pc-st '+st.cls+'">'+st.label+'</span>'+(a.over?'<span class="pc-flag">Over budget</span>':'')+
        '<span class="pc-time pc-show-sm"><br>'+esc(time)+'</span></td>'+
      '<td>'+meter(a.work,"var(--green)", a.running?a.time:null, a.recorded)+
        (a.recorded>a.work+0.5?'<span class="pc-time">'+fmt(a.recorded,0)+'% recorded, awaiting approval</span>':'')+'</td>'+
      '<td>'+meter(a.budget,"#6366f1")+'</td>'+
      '<td class="n pc-hide-sm">'+money(r.planned_value)+'</td>'+
      '<td class="n pc-hide-sm'+(over?' pc-over':'')+'">'+money(r.requested_value)+
        (over?'<br><span style="font-size:10px">+'+money(r.requested_value-r.planned_value)+'</span>':'')+'</td>'+
      '<td class="n">'+money(r.earned_value)+
        (r.pending_value?'<br><span class="pc-time">+'+money(r.pending_value)+' awaiting approval</span>':'')+'</td>'+
    '</tr>'+
    (open?'<tr class="pc-det"><td colspan="9"><div class="pcd" id="pcd-'+esc(r.plan)+'"><div class="loading">Reading everything under '+esc(r.plan)+'&hellip;</div></div></td></tr>':'');
  }

  // every term on the card, in one place
  function pcKey(){
    var dl=function(rows){ return rows.map(function(r){ return r[0]==="#"?'<h6>'+esc(r[1])+'</h6>':'<dt>'+esc(r[0])+'</dt><dd>'+esc(r[1])+'</dd>'; }).join(""); };
    return '<details class="ex-key"><summary>Key: what every term means</summary><dl>'+dl([
      ["#","Which plans are listed"],
      ["Starting from / To","A plan is listed when it starts inside these dates. 4, 8 and 12 weeks end today."],
      ["#","Status"],
      ["Upcoming","The plan has not started yet."],
      ["On track","Running, and recorded work is no more than "+PC_BEHIND_MARGIN+" points behind the share of its days gone by."],
      ["Behind","Running, and recorded work trails the share of its days gone by by more than "+PC_BEHIND_MARGIN+" points."],
      ["Done","Ended with at least "+PC_DONE_AT+"% of its work recorded."],
      ["Ended short","Ended with less than "+PC_DONE_AT+"% of its work recorded."],
      ["Over budget","Requested or earned money is above the plan's value. Shown beside any status."],
      ["#","Measures"],
      ["Work done","Each activity's approved output against its target, capped at that target and weighted by its planned value. Never adds different units together."],
      ["Recorded, awaiting approval","Output entered on actuals that are still in approval. Drawn paler behind Work done; Status counts it."],
      ["Day 4 of 7 / the tick","How far through its period the plan is. The tick on the Work done bar marks that share."],
      ["Budget used","Earned (confirmed) pay ÷ the plan's value."],
      ["Planned KES","The plan's own value: target × rate on each activity."],
      ["Requested KES","Requests raised against the plan (not rejected). Red when above Planned, with the excess under it."],
      ["Earned KES","Confirmed pay for the plan's work. \"+N awaiting approval\" is pay recorded but not yet confirmed."],
      ["#","Inside a plan"],
      ["Not in a pay run","Confirmed pay that no payment run has picked up yet."],
      ["In pay runs, unpaid","Pay in payment runs not yet marked Paid."],
      ["Paid out","Pay in payment runs marked Paid."],
      ["By salaried staff","Output by staff on salary: real work at no piece-rate pay, so Work done can run ahead of Budget used."],
      ["Requests to tasks the plan does not carry","Listed under Requests but not counted in the plan's figures."]
    ])+'</dl></details>';
  }

  // ── one plan opened: everything under it ──
  var PCD = {};      // plan -> mp_detail response
  var PCD_TAB = {};  // plan -> open tab
  function pcLoadDetail(plan){
    if(PCD[plan]){ pcDrawDetail(plan); return; }
    call({action:"mp_detail", plan:plan}).then(function(d){
      if(d.error){ var b=el("pcd-"+plan); if(b) b.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
      PCD[plan]=d; pcDrawDetail(plan);
    }).catch(function(){
      var b=el("pcd-"+plan); if(b) b.innerHTML='<div class="empty">Could not load this plan.</div>';
    });
  }
  function pcDrawDetail(plan){
    var box=el("pcd-"+plan), d=PCD[plan]; if(!box||!d) return;
    var p=d.plan||{}, m=d.money||{};
    var tab=PCD_TAB[plan]||"activities";
    var h='<div class="pcd-h">'+
      '<span><b>'+esc(p.plan_name||p.name)+'</b></span>'+stateTag(p.workflow_state)+
      '<span>Raised by <b>'+esc(p.raised_by||"—")+'</b>'+(p.raised_on?' on '+esc(shortDate(p.raised_on)):'')+'</span>'+
      (p.gm_approved_by?'<span>Approved by <b>'+esc(p.gm_approved_by)+'</b>'+(p.gm_approved_on?' on '+esc(shortDate(p.gm_approved_on)):'')+'</span>':'')+
      '<span><b>'+fmt(p.total_man_days,0)+'</b> man-days planned</span>'+
      deskLink("Work Management Master Plan", p.name)+'</div>';
    // the money, in the order it moves
    var pv=m.planned||0;
    var cell=function(lbl, v, sub, cls){ return '<div class="pcd-m'+(cls?' '+cls:'')+'"><span>'+lbl+'</span><b>'+money(v)+'</b>'+(sub?'<i>'+sub+'</i>':'')+'</div>'; };
    h+='<div class="pcd-money">'+
      cell("Planned", pv, "KES, the plan’s value")+
      cell("Requested", m.requested, pv?fmt(m.requested/pv*100,0)+'% of planned':'', m.requested>pv+0.5?'bad':'')+
      cell("Awaiting approval", m.pending, "recorded, not yet confirmed", m.pending?'warn':'')+
      cell("Earned", m.earned, pv?fmt(m.earned/pv*100,0)+'% of planned · confirmed':'confirmed', m.earned>pv+0.5?'bad':'good')+
      cell("Not in a pay run", m.not_in_run, "confirmed, no payment run yet", m.not_in_run?'warn':'')+
      cell("In pay runs, unpaid", m.unpaid_runs, "", m.unpaid_runs?'warn':'')+
      cell("Paid out", m.paid, "", m.paid?'good':'')+
      '<div class="pcd-m"><span>People</span><b>'+fmt(m.people)+'</b><i>'+fmt(m.person_days)+' person-days recorded</i></div>'+
    '</div>';
    if(m.offplan_count){
      h+='<div class="pcd-note warn" style="margin:-4px 2px 10px">'+fmt(m.offplan_count)+' request'+(m.offplan_count===1?'':'s')+
         ' worth '+money(m.offplan)+' KES went to tasks this plan does not carry &mdash; listed under Requests, not counted above.</div>';
    }
    var tabs=[["activities","Activities",(d.activities||[]).length],["requests","Requests",(d.requests||[]).length],
      ["assignments","Crews",(d.assignments||[]).length],["actuals","Actuals",(d.actuals||[]).length],
      ["people","People",(d.people||[]).length],["payments","Payments",(d.payments||[]).length]];
    h+='<div class="pcd-tabs">'+tabs.map(function(t){
      return '<button type="button" data-pcdtab="'+t[0]+'"'+(tab===t[0]?' class="on"':'')+'>'+t[1]+'<i>'+t[2]+'</i></button>';
    }).join("")+'</div><div class="pcd-pane">'+pcPane(d, tab)+'</div>';
    box.innerHTML=h;
    box.querySelectorAll("[data-pcdtab]").forEach(function(b){
      b.onclick=function(e){ e.stopPropagation(); PCD_TAB[plan]=b.getAttribute("data-pcdtab"); pcDrawDetail(plan); };
    });
    box.querySelectorAll("tr[data-open]").forEach(function(tr){
      tr.onclick=function(){
        var k=tr.getAttribute("data-open"), v=tr.getAttribute("data-v");
        if(k==="req") openPlanModal(v);
        else if(k==="act") openActualModal(v);
        else if(k==="emp") openEmpModal(v);
        else if(k==="pay") openPaymentModal(v);
      };
    });
  }
  // a plan line's standard as the plan budgeted it: its own frozen rate and unit,
  // and the output per man-day its quantity and man-days imply. Falls back to the
  // task's current standard where the line carries no man-days.
  function pcStdSub(a){
    var parts=[];
    var perDay=a.man_days>0?a.target_qty/a.man_days:0;
    if(perDay>0) parts.push(fmt(perDay, perDay%1?1:0)+" "+(a.uom||"units")+"/day");
    if(a.rate>0) parts.push("KES "+fmt(a.rate, a.rate%1===0?0:(a.rate<1?3:2))+(a.uom?"/"+a.uom:""));
    if(!parts.length) return taskStdSub(a.task);
    return '<span class="std-sub" title="Standard in this plan: output per man-day and rate per unit">Std '+esc(parts.join(" · "))+'</span>';
  }
  function pcPane(d, tab){
    var T=function(head, body, note){
      return '<table class="pc-tbl"><thead><tr>'+head.map(function(c){
        return '<th'+(c.charAt(0)==="#"?' class="n"':'')+'>'+c.replace(/^#/,"")+'</th>'; }).join("")+'</tr></thead><tbody>'+
        (body||'<tr><td colspan="'+head.length+'" class="empty">Nothing yet.</td></tr>')+'</tbody></table>'+(note?'<div class="pcd-note">'+note+'</div>':'');
    };
    var n=function(v,dp){ return '<td class="n">'+fmt(v,dp||0)+'</td>'; };
    var k=function(v){ return '<td class="n">'+money(v)+'</td>'; };
    var b="";
    if(tab==="activities"){
      (d.activities||[]).forEach(function(a){
        var sal=a.salaried_qty?'<br><span class="pc-time">'+fmt(a.salaried_qty)+' by salaried staff</span>':'';
        b+='<tr><td><b>'+esc(a.subject||taskName(a.task))+'</b>'+pcStdSub(a)+(a.in_plan?'':' <span class="pc-st st-warn">'+esc(a.consultant_state||"not approved")+'</span>')+'</td>'+
          '<td>'+esc(a.uom||"")+'</td>'+n(a.target_qty)+n(a.req_qty)+
          '<td class="n">'+fmt(a.done_qty)+sal+(a.pending_qty?'<br><span class="pc-time">+'+fmt(a.pending_qty)+' awaiting</span>':'')+'</td>'+
          '<td>'+meter(a.done_pct,"var(--green)")+'</td>'+k(a.planned_value)+k(a.req_value)+k(a.earned)+'</tr>';
      });
      return T(["Activity","Unit","#Target","#Requested","#Done","Work done","#Planned KES","#Requested KES","#Earned KES"], b,
        "Earned is confirmed pay. Output by salaried staff is real work at no piece-rate cost, so work done can run ahead of money earned.");
    }
    if(tab==="requests"){
      (d.requests||[]).forEach(function(r){
        b+='<tr data-open="req" data-v="'+esc(r.name)+'"><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.task_subject||taskName(r.task))+taskStdSub(r.task)+'</td>'+
          '<td>'+esc(lbl(r.block_section))+'</td><td>'+esc(shortDate(r.from_date))+' &ndash; '+esc(shortDate(r.to_date))+'</td>'+
          '<td class="n">'+fmt(r.quantity)+' '+esc(r.uom||"")+'</td><td class="n">'+fmt(r.people_per_day)+'</td>'+k(r.total_cost)+
          '<td>'+stateTag(r.workflow_state)+'</td><td>'+esc(r.requested_by||"")+'</td></tr>';
      });
      return T(["Request","Task","Block","Dates","#Quantity","#People/day","#Cost KES","State","Requested by"], b, "Click a request for its full trail.");
    }
    if(tab==="assignments"){
      (d.assignments||[]).forEach(function(a){
        b+='<tr><td><b>'+esc(a.name)+'</b> '+deskLink("Work Management Assigner", a.name)+'</td><td>'+esc(a.planner_request||"")+'</td>'+
          '<td>'+esc(taskName(a.task))+taskStdSub(a.task)+'</td><td>'+esc(lbl(a.block_section))+'</td>'+
          '<td>'+esc(shortDate(a.from_date))+' &ndash; '+esc(shortDate(a.to_date))+'</td>'+n(a.workers)+
          '<td>'+stateTag(a.workflow_state)+'</td><td>'+esc(a.assigned_by||"")+'</td></tr>';
      });
      return T(["Crew","Request","Task","Block","Dates","#Workers","State","Assigned by"], b);
    }
    if(tab==="actuals"){
      (d.actuals||[]).forEach(function(a){
        b+='<tr data-open="act" data-v="'+esc(a.name)+'"><td><b>'+esc(a.name)+'</b></td><td>'+esc(taskName(a.task))+taskStdSub(a.task)+'</td>'+
          '<td>'+esc(shortDate(a.from_date))+' &ndash; '+esc(shortDate(a.to_date))+'</td>'+n(a.people)+
          '<td class="n">'+fmt(a.qty)+(a.salaried_qty?'<br><span class="pc-time">'+fmt(a.salaried_qty)+' salaried</span>':'')+'</td>'+k(a.pay)+
          '<td>'+stateTag(a.workflow_state)+'</td><td>'+esc(a.entered_by||"")+'</td></tr>';
      });
      return T(["Actual","Task","Dates","#People","#Qty done","#Pay KES","State","Entered by"], b, "Click an actual for its day-by-day record.");
    }
    if(tab==="people"){
      (d.people||[]).forEach(function(p){
        b+='<tr data-open="emp" data-v="'+esc(p.employee)+'"><td><b>'+esc(p.employee_name||p.employee)+'</b><br><span class="pc-time">'+esc(p.employee)+'</span></td>'+
          '<td>'+esc(p.employment_type||"")+'</td>'+n(p.days)+'<td>'+esc(shortDate(p.first_day))+' &ndash; '+esc(shortDate(p.last_day))+'</td>'+
          n(p.qty)+k(p.amount)+k(p.confirmed)+k(p.paid)+'</tr>';
      });
      return T(["Worker","Type","#Days","Worked","#Qty","#Earned KES","#Confirmed KES","#Paid KES"], b,
        "Everyone recorded on this plan’s actuals, rejected ones aside. Click a worker for their history.");
    }
    if(tab==="payments"){
      (d.payments||[]).forEach(function(p){
        b+='<tr data-open="pay" data-v="'+esc(p.name)+'"><td><b>'+esc(p.name)+'</b></td><td>'+esc(p.employee_name||p.employee||"")+'</td>'+
          '<td>'+esc(shortDate(p.period_from))+' &ndash; '+esc(shortDate(p.period_to))+'</td>'+k(p.amount)+'<td>'+stateTag(p.workflow_state)+'</td></tr>';
      });
      return T(["Payment run","Worker","Period","#This plan KES","State"], b,
        "The part of each payment run that pays for this plan’s work.");
    }
    return "";
  }

  function pcWire(box){
    // every control applies the moment it changes, as the farm picker always did;
    // a typed date that waited for an Apply button looked like a filter doing nothing
    var df=el("pc-from");
    if(df) df.onchange=function(){ PC.from=df.value; PC.quick=null; planCompletion(); };
    var dt=el("pc-to");
    if(dt) dt.onchange=function(){ PC.to=dt.value; PC.quick=null; planCompletion(); };
    var fs=el("pc-farm");
    if(fs) fs.onchange=function(){ PC.farm=fs.value; planCompletion(); };
    box.querySelectorAll("[data-pcq]").forEach(function(b){
      b.onclick=function(){
        var k=b.getAttribute("data-pcq");
        PC.quick=k; PC.to=todayISO();
        // n whole weeks ending today: today and the n*7-1 days before it
        PC.from = k==="all" ? "2020-01-01"
                : todayMinus(k==="4w"?27:(k==="12w"?83:55));
        planCompletion();
      };
    });
    box.querySelectorAll("[data-pcchip]").forEach(function(b){
      b.onclick=function(){ PC.chip=b.getAttribute("data-pcchip"); pcDraw(); };
    });
    // a farm's line in the summary is a shortcut to that farm; clicking it again clears it
    box.querySelectorAll(".pc-sum tr[data-farm]").forEach(function(tr){
      tr.onclick=function(){ var f=tr.getAttribute("data-farm"); PC.farm=(PC.farm===f?"":f); planCompletion(); };
    });
    box.querySelectorAll("tr[data-pcplan]").forEach(function(tr){
      tr.onclick=function(){ var n=tr.getAttribute("data-pcplan"); PC.open[n]=!PC.open[n]; pcDraw(); };
    });
  }
  // calendar dates on this machine, not UTC: three hours east of Greenwich the
  // UTC date is yesterday until 3am
  function todayISO(){ return localISO(new Date()); }
  function todayMinus(n){ var d=new Date(); d.setDate(d.getDate()-n); return localISO(d); }

  var TASK_NAMES = {};
  function taskName(t){ return (t && TASK_NAMES[t]) || t || ""; }
  // Each activity's STANDARD: what one person is expected to do in a day, in what
  // unit, and what each unit pays (the task's current rate period). Loaded with
  // the names; shown wherever an activity is, so a figure is read against it.
  var TASK_STD = {};
  function taskStdText(t){
    var s=t && TASK_STD[t]; if(!s) return "";
    var parts=[];
    if(s[0]>0) parts.push(fmt(s[0], s[0]%1?1:0)+" "+(s[1]||"units")+"/day");
    if(s[2]>0) parts.push("KES "+fmt(s[2], s[2]%1===0?0:(s[2]<1?3:2))+(s[1]?"/"+s[1]:""));
    return parts.join(" · ");
  }
  function taskStdSub(t){
    var x=taskStdText(t);
    return x?'<span class="std-sub" title="Standard: daily target per person and rate per unit">Std '+esc(x)+'</span>':'';
  }


  // ── activities, people & blocks: the explorer ────────────────────────────
  // Below the master plans: which activities cost or lag, who earned what, whose
  // requests turn into work, and where the money goes -- with the history behind
  // each. One filter bar scopes everything in the section. Four lenses list the
  // rows; opening one shows every list behind it and loads it into the chart.
  //
  // Every figure comes from the same rows on the server -- a worker's recorded
  // day joined to its actual, crew and request (WMX_JOIN in wm_dashboard) -- so
  // the lenses, the drill-downs and the chart lines cannot disagree.
  var EX = {
    from:null, to:null, farm:"", quick:"8w", q:"",
    lens:"activities", view:"list", sort:{}, open:null, seq:0,
    lenses:{}, details:{}, plans:[],
    chart:{ mode:"measures", kind:"estate", key:"", keyLabel:"", plan:"", activity:"",
            on:{planned:1, requested:0, recorded:0, confirmed:1, paid:1, output:0, cost:0, people:0},
            cmpKind:"activity", cmpKeys:[], cmpMeasure:"recorded", running:true, table:false,
            seq:0, data:null }
  };
  var EX_LENSES = [["activities","Activities"],["workers","Workers"],["staff","Staff"],["blocks",esc(TX("unit_plural","Blocks"))]];
  // eight measures, each its own colour, fixed whichever are switched on. The
  // money five take slots 1-5 and the two percentages 6-7: each panel's lines are
  // adjacent slots of a palette validated for adjacent lines (dataviz validator:
  // CVD dE >= 9.1, normal-vision dE >= 19.6 on white).
  // The dashboard's own chart colours, as "Plans, assignments & actuals over time"
  // uses them: planned dashed brown, confirmed solid green over a pale fill. Each
  // panel's set passes the dataviz validator on white (CVD dE >= 8.8, normal-vision
  // >= 26, contrast >= 3:1), and planned also differs by its dash.
  var EX_MEASURES = [
    {k:"planned",   label:"Planned",          unit:"kes", color:"#a16207", panel:"money", dash:1},
    {k:"requested", label:"Requested",        unit:"kes", color:"#2563eb", panel:"money"},
    {k:"recorded",  label:"Recorded",         unit:"kes", color:"#d97706", panel:"money"},
    {k:"confirmed", label:"Confirmed",        unit:"kes", color:"#0a7a43", panel:"money", fill:1},
    {k:"paid",      label:"Paid out",         unit:"kes", color:"#7c3aed", panel:"money"},
    {k:"output",    label:"Output vs target", unit:"pct", color:"#0a7a43", panel:"perf", fill:1},
    {k:"cost",      label:"Cost/unit vs rate",unit:"pct", color:"#7c3aed", panel:"perf"},
    {k:"people",    label:"People per day",   unit:"n",   color:"#2563eb", panel:"people", fill:1}
  ];
  var EX_SUBJECT_COLORS = ["#0a7a43","#2563eb","#a16207","#7c3aed","#d97706","#e11d48"];
  var EX_PANELS = {money:"Money (KES)", perf:"Performance (%)", people:"People per day"};
  function exMeasure(k){ return EX_MEASURES.filter(function(m){ return m.k===k; })[0]; }

  (function injectExCss(){
    if(document.getElementById("wm-ex-css")) return;
    var st=document.createElement("style");
    st.id="wm-ex-css";
    st.textContent=
      "#wmp .ex-bar{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px}"+
      "#wmp .ex-bar label{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:700;display:block;margin-bottom:4px}"+
      "#wmp .ex-bar input,#wmp .ex-bar select,#wmp .ex-pick select{font-family:inherit;font-size:12px;border:1px solid var(--line);padding:6px 9px;border-radius:var(--rs);background:#fff;color:var(--ink)}"+
      "#wmp .ex-bar input[type=search]{min-width:200px}"+
      "#wmp .ex-pills{display:flex;gap:5px;flex-wrap:wrap}"+
      "#wmp .ex-pills button{font-family:inherit;font-size:10.5px;font-weight:600;background:#fff;color:var(--mute);border:1px solid var(--line);padding:6px 11px;border-radius:999px;cursor:pointer}"+
      "#wmp .ex-pills button.on{background:var(--ink);color:#fff;border-color:var(--ink)}"+
      "#wmp .ex-right{margin-left:auto}"+
      "#wmp .ex-high{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px;margin-bottom:16px}"+
      "#wmp .ex-hi{border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer;background:#fff;text-align:left;font-family:inherit}"+
      "#wmp .ex-hi:hover{border-color:var(--ink)}"+
      "#wmp .ex-hi span{display:block;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:700}"+
      "#wmp .ex-hi b{display:block;font-size:13px;margin-top:4px;color:var(--ink)}"+
      "#wmp .ex-hi i{display:block;font-style:normal;font-size:11px;color:var(--mute);margin-top:2px}"+
      "#wmp .ex-hi .ico{float:right;font-size:13px}"+
      "#wmp .ex-chart{border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:16px;background:#fff}"+
      "#wmp .ex-chart-h{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}"+
      "#wmp .ex-chart-h h4{margin:0;font-size:12px;font-weight:700}"+
      "#wmp .ex-pick{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:11px;color:var(--mute)}"+
      "#wmp .ex-chip{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;background:#eef2ff;color:#3730a3;border-radius:999px;padding:3px 6px 3px 10px}"+
      "#wmp .ex-chip button{border:0;background:none;cursor:pointer;color:#3730a3;font-size:13px;line-height:1;padding:0 2px}"+
      "#wmp .ex-legend{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 4px}"+
      "#wmp .ex-legend{gap:4px 16px}"+
      "#wmp .ex-legend button{display:inline-flex;align-items:center;gap:7px;font-family:inherit;font-size:11.5px;color:var(--ink);background:none;border:0;padding:3px 0;cursor:pointer}"+
      "#wmp .ex-legend button.off{color:#b5b3ad;text-decoration:line-through}"+
      "#wmp .ex-legend button.off i{opacity:.35}"+
      "#wmp .ex-legend button i{display:inline-block;width:18px;height:2px;border-radius:1px}"+
      "#wmp .ex-panel{position:relative;margin-top:6px}"+
      "#wmp .ex-panel h5{margin:8px 0 0;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:#8a8780;font-weight:600}"+
      "#wmp .ex-panel svg{display:block;width:100%;overflow:visible}"+
      "#wmp .ex-panel .grid{stroke:#eceae4;stroke-width:1}"+
      "#wmp .ex-panel .base{stroke:#c3c2b7;stroke-width:1}"+
      "#wmp .ex-panel .ref{stroke:#898781;stroke-width:1;stroke-dasharray:3 3}"+
      "#wmp .ex-panel text{font-size:10px;fill:#898781;font-variant-numeric:tabular-nums}"+
      "#wmp .ex-panel .lbl{fill:#52514e;font-weight:600}"+
      "#wmp .ex-panel .xh{stroke:#898781;stroke-width:1}"+
      "#wmp .ex-tip{position:fixed;z-index:2147483001;pointer-events:none;background:#fff;border:1px solid rgba(11,11,11,.12);box-shadow:0 6px 18px rgba(0,0,0,.12);border-radius:8px;padding:8px 10px;font-size:11px;min-width:150px;display:none}"+
      "#wmp .ex-tip .d{color:var(--mute);margin-bottom:4px;font-weight:600}"+
      "#wmp .ex-tip .r{display:flex;align-items:center;gap:7px;margin-top:2px}"+
      "#wmp .ex-tip .r i{width:12px;height:2px;border-radius:1px;flex:0 0 auto}"+
      "#wmp .ex-tip .r b{font-variant-numeric:tabular-nums}"+
      "#wmp .ex-tip .r span{color:var(--mute)}"+
      "#wmp .ex-lenstabs{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}"+
      "#wmp .ex-scroll{max-height:520px;overflow:auto;border:1px solid var(--faint);border-radius:8px}"+
      "#wmp .ex-scroll thead th{position:sticky;top:0;z-index:2;background:#fff;box-shadow:0 1px 0 var(--line);cursor:pointer;user-select:none}"+
      "#wmp .ex-scroll thead th.sorted{color:var(--ink)}"+
      "#wmp .ex-row{cursor:pointer}#wmp .ex-row:hover td{background:#fafafa}"+
      "#wmp .ex-row.open td{background:#f5f7ff}"+
      "#wmp .ex-sub{font-size:10.5px;color:var(--mute)}"+
      "#wmp .ex-good{color:#006300;font-weight:700}#wmp .ex-bad{color:#b91c1c;font-weight:700}#wmp .ex-warn{color:#92400e;font-weight:700}"+
      "#wmp .ex-flag{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:999px;margin:1px 2px 1px 0;white-space:nowrap}"+
      "#wmp .ex-flag.bad{background:#fee2e2;color:#991b1b}#wmp .ex-flag.warn{background:#fef3c7;color:#92400e}"+
      "#wmp .ex-spark{display:block}"+
      "#wmp .ex-heat td.c{padding:0;min-width:34px;height:26px;text-align:center;font-size:10px;border:2px solid #fff;border-radius:4px}"+
      "#wmp .ex-heat td.c:hover{outline:2px solid var(--ink);outline-offset:-2px}"+
      "#wmp .ex-heat-legend{display:flex;align-items:center;gap:8px;font-size:10.5px;color:var(--mute);margin:8px 2px}"+
      "#wmp .ex-heat-legend s{display:inline-block;width:120px;height:8px;border-radius:4px;text-decoration:none}"+
      "#wmp .ex-det td{padding:0 8px 14px;background:#f5f7ff;border-bottom:1px solid var(--line)}"+
      "#wmp .ex-key{margin-top:14px;border-top:1px solid var(--faint);padding-top:10px;font-size:11.5px;color:var(--ink)}"+
      "#wmp .ex-key summary{cursor:pointer;font-weight:700;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}"+
      "#wmp .ex-key dl{display:grid;grid-template-columns:minmax(140px,190px) 1fr;gap:5px 14px;margin:10px 0 4px}"+
      "#wmp .ex-key dt{font-weight:700}#wmp .ex-key dd{margin:0;color:#52514e}"+
      "#wmp .ex-key h6{grid-column:1/-1;margin:10px 0 2px;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute)}"+
      "@media(max-width:820px){#wmp .ex-hide-sm{display:none}#wmp .ex-key dl{grid-template-columns:1fr}#wmp .ex-right{margin-left:0}}";
    document.head.appendChild(st);
  })();

  function exTip(){
    var t=document.getElementById("ex-tip");
    if(!t){ t=document.createElement("div"); t.id="ex-tip"; t.className="ex-tip"; el("wmp").appendChild(t); }
    return t;
  }
  // tooltip rows are built with textContent: names come from records, not code
  function exShowTip(ev, title, rows){
    var t=exTip(); t.textContent="";
    var d=document.createElement("div"); d.className="d"; d.textContent=title; t.appendChild(d);
    rows.forEach(function(r){
      var row=document.createElement("div"); row.className="r";
      var k=document.createElement("i"); k.style.background=r.color||"transparent"; row.appendChild(k);
      var b=document.createElement("b"); b.textContent=r.value; row.appendChild(b);
      var s=document.createElement("span"); s.textContent=r.label; row.appendChild(s);
      t.appendChild(row);
    });
    t.style.display="block";
    var x=ev.clientX+14, y=ev.clientY+14, w=t.offsetWidth, h=t.offsetHeight;
    if(x+w>window.innerWidth-8) x=ev.clientX-w-14;
    if(y+h>window.innerHeight-8) y=ev.clientY-h-14;
    t.style.left=x+"px"; t.style.top=y+"px";
  }
  function exHideTip(){ var t=document.getElementById("ex-tip"); if(t) t.style.display="none"; }

  function exArgs(extra){
    var a={};
    if(EX.from) a.from_date=EX.from;
    if(EX.to) a.to_date=EX.to;
    if(EX.farm) a.farm=EX.farm;
    for(var k in (extra||{})) a[k]=extra[k];
    return a;
  }
  function exRange(){
    var from=EX.from, to=EX.to;
    if(!from||!to){ to=todayISO(); from=todayMinus(55); }
    return {from:from, to:to};
  }
  function exWeeks(){
    // Monday weeks covering the range, matching the server's buckets
    var r=exRange(), out=[];
    var d=new Date(r.from+"T00:00:00"); d.setDate(d.getDate()-((d.getDay()+6)%7));
    var end=new Date(r.to+"T00:00:00");
    while(d<=end){ out.push(localISO(d)); d.setDate(d.getDate()+7); }
    return out;
  }
  function exPct(v){ return v==null?"—":fmt(v,0)+"%"; }
  function exHours(m){
    if(m==null) return "—";
    if(m<60) return fmt(m)+" min";
    if(m<60*48) return fmt(m/60,1)+" h";
    return fmt(m/1440,1)+" days";
  }
  // benchmark tints: output against target, cost against rate, done/delivered
  function exTintOut(v){ return v==null?"":(v>=95?"ex-good":(v<80?"ex-bad":"ex-warn")); }
  function exTintCost(v){ return v==null?"":(v>115?"ex-bad":(v>105?"ex-warn":"ex-good")); }
  function exTintDone(v){ return v==null?"":(v>=90?"ex-good":(v<50?"ex-bad":"ex-warn")); }

  // ── the section: filters, highlights, chart, lenses, key ──
  function exInit(){
    var box=el("wm-ex"); if(!box) return;
    var q=function(k,l){ return '<button type="button" data-exq="'+k+'"'+(EX.quick===k?' class="on"':'')+'>'+l+'</button>'; };
    box.innerHTML=
      '<div class="ex-bar">'+
        '<div><label>From</label><input type="date" id="ex-from"></div>'+
        '<div><label>To</label><input type="date" id="ex-to"></div>'+
        '<div><label>'+esc(TX("top_singular","Farm"))+'</label><select id="ex-farm">'+farmOptions(EX.farm)+'</select></div>'+
        '<div><label>Find</label><input type="search" id="ex-q" placeholder="Activity, worker, person or '+esc(TX("unit_singular","Block")).toLowerCase()+'…"></div>'+
        '<div class="ex-pills ex-right" id="ex-quick">'+q("4w","4 weeks")+q("8w","8 weeks")+q("12w","12 weeks")+q("all","All")+'</div>'+
      '</div>'+
      '<div class="ex-high" id="ex-high"><div class="loading">Looking for what stands out&hellip;</div></div>'+
      '<div class="ex-chart" id="ex-chart"></div>'+
      '<div class="ex-lenstabs">'+
        '<div class="ex-pills" id="ex-lenses">'+EX_LENSES.map(function(l){
          return '<button type="button" data-exlens="'+l[0]+'"'+(EX.lens===l[0]?' class="on"':'')+'>'+l[1]+'</button>'; }).join("")+'</div>'+
        '<div class="ex-pills ex-right" id="ex-views">'+
          '<button type="button" data-exview="list"'+(EX.view==="list"?' class="on"':'')+'>List</button>'+
          '<button type="button" data-exview="heat"'+(EX.view==="heat"?' class="on"':'')+'>Heatmap</button></div>'+
      '</div>'+
      '<div id="ex-lens"><div class="loading">Reading the lenses&hellip;</div></div>'+
      exKey();
    var r=exRange();
    el("ex-from").value=EX.from||r.from; el("ex-to").value=EX.to||r.to;
    el("ex-from").onchange=function(){ EX.from=this.value; EX.quick=null; exReload(); };
    el("ex-to").onchange=function(){ EX.to=this.value; EX.quick=null; exReload(); };
    el("ex-farm").onchange=function(){ EX.farm=this.value; exReload(); };
    var qt=null;
    el("ex-q").oninput=function(){ var v=this.value; clearTimeout(qt); qt=setTimeout(function(){ EX.q=v.toLowerCase(); exDrawLens(); },160); };
    box.querySelectorAll("[data-exq]").forEach(function(b){
      b.onclick=function(){
        var k=b.getAttribute("data-exq");
        EX.quick=k; EX.to=todayISO();
        EX.from = k==="all" ? "2020-01-01" : todayMinus(k==="4w"?27:(k==="12w"?83:55));
        el("ex-from").value=EX.from; el("ex-to").value=EX.to;
        box.querySelectorAll("[data-exq]").forEach(function(x){ x.classList.toggle("on", x===b); });
        exReload();
      };
    });
    box.querySelectorAll("[data-exlens]").forEach(function(b){
      b.onclick=function(){ EX.lens=b.getAttribute("data-exlens"); EX.open=null;
        box.querySelectorAll("[data-exlens]").forEach(function(x){ x.classList.toggle("on", x===b); });
        exLoadLens(EX.lens); };
    });
    box.querySelectorAll("[data-exview]").forEach(function(b){
      b.onclick=function(){ EX.view=b.getAttribute("data-exview");
        box.querySelectorAll("[data-exview]").forEach(function(x){ x.classList.toggle("on", x===b); });
        exLoadLens(EX.lens); };
    });
    exReload();
  }

  // a filter changed: every lens, the plans list and the chart re-read the slice
  function exReload(){
    var seq=++EX.seq;
    EX.lenses={}; EX.details={}; EX.open=null;
    // refetch keeps the frame: the old render stays, dimmed, until the new one lands
    ["ex-lens","ex-chart","ex-high"].forEach(function(id){ var n=el(id); if(n) n.style.opacity=".55"; });
    var loads=EX_LENSES.map(function(l){
      return call(exArgs({action:"ex_lens", lens:l[0]})).then(function(d){ if(seq===EX.seq) EX.lenses[l[0]]=d; });
    });
    loads.push(call(exArgs({action:"plan_completion"})).then(function(d){ if(seq===EX.seq) EX.plans=d.plans||[]; }));
    Promise.all(loads).then(function(){
      if(seq!==EX.seq) return;
      ["ex-lens","ex-chart","ex-high"].forEach(function(id){ var n=el(id); if(n) n.style.opacity=""; });
      // the farm list arrives with the dashboard's other reads, after this bar was drawn
      var fs=el("ex-farm"); if(fs && fs.options.length<=1 && FARM_LIST.length) fs.innerHTML=farmOptions(EX.farm);
      exDrawHighlights();
      exLoadLens(EX.lens);
      exDrawChartFrame(); exLoadSeries();
    }).catch(function(){
      if(seq!==EX.seq) return;
      var n=el("ex-lens"); if(n){ n.style.opacity=""; n.innerHTML='<div class="empty">Could not read the explorer.</div>'; }
    });
  }

  // ── highlights: what stands out in the current slice ──
  function exDrawHighlights(){
    var box=el("ex-high"); if(!box) return;
    var A=(EX.lenses.activities||{}).rows||[], W=(EX.lenses.workers||{}).rows||[];
    var S=(EX.lenses.staff||{}).rows||[], B=(EX.lenses.blocks||{}).rows||[];
    var cards=[];
    var totPaid=A.reduce(function(s,r){ return s+(r.paid_amt||0); },0);
    var over=A.filter(function(r){ return r.cost_pct!=null && r.paid_amt>=Math.max(5000,totPaid*0.01); })
              .sort(function(a,b){ return b.cost_pct-a.cost_pct; })[0];
    if(over && over.cost_pct>105) cards.push({ico:"▲", tone:"bad", k:"Furthest over its rate",
      b:(over.subject||taskName(over.task))+" · "+exPct(over.cost_pct), i:"paid "+money(over.paid_amt)+" KES for work valued at "+money(over.rated),
      go:{lens:"activities", key:over.task}});
    var low=A.map(function(r){ return {lens:"activities", key:r.task, name:r.subject||taskName(r.task), v:r.out_pct, pd:r.person_days}; })
      .concat(B.map(function(r){ return {lens:"blocks", key:r.block, name:lbl(r.block), v:r.out_pct, pd:r.person_days}; }))
      .filter(function(x){ return x.v!=null && x.pd>=20; }).sort(function(a,b){ return a.v-b.v; })[0];
    if(low && low.v<95) cards.push({ico:"▼", tone:"bad", k:"Furthest below target", b:low.name+" · "+exPct(low.v),
      i:"output against the daily target, over "+fmt(low.pd)+" person-days", go:{lens:low.lens, key:low.key}});
    var top=W.slice().sort(function(a,b){ return b.confirmed-a.confirmed; })[0];
    if(top && top.confirmed>0){
      var perDay=W.filter(function(r){ return r.confirmed>0 && r.days>0; }).map(function(r){ return r.confirmed/r.days; }).sort(function(a,b){ return a-b; });
      var med=perDay.length?perDay[Math.floor(perDay.length/2)]:0;
      var hi=W.filter(function(r){ return r.days>0 && med>0 && r.confirmed/r.days>2*med; }).length;
      cards.push({ico:"★", tone:"", k:"Top earner", b:(top.name||top.employee)+" · "+money(top.confirmed)+" KES",
        i:fmt(top.days)+" days"+(hi?(" · "+hi+" worker"+(hi===1?"":"s")+" earn over twice the median day"):""), go:{lens:"workers", key:top.employee}});
    }
    var wd=EX.lenses.workers||{};
    if(wd.scan_from){
      var ns=W.filter(function(r){ return r.noscan_days>0; });
      var nd=ns.reduce(function(s,r){ return s+r.noscan_days; },0);
      if(nd) cards.push({ico:"⚠", tone:"bad", k:"Paid with no check-in scan", b:fmt(nd)+" day"+(nd===1?"":"s")+" · "+ns.length+" worker"+(ns.length===1?"":"s"),
        i:"scans exist from "+shortDate(wd.scan_from), go:{lens:"workers", sort:"noscan_days"}});
    }
    var un=W.reduce(function(s,r){ return s+(r.unpaid_confirmed||0); },0);
    if(un>0) cards.push({ico:"⏸", tone:"warn", k:"Confirmed, not yet paid", b:money(un)+" KES",
      i:W.filter(function(r){ return r.unpaid_confirmed>0; }).length+" workers waiting on a paid payment run", go:{lens:"workers", sort:"unpaid_confirmed"}});
    var weak=S.filter(function(r){ return r.requested>=50000 && r.delivered_pct!=null; }).sort(function(a,b){ return a.delivered_pct-b.delivered_pct; })[0];
    if(weak && weak.delivered_pct<60) cards.push({ico:"↓", tone:"warn", k:"Requests delivering least", b:(weak.name||weak.user)+" · "+exPct(weak.delivered_pct),
      i:money(weak.delivered)+" of "+money(weak.requested)+" KES requested", go:{lens:"staff", key:weak.user}});
    if(!cards.length){ box.innerHTML='<div class="empty">Nothing stands out in this slice.</div>'; return; }
    box.innerHTML=cards.slice(0,6).map(function(c,i){
      return '<button type="button" class="ex-hi" data-exhi="'+i+'"><span>'+esc(c.k)+
        '<em class="ico ex-'+(c.tone||"good")+'" style="font-style:normal">'+c.ico+'</em></span><b>'+esc(c.b)+'</b><i>'+esc(c.i)+'</i></button>';
    }).join("");
    box.querySelectorAll("[data-exhi]").forEach(function(b){
      b.onclick=function(){
        var g=cards[+b.getAttribute("data-exhi")].go;
        EX.lens=g.lens; EX.view="list";
        if(g.sort) EX.sort[g.lens]={k:g.sort, dir:-1};
        document.querySelectorAll("#wm-ex [data-exlens]").forEach(function(x){ x.classList.toggle("on", x.getAttribute("data-exlens")===g.lens); });
        document.querySelectorAll("#wm-ex [data-exview]").forEach(function(x){ x.classList.toggle("on", x.getAttribute("data-exview")==="list"); });
        EX.open=g.key?{lens:g.lens, key:g.key}:null;
        exLoadLens(g.lens, function(){
          if(g.key) exSelectSubject(g.lens, g.key);
          var row=document.querySelector('#ex-lens tr[data-exkey="'+(window.CSS&&CSS.escape?CSS.escape(g.key||""):g.key)+'"]');
          (row||el("ex-lens")).scrollIntoView({block:"nearest", behavior:"smooth"});
        });
      };
    });
  }

  // ── lenses ──
  var EX_COLS = {
    activities:[
      {k:"subject", label:"Activity", get:function(r){ return (r.subject||taskName(r.task)||"").toLowerCase(); },
        cell:function(r){ return '<b>'+esc(r.subject||taskName(r.task))+'</b><br><span class="ex-sub">'+(taskStdText(r.task)?'Std '+esc(taskStdText(r.task)):esc(r.uom||""))+' &middot; '+fmt(r.people)+' people</span>'; }},
      {k:"done_pct", label:"Done", num:1, tip:"recorded output ÷ requested quantity",
        cell:function(r){ return '<span class="'+exTintDone(r.done_pct)+'">'+exPct(r.done_pct)+'</span>'; }},
      {k:"out_pct", label:"Output vs target", num:1, tip:"output per person-day ÷ the daily target",
        cell:function(r){ return '<span class="'+exTintOut(r.out_pct)+'">'+exPct(r.out_pct)+'</span>'; }},
      {k:"cost_pct", label:"Cost/unit vs rate", num:1, tip:"pay ÷ output at the rate; 100% = exactly the rate",
        cell:function(r){ return '<span class="'+exTintCost(r.cost_pct)+'">'+exPct(r.cost_pct)+'</span>'; }},
      {k:"confirmed", label:"Earned KES", num:1, cell:function(r){ return money(r.confirmed); }},
      {k:"trend", label:"Weekly KES", nosort:1, sm:1, cell:function(r){ return exSpark(r.trend); }}
    ],
    workers:[
      {k:"name", label:"Worker", get:function(r){ return (r.name||"").toLowerCase(); },
        cell:function(r){ return '<b>'+esc(r.name||r.employee)+'</b><br><span class="ex-sub">'+esc(r.employee)+' &middot; '+esc(r.employment_type||"—")+'</span>'; }},
      {k:"farm", label:esc(TX("top_singular","Farm")), get:function(r){ return (r.farm||"").toLowerCase(); }, sm:1,
        cell:function(r){ return esc(r.farm||"")+(r.farms>1?' <span class="ex-sub">+'+(r.farms-1)+'</span>':''); }},
      {k:"days", label:"Days", num:1, cell:function(r){ return fmt(r.days); }},
      {k:"confirmed", label:"Earned KES", num:1, tip:"confirmed pay",
        cell:function(r){ return money(r.confirmed)+(r.unpaid_confirmed>0?'<br><span class="ex-sub">'+money(r.unpaid_confirmed)+' not yet paid</span>':''); }},
      {k:"out_pct", label:"Output vs target", num:1, cell:function(r){ return '<span class="'+exTintOut(r.out_pct)+'">'+exPct(r.out_pct)+'</span>'; }},
      {k:"noscan_days", label:"Flags", num:1, tip:"paid days with no check-in scan · days on two farms at once",
        cell:function(r){
          var f="";
          if(r.noscan_days) f+='<span class="ex-flag bad" title="paid days with no check-in scan">⚠ '+r.noscan_days+' no scan</span>';
          if(r.multi_farm_days) f+='<span class="ex-flag warn" title="days recorded on two farms">⇄ '+r.multi_farm_days+' two farms</span>';
          return f||'<span class="ex-sub">—</span>'; }}
    ],
    staff:[
      {k:"name", label:"Person", get:function(r){ return (r.name||"").toLowerCase(); },
        cell:function(r){ return '<b>'+esc(r.name||r.user)+'</b><br><span class="ex-sub">'+
          [r.requests?r.requests+" requests":"", r.crews?r.crews+" crews":"", r.actuals?r.actuals+" actuals":"", r.approvals?r.approvals+" approvals":""]
            .filter(function(x){return x;}).join(" &middot; ")+'</span>'; }},
      {k:"requested", label:"Requested KES", num:1, cell:function(r){ return r.requested?money(r.requested):'<span class="ex-sub">—</span>'; }},
      {k:"delivered", label:"Delivered KES", num:1, tip:"confirmed pay on their requests", cell:function(r){ return r.requested?money(r.delivered):'<span class="ex-sub">—</span>'; }},
      {k:"delivered_pct", label:"Delivered", num:1, cell:function(r){ return r.requested?'<span class="'+exTintDone(r.delivered_pct)+'">'+exPct(r.delivered_pct)+'</span>':'<span class="ex-sub">—</span>'; }},
      {k:"approve_median_min", label:"Approves in", num:1, tip:"median time from submitted to their approval",
        cell:function(r){ return r.approvals?exHours(r.approve_median_min):'<span class="ex-sub">—</span>'; }}
    ],
    blocks:[
      {k:"block", label:esc(TX("unit_singular","Block")), get:function(r){ return (r.block||"").toLowerCase(); },
        cell:function(r){ return '<b>'+esc(lbl(r.block)||"—")+'</b><br><span class="ex-sub">'+fmt(r.activities)+' activities &middot; '+fmt(r.people)+' people</span>'; }},
      {k:"farm", label:esc(TX("top_singular","Farm")), sm:1, get:function(r){ return (r.farm||"").toLowerCase(); }, cell:function(r){ return esc(r.farm||""); }},
      {k:"recorded", label:"Labour KES", num:1, cell:function(r){ return money(r.recorded); }},
      {k:"kes_per_ha", label:"KES / ha", num:1, tip:"labour KES ÷ the block's area; — where no area is recorded",
        cell:function(r){ return r.kes_per_ha!=null?money(r.kes_per_ha):'<span class="ex-sub" title="no area recorded on this block">—</span>'; }},
      {k:"person_days", label:"Person-days", num:1, cell:function(r){ return fmt(r.person_days); }},
      {k:"trend", label:"Weekly KES", nosort:1, sm:1, cell:function(r){ return exSpark(r.trend); }}
    ]
  };
  var EX_DEFAULT_SORT = {activities:"confirmed", workers:"confirmed", staff:"requested", blocks:"recorded"};
  var EX_HEAT = {
    activities:{label:"Output vs target, by week", diverge:true},
    workers:{label:"KES recorded, by week"},
    staff:{label:"Delivered % of requested, by week of request", pct:true},
    blocks:{label:"Labour KES, by week"}
  };

  function exSpark(trend){
    var wks=exWeeks(), vals=wks.map(function(w){ return (trend||{})[w]||0; });
    var max=Math.max.apply(null, vals.concat([1])), W=88, H=22;
    var pts=vals.map(function(v,i){ return (wks.length>1?i/(wks.length-1)*W:W/2).toFixed(1)+","+(H-2-(v/max)*(H-4)).toFixed(1); }).join(" ");
    return '<svg class="ex-spark" width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'" aria-hidden="true">'+
      '<polyline points="'+pts+'" fill="none" stroke="#2a78d6" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  }
  function exRowKey(lens, r){ return lens==="activities"?r.task:(lens==="workers"?r.employee:(lens==="staff"?r.user:r.block)); }
  function exRowName(lens, r){
    return lens==="activities"?(r.subject||taskName(r.task)):(lens==="workers"?(r.name||r.employee):(lens==="staff"?(r.name||r.user):lbl(r.block)));
  }
  function exMatch(lens, r){
    if(!EX.q) return true;
    return [exRowName(lens,r), exRowKey(lens,r), r.farm, r.employment_type, r.uom].join(" ").toLowerCase().indexOf(EX.q)>=0;
  }
  function exSorted(lens){
    var rows=((EX.lenses[lens]||{}).rows||[]).filter(function(r){ return exMatch(lens,r); });
    var s=EX.sort[lens]||{k:EX_DEFAULT_SORT[lens], dir:-1};
    var col=EX_COLS[lens].filter(function(c){ return c.k===s.k; })[0];
    var get=(col&&col.get)||function(r){ return r[s.k]; };
    return rows.slice().sort(function(a,b){
      var x=get(a), y=get(b);
      if(x==null&&y==null) return 0; if(x==null) return 1; if(y==null) return -1;
      return (x<y?-1:(x>y?1:0))*s.dir;
    });
  }

  function exLoadLens(lens, after){
    var box=el("ex-lens"); if(!box) return;
    if(EX.view==="heat"){
      var have=EX.lenses[lens];
      if(have && have.grid){ exDrawLens(); if(after) after(); return; }
      box.style.opacity=".55";
      call(exArgs({action:"ex_lens", lens:lens, heat:1})).then(function(d){
        EX.lenses[lens]=d; box.style.opacity=""; exDrawLens(); if(after) after();
      });
      return;
    }
    if(EX.lenses[lens]){ exDrawLens(); if(after) after(); return; }
    call(exArgs({action:"ex_lens", lens:lens})).then(function(d){ EX.lenses[lens]=d; exDrawLens(); if(after) after(); });
  }

  function exDrawLens(){
    var box=el("ex-lens"); if(!box) return;
    var lens=EX.lens, rows=exSorted(lens);
    if(!(EX.lenses[lens])){ box.innerHTML='<div class="loading">Reading&hellip;</div>'; return; }
    if(!rows.length){ box.innerHTML='<div class="empty">Nothing recorded '+(EX.q?'matches “'+esc(EX.q)+'” ':'')+'in this slice.</div>'; return; }
    if(EX.view==="heat"){ box.innerHTML=exHeat(lens, rows); exWireHeat(box, lens); return; }
    var cols=EX_COLS[lens], s=EX.sort[lens]||{k:EX_DEFAULT_SORT[lens], dir:-1};
    var h='<div class="ex-scroll"><table class="pc-tbl"><thead><tr>'+cols.map(function(c){
      return '<th'+(c.nosort?'':' data-exsort="'+c.k+'"')+' class="'+(c.num?'n ':'')+(c.sm?'ex-hide-sm ':'')+(s.k===c.k?'sorted':'')+'"'+
        (c.tip?' title="'+esc(c.tip)+'"':'')+'>'+c.label+(s.k===c.k?(s.dir<0?' ↓':' ↑'):'')+'</th>';
    }).join("")+'</tr></thead><tbody>';
    rows.slice(0,400).forEach(function(r){
      var key=exRowKey(lens,r), open=EX.open&&EX.open.lens===lens&&EX.open.key===key;
      h+='<tr class="ex-row'+(open?' open':'')+'" data-exkey="'+esc(key||"")+'">'+cols.map(function(c){
        return '<td class="'+(c.num?'n ':'')+(c.sm?'ex-hide-sm':'')+'">'+c.cell(r)+'</td>'; }).join("")+'</tr>';
      if(open) h+='<tr class="ex-det"><td colspan="'+cols.length+'"><div class="pcd" id="exd"><div class="loading">Reading everything behind '+esc(exRowName(lens,r))+'&hellip;</div></div></td></tr>';
    });
    h+='</tbody></table></div>';
    if(rows.length>400) h+='<div class="pcd-note">Showing the first 400 of '+fmt(rows.length)+'. Narrow the dates, '+esc(TX("top_singular","Farm")).toLowerCase()+' or search to see the rest.</div>';
    box.innerHTML=h;
    box.querySelectorAll("th[data-exsort]").forEach(function(th){
      th.onclick=function(){
        var k=th.getAttribute("data-exsort"), cur=EX.sort[lens]||{k:EX_DEFAULT_SORT[lens], dir:-1};
        EX.sort[lens]={k:k, dir:cur.k===k?-cur.dir:-1}; exDrawLens();
      };
    });
    box.querySelectorAll("tr[data-exkey]").forEach(function(tr){
      tr.onclick=function(){
        var k=tr.getAttribute("data-exkey");
        var same=EX.open&&EX.open.lens===lens&&EX.open.key===k;
        EX.open=same?null:{lens:lens, key:k};
        exDrawLens();
        if(!same) exSelectSubject(lens, k);
      };
    });
    if(EX.open && EX.open.lens===lens) exLoadDetail(lens, EX.open.key);
  }

  function exHeatColor(v, max, diverge){
    if(v==null) return "#f4f3ef";
    if(diverge){
      // diverging around 100%: blue above target, red below, grey at target
      var d=Math.max(-1, Math.min(1, (v-100)/40));
      if(Math.abs(d)<0.06) return "#f0efec";
      var blue=["#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf"], red=["#fcdcd9","#f6b4ae","#ee8a83","#e34948","#c22f2f"];
      var i=Math.min(4, Math.floor(Math.abs(d)*5));
      return d>0?blue[i]:red[i];
    }
    var ramp=["#e7f0fc","#cde2fb","#9ec5f4","#6da7ec","#3987e5","#2a78d6","#1c5cab","#104281"];
    if(!v) return "#f4f3ef";
    return ramp[Math.min(7, Math.floor(v/(max||1)*7.999))];
  }
  function exHeat(lens, rows){
    var grid=(EX.lenses[lens]||{}).grid||{}, wks=exWeeks(), cfg=EX_HEAT[lens];
    rows=rows.slice(0,60);
    var max=0;
    rows.forEach(function(r){ var g=grid[exRowKey(lens,r)]||{}; wks.forEach(function(w){ if(g[w]!=null && g[w]>max) max=g[w]; }); });
    if(cfg.pct) max=Math.max(100, max);
    var h='<div class="ex-heat-legend"><b style="color:var(--ink)">'+esc(cfg.label)+'</b>'+
      (cfg.diverge
        ? '<span>below target</span><s style="background:linear-gradient(90deg,#c22f2f,#f6b4ae,#f0efec,#9ec5f4,#256abf)"></s><span>above target</span>'
        : '<span>0</span><s style="background:linear-gradient(90deg,#e7f0fc,#6da7ec,#104281)"></s><span>'+(cfg.pct?fmt(max,0)+'%':money(max)+(lens==="staff"?'':' KES'))+'</span>')+
      '<span style="margin-left:auto">click a cell to chart that row from that week</span></div>';
    h+='<div class="ex-scroll"><table class="pc-tbl ex-heat"><thead><tr><th>'+EX_COLS[lens][0].label+'</th>'+
      wks.map(function(w){ return '<th class="n" style="text-align:center">'+esc(shortDate(w))+'</th>'; }).join("")+'</tr></thead><tbody>';
    rows.forEach(function(r){
      var key=exRowKey(lens,r), g=grid[key]||{};
      h+='<tr><td><b>'+esc(exRowName(lens,r))+'</b>'+(lens==="activities"?taskStdSub(r.task):'')+'</td>'+wks.map(function(w){
        var v=g[w];
        var txt=v==null?'':(cfg.diverge||cfg.pct?fmt(v,0):'');
        var dark=v!=null && !cfg.diverge && v/(max||1)>0.55;
        if(cfg.diverge && v!=null && Math.abs(v-100)>24) dark=true;
        return '<td class="c" data-exhk="'+esc(key||"")+'" data-exhw="'+w+'" data-exhv="'+(v==null?'':v)+'" style="background:'+exHeatColor(v,max,cfg.diverge)+
          ';color:'+(dark?'#fff':'#52514e')+'">'+txt+'</td>';
      }).join("")+'</tr>';
    });
    h+='</tbody></table></div>';
    if(((EX.lenses[lens]||{}).rows||[]).length>60) h+='<div class="pcd-note">The 60 rows at the top of the current sort. Sort or search in List view to choose others.</div>';
    return h;
  }
  function exWireHeat(box, lens){
    var cfg=EX_HEAT[lens];
    box.querySelectorAll("td[data-exhk]").forEach(function(td){
      var name=td.parentNode.firstChild.textContent;
      td.onmousemove=function(ev){
        var v=td.getAttribute("data-exhv");
        exShowTip(ev, name+" · week of "+shortDate(td.getAttribute("data-exhw")),
          [{label:cfg.label.split(",")[0], value:v===''?"nothing recorded":(cfg.diverge||cfg.pct?fmt(+v,0)+"%":money(+v)+" KES")}]);
      };
      td.onmouseleave=exHideTip;
      td.onclick=function(){
        exHideTip();
        EX.view="list"; EX.open={lens:lens, key:td.getAttribute("data-exhk")};
        document.querySelectorAll("#wm-ex [data-exview]").forEach(function(x){ x.classList.toggle("on", x.getAttribute("data-exview")==="list"); });
        exDrawLens(); exSelectSubject(lens, td.getAttribute("data-exhk"));
        var c=el("ex-chart"); if(c) c.scrollIntoView({block:"nearest", behavior:"smooth"});
      };
    });
  }

  // ── drill-down ──
  function exLoadDetail(lens, key){
    var kind={activities:"activity", workers:"worker", staff:"staff", blocks:"block"}[lens];
    var ck=lens+"|"+key;
    if(EX.details[ck]){ exDrawDetail(lens, key, EX.details[ck]); return; }
    call(exArgs({action:"ex_detail", kind:kind, key:key})).then(function(d){
      EX.details[ck]=d; if(EX.open&&EX.open.key===key) exDrawDetail(lens, key, d);
    }).catch(function(){ var b=el("exd"); if(b) b.innerHTML='<div class="empty">Could not load this row.</div>'; });
  }
  var EX_TAB = {};
  function exDrawDetail(lens, key, d){
    var box=el("exd"); if(!box) return;
    if(d.error){ box.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
    var row=((EX.lenses[lens]||{}).rows||[]).filter(function(r){ return exRowKey(lens,r)===key; })[0]||{};
    var cell=function(l,v,sub,cls){ return '<div class="pcd-m'+(cls?' '+cls:'')+'"><span>'+l+'</span><b>'+v+'</b>'+(sub?'<i>'+sub+'</i>':'')+'</div>'; };
    var h='', tabs=[];
    if(lens!=="staff"){
      var o=d.overview||{};
      var sal=o.qty?o.salaried_qty/o.qty*100:null;
      h+='<div class="pcd-money">'+
        cell("Recorded", money(o.recorded)+' <small>KES</small>', fmt(o.person_days)+' person-days')+
        cell("Confirmed", money(o.confirmed), o.recorded?fmt(o.confirmed/o.recorded*100,0)+'% of recorded':'', 'good')+
        cell("Paid out", money(o.paid_out), "in payment runs marked Paid", o.paid_out?'good':'')+
        cell("Output vs target", exPct(o.out_pct), "per person-day", o.out_pct!=null&&o.out_pct<80?'bad':'')+
        cell("Cost/unit vs rate", exPct(o.cost_pct), "100% = exactly the rate", o.cost_pct!=null&&o.cost_pct>115?'bad':'')+
        cell("By salaried staff", sal==null?"—":fmt(sal,0)+"%", "of output, at no piece-rate pay")+
        cell("People", fmt(o.people), fmt(o.days)+' days worked')+
        (lens==="activities"&&taskStdText(key)?cell("Standard", esc(taskStdText(key).split(" · ")[0]), esc(taskStdText(key).split(" · ").slice(1).join(" · ")||"daily target per person")):'')+
        (lens==="blocks"?cell("Area", d.area_ha?fmt(d.area_ha,2)+" ha":"not recorded", d.area_ha?money(o.recorded/d.area_ha)+' KES/ha':''):'')+
      '</div>';
      if(lens!=="activities") tabs.push(["acts","Activities",d.by_activity]);
      if(lens!=="workers") tabs.push(["workers","Workers",d.by_worker]);
      if(lens!=="blocks") tabs.push(["blocks",esc(TX("unit_plural","Blocks")),d.by_block]);
      tabs.push(["plans","Master plans",d.by_plan]);
      tabs.push(["weeks","Weeks",d.by_week]);
      tabs.push(["days", lens==="workers"?"Days":"Actuals", d.days]);
    } else {
      tabs=[["reqs","Requests",d.requests],["crews","Crews",d.crews],["acts_in","Actuals entered",d.actuals],["apprs","Approvals",d.approvals]];
    }
    var tab=EX_TAB[lens]; if(!tabs.some(function(t){ return t[0]===tab; })) tab=tabs[0][0];
    h+='<div class="pcd-tabs">'+tabs.map(function(t){
      return '<button type="button" data-extab="'+t[0]+'"'+(t[0]===tab?' class="on"':'')+'>'+t[1]+'<i>'+((t[2]||[]).length)+'</i></button>'; }).join("")+
      (lens==="blocks"?'<button type="button" data-excc="1" style="margin-left:auto">Open in Cost centres ↗</button>':'')+
      '</div><div class="pcd-pane">'+exPane(lens, tab, d)+'</div>';
    box.innerHTML=h;
    box.querySelectorAll("[data-extab]").forEach(function(b){
      b.onclick=function(e){ e.stopPropagation(); EX_TAB[lens]=b.getAttribute("data-extab"); exDrawDetail(lens, key, d); };
    });
    var cc=box.querySelector("[data-excc]");
    if(cc) cc.onclick=function(){
      var q=el("cc-q"); if(q){ q.value=lbl(key); q.dispatchEvent(new Event("input",{bubbles:true})); q.dispatchEvent(new Event("change",{bubbles:true})); }
      var c=el("cc-list")||q; if(c) c.scrollIntoView({block:"start", behavior:"smooth"});
    };
    box.querySelectorAll("tr[data-open]").forEach(function(tr){
      tr.onclick=function(e){
        e.stopPropagation();
        var k=tr.getAttribute("data-open"), v=tr.getAttribute("data-v");
        if(k==="req") openPlanModal(v); else if(k==="act") openActualModal(v);
        else if(k==="emp") openEmpModal(v); else if(k==="pay") openPaymentModal(v);
        else if(k==="mp"){ EX.chart.mode="measures"; EX.chart.plan=v; EX.chart.activity=lens==="activities"?key:"";
          EX.chart.kind=EX.chart.activity?"activity":"estate"; EX.chart.key=EX.chart.activity; exDrawChartFrame(); exLoadSeries();
          var c=el("ex-chart"); if(c) c.scrollIntoView({block:"nearest", behavior:"smooth"}); }
      };
    });
  }
  function exPane(lens, tab, d){
    var T=function(head, body, note){
      return '<table class="pc-tbl"><thead><tr>'+head.map(function(c){
        return '<th'+(c.charAt(0)==="#"?' class="n"':'')+'>'+c.replace(/^#/,"")+'</th>'; }).join("")+'</tr></thead><tbody>'+
        (body||'<tr><td colspan="'+head.length+'" class="empty">Nothing in this slice.</td></tr>')+'</tbody></table>'+(note?'<div class="pcd-note">'+note+'</div>':'');
    };
    var n=function(v,dp){ return '<td class="n">'+fmt(v,dp||0)+'</td>'; };
    var k=function(v){ return '<td class="n">'+money(v)+'</td>'; };
    var g=function(r){ return '<td class="n"><span class="'+exTintOut(r.out_pct)+'">'+exPct(r.out_pct)+'</span></td>'; };
    var grp=function(rows, first, opener){
      var b="";
      (rows||[]).forEach(function(r){
        b+='<tr'+(opener?' data-open="'+opener+'" data-v="'+esc(r.k||"")+'"':'')+'>'+first(r)+n(r.person_days)+n(r.people)+
          '<td class="n">'+fmt(r.qty)+' <span class="ex-sub">'+esc(r.uom||"")+'</span></td>'+g(r)+k(r.recorded)+k(r.confirmed)+'</tr>';
      });
      return b;
    };
    var head=["#Person-days","#People","#Output","#Output vs target","#Recorded KES","#Confirmed KES"];
    if(tab==="acts") return T(["Activity"].concat(head), grp(d.by_activity, function(r){ return '<td><b>'+esc(r.label||taskName(r.k))+'</b>'+taskStdSub(r.k)+'</td>'; }));
    if(tab==="workers") return T(["Worker"].concat(head), grp(d.by_worker, function(r){ return '<td><b>'+esc(r.label||r.k)+'</b><br><span class="ex-sub">'+esc(r.k)+'</span></td>'; }, "emp"),
      "Click a worker for their full record.");
    if(tab==="blocks") return T([esc(TX("unit_singular","Block"))].concat(head), grp(d.by_block, function(r){ return '<td><b>'+esc(lbl(r.k)||"—")+'</b> <span class="ex-sub">'+esc(r.label||"")+'</span></td>'; }));
    if(tab==="plans") return T(["Master plan"].concat(head), grp(d.by_plan, function(r){
        return '<td><b>'+esc(r.k||"No plan named")+'</b> <span class="ex-sub">'+esc(r.label||"")+'</span></td>'; }, "mp"),
      "Click a plan to chart "+(lens==="activities"?"this activity within it":"it")+".");
    if(tab==="weeks") return T(["Week of"].concat(head), grp((d.by_week||[]).slice().sort(function(a,b){ return a.k<b.k?1:-1; }),
      function(r){ return '<td><b>'+esc(shortDate(r.k))+'</b></td>'; }));
    var b="";
    if(tab==="days" && lens==="workers"){
      (d.days||[]).forEach(function(r){
        var sc=r.scanned==null?'<span class="ex-sub" title="before this site had scans">—</span>':(r.scanned?'<span class="ex-good" title="checked in that day">✓</span>':'<span class="ex-bad" title="no check-in scan that day">✗</span>');
        b+='<tr data-open="act" data-v="'+esc(r.actual)+'"><td><b>'+esc(shortDate(r.work_date))+'</b></td><td>'+esc(r.subject||taskName(r.task))+taskStdSub(r.task)+'</td>'+
          '<td>'+esc(lbl(r.block))+'</td>'+'<td class="n">'+fmt(r.qty)+' <span class="ex-sub">'+esc(r.uom||"")+'</span></td>'+n(r.hours,1)+k(r.amount)+
          '<td>'+stateTag(r.workflow_state)+'</td><td style="text-align:center">'+sc+'</td></tr>';
      });
      return T(["Date","Activity",esc(TX("unit_singular","Block")),"#Output","#Hours","#KES","State","Scan"], b, "Click a day for its actual.");
    }
    if(tab==="days"){
      (d.days||[]).forEach(function(r){
        b+='<tr data-open="act" data-v="'+esc(r.actual)+'"><td><b>'+esc(r.actual)+'</b></td><td>'+esc(r.subject||taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(lbl(r.block))+'</td>'+
          '<td>'+esc(shortDate(r.from_date))+' &ndash; '+esc(shortDate(r.to_date))+'</td>'+n(r.people)+
          '<td class="n">'+fmt(r.qty)+' <span class="ex-sub">'+esc(r.uom||"")+'</span></td>'+k(r.amount)+'<td>'+stateTag(r.workflow_state)+'</td></tr>';
      });
      return T(["Actual","Activity",esc(TX("unit_singular","Block")),"Dates","#People","#Output","#KES","State"], b, "Click an actual for its day-by-day record.");
    }
    if(tab==="reqs"){
      (d.requests||[]).forEach(function(r){
        b+='<tr data-open="req" data-v="'+esc(r.name)+'"><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.subject||taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(lbl(r.block))+'</td>'+
          '<td>'+esc(shortDate(r.from_date))+' &ndash; '+esc(shortDate(r.to_date))+'</td>'+k(r.total_cost)+k(r.delivered)+
          '<td>'+stateTag(r.workflow_state)+'</td><td>'+esc(r.approved_by||"")+'</td></tr>';
      });
      return T(["Request","Activity",esc(TX("unit_singular","Block")),"Dates","#Requested KES","#Delivered KES","State","Approved by"], b, "Click a request for its full trail.");
    }
    if(tab==="crews"){
      (d.crews||[]).forEach(function(r){
        b+='<tr data-open="req" data-v="'+esc(r.planner_request||"")+'"><td><b>'+esc(r.name)+'</b></td><td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(lbl(r.block))+'</td>'+
          '<td>'+esc(shortDate(r.from_date))+' &ndash; '+esc(shortDate(r.to_date))+'</td>'+n(r.workers)+'<td>'+stateTag(r.workflow_state)+'</td></tr>';
      });
      return T(["Crew","Activity",esc(TX("unit_singular","Block")),"Dates","#Workers","State"], b, "Click a crew for the request behind it.");
    }
    if(tab==="acts_in"){
      (d.actuals||[]).forEach(function(r){
        b+='<tr data-open="act" data-v="'+esc(r.name)+'"><td><b>'+esc(r.name)+'</b></td><td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(lbl(r.block))+'</td>'+
          '<td>'+esc(shortDate(r.from_date))+' &ndash; '+esc(shortDate(r.to_date))+'</td>'+n(r.qty)+k(r.pay)+'<td>'+stateTag(r.workflow_state)+'</td></tr>';
      });
      return T(["Actual","Activity",esc(TX("unit_singular","Block")),"Dates","#Output","#Pay KES","State"], b);
    }
    if(tab==="apprs"){
      (d.approvals||[]).forEach(function(r){
        b+='<tr data-open="req" data-v="'+esc(r.name)+'"><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.subject||"")+'</td><td>'+esc(r.requested_by||"")+'</td>'+
          k(r.total_cost)+'<td>'+esc(fmtDT(r.approved_at))+'</td><td class="n">'+exHours(r.minutes)+'</td></tr>';
      });
      return T(["Request","Activity","Requested by","#KES","Approved","#Took"], b, "Took = from submitted to this person's approval.");
    }
    return "";
  }

  // ── the trends chart ──
  // a lens row clicked becomes the chart's subject
  function exSelectSubject(lens, key){
    var kind={activities:"activity", workers:"worker", blocks:"block", staff:null}[lens];
    if(!kind) return;
    var row=((EX.lenses[lens]||{}).rows||[]).filter(function(r){ return exRowKey(lens,r)===key; })[0];
    var c=EX.chart;
    if(c.mode==="compare"){
      if(c.cmpKind!==kind){ c.cmpKind=kind; c.cmpKeys=[]; }
      if(c.cmpKeys.indexOf(key)<0){ c.cmpKeys.push(key); if(c.cmpKeys.length>6) c.cmpKeys.shift(); }
    } else {
      c.kind=kind; c.key=key; c.keyLabel=row?exRowName(lens,row):key;
      if(kind==="activity") c.activity=key; else { c.activity=""; if(kind!=="estate") c.plan=""; }
    }
    exDrawChartFrame(); exLoadSeries();
  }
  function exSubjectLabel(kind, key){
    var lens={activity:"activities", worker:"workers", block:"blocks"}[kind];
    if(kind==="plan") return key;
    var row=((EX.lenses[lens]||{}).rows||[]).filter(function(r){ return exRowKey(lens,r)===key; })[0];
    return row?exRowName(lens,row):key;
  }
  function exDrawChartFrame(){
    var box=el("ex-chart"); if(!box) return;
    var c=EX.chart;
    var acts=((EX.lenses.activities||{}).rows||[]).slice().sort(function(a,b){ return (a.subject||"")<(b.subject||"")?-1:1; });
    var plans=EX.plans||[];
    var h='<div class="ex-chart-h"><h4>Trends</h4>'+
      '<div class="ex-pills"><button type="button" data-exmode="measures"'+(c.mode==="measures"?' class="on"':'')+'>Measures</button>'+
      '<button type="button" data-exmode="compare"'+(c.mode==="compare"?' class="on"':'')+'>Compare</button></div>';
    if(c.mode==="measures"){
      h+='<div class="ex-pick">'+
        '<select id="ex-cplan" title="Master plan"><option value="">All master plans</option>'+plans.map(function(p){
          return '<option value="'+esc(p.plan)+'"'+(c.plan===p.plan?' selected':'')+'>'+esc(p.plan)+' · '+esc(p.farm)+' · '+esc(shortDate(p.period_from))+'</option>'; }).join("")+'</select>'+
        '<select id="ex-cact" title="Activity"><option value="">All activities</option>'+acts.map(function(a){
          return '<option value="'+esc(exRowKey("activities",a))+'"'+(c.activity===a.task?' selected':'')+'>'+esc(a.subject||taskName(a.task))+(taskStdText(a.task)?' — '+esc(taskStdText(a.task)):'')+'</option>'; }).join("")+'</select>'+
        ((c.kind==="worker"||c.kind==="block")?'<span class="ex-chip">'+(c.kind==="worker"?"Worker: ":esc(TX("unit_singular","Block"))+": ")+esc(c.keyLabel||c.key)+
          '<button type="button" data-exclear="1" title="Back to all work">×</button></span>':'')+
        '</div>';
    } else {
      h+='<div class="ex-pick">'+
        '<select id="ex-ckind"><option value="activity"'+(c.cmpKind==="activity"?' selected':'')+'>Activities</option>'+
          '<option value="plan"'+(c.cmpKind==="plan"?' selected':'')+'>Master plans</option>'+
          '<option value="worker"'+(c.cmpKind==="worker"?' selected':'')+'>Workers</option>'+
          '<option value="block"'+(c.cmpKind==="block"?' selected':'')+'>'+esc(TX("unit_plural","Blocks"))+'</option></select>'+
        '<select id="ex-cmeas">'+EX_MEASURES.filter(function(m){ return !((c.cmpKind==="worker"||c.cmpKind==="block") && (m.k==="planned"||(c.cmpKind==="worker"&&m.k==="requested"))); })
          .map(function(m){ return '<option value="'+m.k+'"'+(c.cmpMeasure===m.k?' selected':'')+'>'+esc(m.label)+'</option>'; }).join("")+'</select>'+
        (c.cmpKind==="activity"||c.cmpKind==="plan"
          ? '<select id="ex-cadd"><option value="">+ Add '+(c.cmpKind==="plan"?"a master plan":"an activity")+'…</option>'+
              (c.cmpKind==="plan"?plans.map(function(p){ return '<option value="'+esc(p.plan)+'">'+esc(p.plan)+' · '+esc(p.farm)+'</option>'; })
                                 :acts.map(function(a){ return '<option value="'+esc(exRowKey("activities",a))+'">'+esc(a.subject||taskName(a.task))+(taskStdText(a.task)?' — '+esc(taskStdText(a.task)):'')+'</option>'; })).join("")+'</select>'
          : '<span>pick '+(c.cmpKind==="worker"?"workers":esc(TX("unit_plural","Blocks")).toLowerCase())+' from the list below</span>')+
        c.cmpKeys.map(function(k,i){ return '<span class="ex-chip" style="background:#fff;border:1px solid var(--line);color:var(--ink)"><i style="display:inline-block;width:12px;height:2px;background:'+EX_SUBJECT_COLORS[i]+'"></i>'+
          esc(exSubjectLabel(c.cmpKind,k))+'<button type="button" data-exdrop="'+esc(k)+'" style="color:var(--mute)">×</button></span>'; }).join("")+
        '</div>';
    }
    var kesOn=c.mode==="compare"?exMeasure(c.cmpMeasure).unit==="kes":EX_MEASURES.some(function(m){ return c.on[m.k] && m.unit==="kes"; });
    h+='<div class="ex-pills ex-right">'+
      (kesOn?'<button type="button" data-exrun="1"'+(c.running?' class="on"':'')+' title="KES lines add up from the first day of the range">Running total</button>':'')+
      '<button type="button" data-extable="1"'+(c.table?' class="on"':'')+'>Table</button></div></div>';
    if(c.mode==="measures"){
      h+='<div class="ex-legend">'+EX_MEASURES.map(function(m){
        var na=(m.k==="planned"&&(c.kind==="worker"||c.kind==="block"))||(m.k==="requested"&&c.kind==="worker");
        if(na) return "";
        return '<button type="button" data-exm="'+m.k+'" class="'+(c.on[m.k]?'':'off')+'" title="'+(c.on[m.k]?'Hide':'Show')+' this line">'+
          '<i style="'+(m.dash?'background:none;border-top:2px dashed '+m.color+';height:0':'background:'+m.color)+'"></i>'+esc(m.label)+'</button>';
      }).join("")+'</div>';
    }
    h+='<div id="ex-plot"><div class="loading">Drawing&hellip;</div></div>';
    box.innerHTML=h;
    box.querySelectorAll("[data-exmode]").forEach(function(b){ b.onclick=function(){ c.mode=b.getAttribute("data-exmode"); exDrawChartFrame(); exLoadSeries(); }; });
    var cp=el("ex-cplan"); if(cp) cp.onchange=function(){ c.plan=cp.value; if(!c.activity){ c.kind="estate"; c.key=""; c.keyLabel=""; } exDrawChartFrame(); exLoadSeries(); };
    var ca=el("ex-cact"); if(ca) ca.onchange=function(){ c.activity=ca.value; c.kind=ca.value?"activity":"estate"; c.key=ca.value;
      c.keyLabel=ca.value?ca.options[ca.selectedIndex].text:""; exDrawChartFrame(); exLoadSeries(); };
    var ck=el("ex-ckind"); if(ck) ck.onchange=function(){ c.cmpKind=ck.value; c.cmpKeys=[]; exDrawChartFrame(); exLoadSeries(); };
    var cm=el("ex-cmeas"); if(cm) cm.onchange=function(){ c.cmpMeasure=cm.value; exDrawChartFrame(); exLoadSeries(); };
    var cadd=el("ex-cadd"); if(cadd) cadd.onchange=function(){ if(cadd.value && c.cmpKeys.indexOf(cadd.value)<0 && c.cmpKeys.length<6){ c.cmpKeys.push(cadd.value); } exDrawChartFrame(); exLoadSeries(); };
    box.querySelectorAll("[data-exdrop]").forEach(function(b){ b.onclick=function(){ var k=b.getAttribute("data-exdrop"); c.cmpKeys=c.cmpKeys.filter(function(x){ return x!==k; }); exDrawChartFrame(); exLoadSeries(); }; });
    var cl=box.querySelector("[data-exclear]"); if(cl) cl.onclick=function(){ c.kind=c.activity?"activity":"estate"; c.key=c.activity; c.keyLabel=""; exDrawChartFrame(); exLoadSeries(); };
    box.querySelectorAll("[data-exm]").forEach(function(b){ b.onclick=function(){ var k=b.getAttribute("data-exm"); c.on[k]=c.on[k]?0:1; exDrawChartFrame(); exLoadSeries(); }; });
    var rb=box.querySelector("[data-exrun]"); if(rb) rb.onclick=function(){ c.running=!c.running; rb.classList.toggle("on", c.running); exDrawPlot(); };
    var tb=box.querySelector("[data-extable]"); if(tb) tb.onclick=function(){ c.table=!c.table; tb.classList.toggle("on", c.table); exDrawPlot(); };
  }
  function exLoadSeries(){
    var c=EX.chart, seq=++c.seq, a;
    if(c.mode==="compare"){
      if(!c.cmpKeys.length){ c.data=null; var p=el("ex-plot"); if(p) p.innerHTML='<div class="empty">Add up to six '+(c.cmpKind==="plan"?"master plans":(c.cmpKind==="activity"?"activities":(c.cmpKind==="worker"?"workers":esc(TX("unit_plural","Blocks")).toLowerCase())))+' to compare one measure, one line each.</div>'; return; }
      a=exArgs({action:"ex_series", mode:"compare", kind:c.cmpKind, keys:c.cmpKeys.join("||"), measures:c.cmpMeasure});
    } else {
      var ms=EX_MEASURES.filter(function(m){ return c.on[m.k]; }).map(function(m){ return m.k; });
      if(!ms.length){ c.data=null; var p2=el("ex-plot"); if(p2) p2.innerHTML='<div class="empty">Switch a line on in the legend above.</div>'; return; }
      a=exArgs({action:"ex_series", mode:"measures", kind:c.kind, keys:c.key||"", plan:c.plan||"", measures:ms.join(",")});
    }
    var plot=el("ex-plot"); if(plot) plot.style.opacity=".55";
    call(a).then(function(d){
      if(seq!==c.seq) return;
      c.data=d; if(plot) plot.style.opacity=""; exDrawPlot();
    }).catch(function(){ if(seq!==c.seq) return; if(plot){ plot.style.opacity=""; plot.innerHTML='<div class="empty">Could not draw the chart.</div>'; } });
  }
  // series to draw: [{label, color, unit, panel, values:[...]}], one per line
  function exLines(){
    var c=EX.chart, d=c.data; if(!d) return [];
    var b=d.buckets||[], out=[];
    var vals=function(series, k, unit){
      var acc=0;
      return b.map(function(x){
        var v=(series[k]||{})[x];
        if(unit==="kes"){ v=v||0; if(c.running){ acc+=v; return acc; } return v; }
        return v==null?null:v;
      });
    };
    if(c.mode==="compare"){
      var m=exMeasure(c.cmpMeasure);
      (d.subjects||[]).forEach(function(s,i){
        out.push({label:exSubjectLabel(c.cmpKind==="plan"?"plan":c.cmpKind, s.key), color:EX_SUBJECT_COLORS[i], unit:m.unit, panel:m.panel, values:vals(s.series, m.k, m.unit)});
      });
    } else {
      var s0=(d.subjects||[])[0]||{series:{}};
      EX_MEASURES.forEach(function(m){
        if(!c.on[m.k] || !s0.series[m.k]) return;
        out.push({label:m.label, color:m.color, unit:m.unit, panel:m.panel, dash:m.dash, fill:m.fill, values:vals(s0.series, m.k, m.unit)});
      });
    }
    return out;
  }
  function exFmtV(v, unit){ if(v==null) return "—"; return unit==="kes"?money(v)+" KES":(unit==="pct"?fmt(v,0)+"%":fmt(v,1)); }
  function exDrawPlot(){
    var box=el("ex-plot"), c=EX.chart, d=c.data; if(!box||!d) return;
    var lines=exLines(), b=d.buckets||[];
    if(!lines.length || !b.length){ box.innerHTML='<div class="empty">Nothing recorded for this in the chosen dates.</div>'; return; }
    var title=c.mode==="compare"?exMeasure(c.cmpMeasure).label:
      ((c.kind==="activity"&&c.plan)?(c.keyLabel||exSubjectLabel("activity",c.key))+" within "+c.plan:
       (c.kind==="activity"?(c.keyLabel||exSubjectLabel("activity",c.key)):(c.kind==="worker"||c.kind==="block"?(c.keyLabel||c.key):(c.plan?c.plan:"All work"))));
    var gran=d.granularity==="day"?"per day":"per week";
    var sub=title+" · "+(c.running&&lines.some(function(l){ return l.unit==="kes"; })?"KES as a running total, ":"")+gran;
    if(c.table){
      var h='<div class="pcd-note" style="margin:4px 0 6px">'+esc(sub)+'</div><div class="ex-scroll" style="max-height:360px"><table class="pc-tbl"><thead><tr><th>'+(d.granularity==="day"?"Day":"Week of")+'</th>'+
        lines.map(function(l){ return '<th class="n">'+esc(l.label)+'</th>'; }).join("")+'</tr></thead><tbody>';
      b.forEach(function(x,i){ h+='<tr><td>'+esc(shortDate(x))+'</td>'+lines.map(function(l){ return '<td class="n">'+exFmtV(l.values[i], l.unit)+'</td>'; }).join("")+'</tr>'; });
      box.innerHTML=h+'</tbody></table></div>'; return;
    }
    // one small chart per unit, stacked on the same dates: never two scales on one axis
    var panels=["money","perf","people"].filter(function(p){ return lines.some(function(l){ return l.panel===p; }); });
    var W=Math.max(320, box.clientWidth||900), L=52, R=96, H=panels.length>1?170:250, T=12, B=26;
    var iw=W-L-R, ih=H-T-B;
    var xAt=function(i){ return L+(b.length>1?i/(b.length-1)*iw:iw/2); };
    // round tick steps (1, 2, 2.5, 5 x 10^n) aiming at about four gridlines
    var niceStep=function(max){
      var raw=max/4, mag=Math.pow(10, Math.floor(Math.log10(raw||1))), f=raw/mag;
      return (f<=1?1:(f<=2?2:(f<=2.5?2.5:(f<=5?5:10))))*mag;
    };
    var FONT='font-family="Poppins,sans-serif" font-size="9.5" fill="#8a8780"';
    var html='<div class="pcd-note" style="margin:4px 0 0">'+esc(sub)+'</div>';
    panels.forEach(function(p){
      var pl=lines.filter(function(l){ return l.panel===p; });
      var max=0; pl.forEach(function(l){ l.values.forEach(function(v){ if(v!=null&&v>max) max=v; }); });
      if(p==="perf") max=Math.max(max, 110);
      max=max||1;
      var step=niceStep(max), nice=Math.ceil(max/step)*step;
      var yAt=function(v){ return T+ih-(v/nice)*ih; };
      var s='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block" role="img" aria-label="'+esc(EX_PANELS[p])+'">';
      for(var g=0; g<=nice+1e-9; g+=step){
        var y=yAt(g).toFixed(1);
        s+='<line x1="'+L+'" y1="'+y+'" x2="'+(L+iw)+'" y2="'+y+'" stroke="rgba(10,10,10,0.06)" stroke-width="1"/>';
        s+='<text x="'+(L-8)+'" y="'+(+y+3)+'" text-anchor="end" '+FONT+'>'+(p==="money"?money(g):(p==="perf"?fmt(g,0)+"%":fmt(g,0)))+'</text>';
      }
      if(p==="perf") s+='<line x1="'+L+'" x2="'+(L+iw)+'" y1="'+yAt(100).toFixed(1)+'" y2="'+yAt(100).toFixed(1)+'" stroke="#8a8780" stroke-width="1" stroke-dasharray="3 3"/>'+
        '<text x="'+(L+4)+'" y="'+(yAt(100)-4).toFixed(1)+'" '+FONT+'>target / rate</text>';
      var every=Math.max(1, Math.ceil(b.length/8));
      b.forEach(function(x,i){ if(i%every===0||i===b.length-1) s+='<text x="'+xAt(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" '+FONT+'>'+esc(shortDate(x))+'</text>'; });
      var ends=[];
      // filled series first, so their wash sits under every line
      pl.slice().sort(function(a,b){ return (b.fill?1:0)-(a.fill?1:0); }).forEach(function(l){
        // a week with no work has no percentage: the line joins the weeks that do,
        // and when they are few each one gets a marker so a lone week still shows
        var pts=[]; l.values.forEach(function(v,i){ if(v!=null) pts.push([xAt(i), yAt(v), v]); });
        if(!pts.length) return;
        var d=pts.map(function(q,i){ return (i?"L":"M")+q[0].toFixed(1)+","+q[1].toFixed(1); }).join("");
        if(l.fill && pts.length>1) s+='<path d="'+d+'L'+pts[pts.length-1][0].toFixed(1)+','+(T+ih).toFixed(1)+'L'+pts[0][0].toFixed(1)+','+(T+ih).toFixed(1)+'Z" fill="'+l.color+'" fill-opacity="0.09"/>';
        s+='<path d="'+d+'" fill="none" stroke="'+l.color+'" stroke-width="2"'+(l.dash?' stroke-dasharray="6 4"':'')+' stroke-linejoin="round" stroke-linecap="round"/>';
        if(pts.length<b.length && pts.length<=12) pts.forEach(function(q){
          s+='<circle cx="'+q[0].toFixed(1)+'" cy="'+q[1].toFixed(1)+'" r="3.5" fill="'+l.color+'" stroke="#fff" stroke-width="1.5"/>'; });
        var last=pts[pts.length-1];
        ends.push({x:last[0], y:last[1], l:l, v:last[2]});
      });
      // the line's name at its end, in its colour, as the timeline does
      ends.sort(function(a,b){ return a.y-b.y; });
      for(var e=1;e<ends.length;e++){ var prev=ends[e-1].ly!=null?ends[e-1].ly:ends[e-1].y; if(ends[e].y-prev<12) ends[e].ly=prev+12; }
      ends.forEach(function(e){
        var ly=e.ly!=null?e.ly:e.y;
        var name=e.l.label.length>14?e.l.label.slice(0,13)+"…":e.l.label;
        s+='<text x="'+(e.x+6).toFixed(1)+'" y="'+(ly+3).toFixed(1)+'" font-family="Poppins,sans-serif" font-size="9.5" font-weight="600" style="fill:'+e.l.color+'">'+esc(name)+'</text>';
      });
      s+='<line class="xh" x1="0" x2="0" y1="'+T+'" y2="'+(T+ih)+'" style="display:none"/>';
      s+='<rect class="hit" x="'+L+'" y="'+T+'" width="'+iw+'" height="'+ih+'" fill="transparent"/></svg>';
      html+='<div class="ex-panel" data-panel="'+p+'"><h5>'+esc(EX_PANELS[p])+'</h5>'+s+'</div>';
    });
    box.innerHTML=html;
    // crosshair: the pointer picks a date, the tooltip lists every visible line at it
    box.querySelectorAll(".ex-panel").forEach(function(pn){
      var svg=pn.querySelector("svg"), hit=pn.querySelector(".hit");
      hit.onmousemove=function(ev){
        var r=svg.getBoundingClientRect(), x=(ev.clientX-r.left)*(W/r.width);
        var i=Math.max(0, Math.min(b.length-1, Math.round((x-L)/(iw||1)*(b.length-1))));
        box.querySelectorAll(".xh").forEach(function(xh){ xh.setAttribute("x1",xAt(i)); xh.setAttribute("x2",xAt(i)); xh.style.display=""; });
        exShowTip(ev, (d.granularity==="day"?"":"Week of ")+shortDate(b[i]), lines.map(function(l){ return {color:l.color, label:l.label, value:exFmtV(l.values[i], l.unit)}; }));
      };
      hit.onmouseleave=function(){ exHideTip(); box.querySelectorAll(".xh").forEach(function(xh){ xh.style.display="none"; }); };
    });
  }

  // ── the key: every term, in one place ──
  function exKey(){
    var dl=function(rows){ return rows.map(function(r){ return r[0]==="#"?'<h6>'+esc(r[1])+'</h6>':'<dt>'+esc(r[0])+'</dt><dd>'+esc(r[1])+'</dd>'; }).join(""); };
    return '<details class="ex-key"><summary>Key: what every term means</summary><dl>'+dl([
      ["#","Where the numbers come from"],
      ["Recorded","Every worker-day entered on an actual, whatever its approval state, except rejected actuals and rejected requests."],
      ["Confirmed / Earned","Recorded pay on actuals that finished approval (state CONFIRMED). Earned KES is confirmed pay."],
      ["Paid out","Confirmed pay carried by a payment run whose state is Paid."],
      ["Planned","A master plan's activity values, spread evenly over the plan's days."],
      ["Requested","Requests raised (not rejected), each spread evenly over the days it covers."],
      ["#","Measures"],
      ["Done","Output recorded ÷ quantity requested, in the activity's own unit."],
      ["Output vs target","Output per person-day ÷ the request's daily target. 100% = exactly on target. Taken day by day, so activities in different units can be compared."],
      ["Cost/unit vs rate","Pay ÷ output valued at the rate, over paid days. 100% = paid exactly the rate; above it, the work cost more per unit than the rate says."],
      ["By salaried staff","Output on days with no piece-rate pay. Real work at no task cost, which is why work done can run ahead of money."],
      ["Delivered (staff)","Confirmed pay on the requests a person raised ÷ what those requests asked for."],
      ["Approves in","The middle (median) time between a request being submitted and this person approving it."],
      ["KES / ha","Labour KES on a "+esc(TX("unit_singular","Block")).toLowerCase()+" ÷ its recorded area. Blank where no area is recorded."],
      ["#","Flags and colours"],
      ["⚠ no scan","Days paid with no check-in scan for that worker that day. Only counted from the first day this site has scans."],
      ["⇄ two farms","Days the worker was recorded on two farms at once."],
      ["Green / amber / red figures","Output vs target: green 95%+, red under 80%. Cost/unit vs rate: green to 105%, amber to 115%, red above. Done and Delivered: green 90%+, red under 50%."],
      ["Heatmap","Activities: blue above target, red below, grey on target. Workers, staff and "+esc(TX("unit_plural","Blocks")).toLowerCase()+": darker = more."],
      ["#","The chart"],
      ["Measures / Compare","Measures: one subject, any lines. Compare: up to six plans, activities, workers or "+esc(TX("unit_plural","Blocks")).toLowerCase()+", one measure each."],
      ["Picking a plan and an activity","Charts that activity within that plan."],
      ["Running total","KES lines add up from the start of the range, so the gap between Planned and Confirmed reads as how far behind."],
      ["Days or weeks","Daily up to six weeks of range, Monday-started weeks beyond."]
    ])+'</dl></details>';
  }

  function skeleton(){
    return '<div class="kpis">'+
      Array(6).join(0).split("0").map(function(){return '<div class="kpi"><div class="sk sk-kpi"></div></div>';}).join("")+
      '</div>';
  }

  function render(D){
    el("wm-body").innerHTML=
      // ===== how much of each plan actually happened =====
      '<div class="sech">Master plans &mdash; progress &amp; money</div>'+
      '<div class="card"><div class="hd"><h3>How each master plan is going</h3>'+
        '<div class="cap">work done against time gone by &middot; money planned, earned and paid &middot; open a plan for everything under it</div></div>'+
        '<div class="bd" id="wm-plancomp"><div class="loading">Measuring completion&hellip;</div></div></div>'+
      // ===== activities, people & blocks, in depth =====
      '<div class="sech">Activities, people &amp; '+esc(TX("unit_plural","Blocks")).toLowerCase()+'</div>'+
      '<div class="card"><div class="hd"><h3>What the work costs, who did it and where</h3>'+
        '<div class="cap">pick a lens &middot; open any row for everything behind it &middot; the chart follows what you open</div></div>'+
        '<div class="bd" id="wm-ex"><div class="loading">Reading the work&hellip;</div></div></div>'+
      // ===== trends & analytics tabs =====
      '<div class="sech">Trends &amp; analytics</div>'+
      '<div class="card"><div class="hd"><h3>What the numbers are doing</h3><div class="cap">confirmed work, with what is still in approval shown paler &middot; last 12 weeks unless dates are set</div></div>'+
        '<div class="bd">'+
          '<div class="pex-filters" id="an-filters">'+
            '<select id="an-farm"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select>'+
            '<label>From <input type="date" id="an-from" /></label>'+
            '<label>To <input type="date" id="an-to" /></label>'+
            '<button id="an-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="wm-stage-strip"></div>'+
          '<div id="wm-an-tabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px"></div><div id="wm-an-body" style="min-height:180px;color:var(--mute)">Loading charts…</div></div></div>'+
      // ===== pipeline + per-farm comparison (one card, pill tabs) =====
      '<div class="sech">Pipeline Explorer &mdash; drill into planning, assigning, actuals &amp; payment</div>'+
      '<div class="card"><div class="hd"><h3>All records</h3><div class="cap">click any row for full detail &middot; filter and browse each stage</div></div>'+
        '<div class="bd">'+
          '<div class="pex-tabs" id="pex-tabs">'+
            '<button data-ps="plans" class="on">Plans</button>'+
            '<button data-ps="assignments">Assignments</button>'+
            '<button data-ps="actuals">Actuals</button>'+
            '<button data-ps="payments">Payments</button>'+
          '</div>'+
          '<div class="pex-filters" id="pex-filters">'+
            '<input id="pex-q" placeholder="Search name / task / '+esc(TX("unit_singular","Block")).toLowerCase()+'…" />'+
            '<select id="pex-farm"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select>'+
            '<select id="pex-state"><option value="">All states</option></select>'+
            '<select id="pex-life"><option value="">All status</option><option value="planned">Planned</option><option value="assigned">Assigned</option><option value="done">Done</option><option value="paid">Paid</option><option value="closed">Closed</option></select>'+
            '<input id="pex-task" placeholder="Task" />'+
            '<input id="pex-block" placeholder="'+esc(TX("unit_singular","Block"))+'" />'+
            '<label>From <input type="date" id="pex-from" /></label>'+
            '<label>To <input type="date" id="pex-to" /></label>'+
            '<button id="pex-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="pex-list" style="max-height:420px;overflow:auto;border-top:1px solid #eee">Loading&hellip;</div>'+
        '</div></div>'+
      '<div id="pex-modal" class="pex-modal"><div class="pex-back"></div><div class="pex-sheet"><button class="pex-x">×</button><div id="pex-modal-body">…</div></div></div>'+
      // ===== COST BREAKDOWN: estimated vs paid, per activity / worker / farm =====
      // ===== COST CENTRE (BLOCK): which block consumes the most money =====
      '<div class="sech">Cost centres &mdash; spend by '+esc(TX("unit_singular","Block")).toLowerCase()+' or '+esc(TX("section_singular","Section")).toLowerCase()+'</div>'+
      '<div class="card"><div class="hd"><h3>Cost centres</h3><div class="cap">running labour cost per '+esc(TX("unit_singular","Block")).toLowerCase()+' beside GL cost-centre actuals, or totalled by '+esc(TX("section_singular","Section")).toLowerCase()+' &middot; boxes sized by spend &middot; click a row for its full breakdown</div></div>'+
        '<div class="bd">'+
          '<div class="pex-filters" id="cc-filters">'+
            '<input id="cc-q" placeholder="Search…" />'+
            '<select id="cc-farm"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select>'+
            '<label>From <input type="date" id="cc-from" /></label>'+
            '<label>To <input type="date" id="cc-to" /></label>'+
            '<select id="cc-group"><option value="block">Group: by '+esc(TX("unit_singular","Block")).toLowerCase()+'</option><option value="section">Group: by '+esc(TX("section_singular","Section")).toLowerCase()+'</option></select>'+
            '<select id="cc-color"><option value="spend">Colour: by spend</option><option value="cpu">Colour: cost per unit</option><option value="farm">Colour: by '+esc(TX("top_singular","Farm")).toLowerCase()+'</option></select>'+
            '<button id="cc-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="cc-totals" class="cb-totals"></div>'+
          '<div id="cc-treemap" style="margin:4px 0 14px"></div>'+
          '<div id="cc-tabs" class="pex-tabs" style="margin-bottom:6px">'+
            '<button data-ccview="block" class="on">By '+esc(TX("unit_singular","Block")).toLowerCase()+'</button>'+
            '<button data-ccview="farm">By '+esc(TX("top_singular","Farm")).toLowerCase()+'</button>'+
          '</div>'+
          '<div id="cc-list" style="max-height:520px;overflow:auto;border-top:1px solid #eee">Loading&hellip;</div>'+
        '</div></div>'+
      '<div class="sech">Crew movements &mdash; who left, who joined, who swapped</div>'+
      '<div class="card"><div class="hd"><h3>Substitution history</h3><div class="cap">every mid-period movement &middot; a leaver keeps pay for days worked; Days/Qty/Pay are what that row&rsquo;s worker did on the plan</div></div><div class="bd"><div class="pex-filters" id="subs-filters"><select id="subs-farm"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select></div><div id="wm-subs" style="max-height:360px;overflow:auto">Loading&hellip;</div></div></div>'+
      '<div class="sech">Delivery timeline &mdash; planned vs staffed vs delivered &middot; field intelligence</div>'+
      '<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:stretch">'+
      '<div class="card" style="flex:3;min-width:480px;margin-bottom:0"><div class="hd"><h3>Plans, assignments &amp; actuals over time</h3><div class="cap">daily &middot; planned share of approved plans, the staffed share, and confirmed output</div></div>'+
        '<div class="bd">'+
          '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px">'+
            '<div><div class="tl-lab">'+esc(TX("top_singular","Farm"))+'</div><select id="wm-tl-farm" class="tl-in"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select></div>'+
            '<div><div class="tl-lab">From</div><input type="date" id="wm-tl-from" class="tl-in"></div>'+
            '<div><div class="tl-lab">To</div><input type="date" id="wm-tl-to" class="tl-in"></div>'+
            '<button type="button" class="refresh" id="wm-tl-apply" style="margin-bottom:1px">Apply</button>'+
            '<span style="flex:1"></span>'+
            '<div id="wm-tl-measure" style="display:inline-flex;gap:2px;background:var(--wash);border:1px solid var(--line);border-radius:999px;padding:3px">'+
              '<button type="button" data-m="qty" class="on">Quantity</button>'+
              '<button type="button" data-m="val">KES</button>'+
            '</div>'+
          '</div>'+
          '<div id="wm-tl-chart" style="min-height:240px"><div class="empty">Loading timeline&hellip;</div></div>'+
        '</div></div>'+
      '<div class="card" style="flex:2;min-width:380px;margin-bottom:0"><div class="hd"><h3>Field intelligence</h3><div class="cap">efficiency per '+esc(TX("top_singular","Farm")).toLowerCase()+' &middot; who is free to work, any day</div></div>'+
        '<div class="bd">'+
          '<div class="subtabs" id="wm-fi-tabs" style="margin-bottom:10px">'+
            '<button type="button" class="subtab on" data-fi="eff">Efficiency</button>'+
            '<button type="button" class="subtab" data-fi="avail">Available workers</button>'+
          '</div>'+
          '<div id="wm-fi-eff">'+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px">'+
              '<div><div class="tl-lab">From</div><input type="date" id="wm-fi-from" class="tl-in"></div>'+
              '<div><div class="tl-lab">To</div><input type="date" id="wm-fi-to" class="tl-in"></div>'+
              '<button type="button" class="refresh" id="wm-fi-apply" style="margin-bottom:1px">Apply</button>'+
            '</div>'+
            '<div id="wm-fi-eff-body"><div class="empty">Loading&hellip;</div></div>'+
          '</div>'+
          '<div id="wm-fi-avail" style="display:none">'+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px">'+
              '<div><div class="tl-lab">Date</div><input type="date" id="wm-fi-date" class="tl-in"></div>'+
              '<div><div class="tl-lab">'+esc(TX("top_singular","Farm"))+'</div><select id="wm-fi-farm" class="tl-in"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select></div>'+
              '<button type="button" class="refresh" id="wm-fi-avapply" style="margin-bottom:1px">Apply</button>'+
              '<input type="text" id="wm-fi-search" class="tl-in" placeholder="Search name…" style="flex:1;min-width:120px">'+
            '</div>'+
            '<div id="wm-fi-avail-body"><div class="empty">Loading&hellip;</div></div>'+
          '</div>'+
        '</div></div>'+
      '</div>'+
      '<div class="sech">Action queues</div>'+
      '<div class="card"><div class="hd"><h3>Everything waiting on someone</h3><div class="cap">one queue at a time &middot; full-width</div></div>'+
        '<div class="bd">'+
          '<div class="subtabs" id="wm-q-tabs"></div>'+
          '<div id="wm-q-body" style="max-height:420px;overflow:auto;margin-top:10px"></div>'+
        '</div></div>';
    planCompletion();
    exInit();
    initCharts();
    initQueues(D);
    initTimeline();
    initFieldIntel();
  }

  // ============ APPROVAL SPEED (step by step) ============
  function speedWord(avg){
    if(avg==null) return "—";
    if(avg<0.5) return "Same day";
    if(avg<1.75) return "About 1 day";
    if(avg<7) return "About "+fmt(avg,1)+" days";
    return "Over a week ("+fmt(avg,0)+" days)";
  }
  function rankWord(i,total){
    if(i===1) return "Fastest";
    if(i===total&&total>1) return "Slowest";
    if(i===2) return "2nd fastest";
    if(i===3) return "3rd fastest";
    return i+"th";
  }
  function speedBar(avg,maxAvg,color){
    if(avg==null||maxAvg<=0) return "";
    var w=Math.max(4,Math.round(avg/maxAvg*100));
    return '<div style="background:var(--faint);height:8px;width:100%;min-width:100px"><div style="background:'+color+';height:8px;width:'+w+'%"></div></div>';
  }
  function apprEff(rows, names){
    rows=(rows||[]).filter(function(r){ return (r.n>0)||(r.pending_n>0); }); names=names||{};
    if(!rows.length) return '<div style="padding:18px;text-align:center;color:var(--mute)">No approval timing data yet — steps appear here as documents get signed off.</div>';
    var has=function(r){ return r.n>0 && r.avg_days!=null; };
    rows.sort(function(a,b){
      var av=has(a)?a.avg_days:1e9, bv=has(b)?b.avg_days:1e9;
      if(av!==bv) return av-bv;
      return (b.n||0)-(a.n||0);
    });
    var maxAvg=0, dataN=0;
    rows.forEach(function(r){ if(has(r)){ dataN++; if(r.avg_days>maxAvg) maxAvg=r.avg_days; } });
    var h='<table><thead><tr><th>Rank</th><th>Step</th><th>Who signs off</th><th>How fast (typical)</th><th style="min-width:120px"></th><th class="n">Signed within a day</th><th class="n">Signed off</th><th class="n">Waiting now</th></tr></thead><tbody>';
    var shown=0;
    rows.forEach(function(r){
      var ok=has(r);
      var rank="—", color="#9ca3af";
      if(ok){ shown++; rank=rankWord(shown,dataN);
        if(shown===1) color="#0a7a43";
        else if(shown===dataN&&dataN>1&&r.avg_days>=2) color="#b45309";
      }
      var ppl=(r.people||[]).slice().sort(function(a,b){ return (b.n||0)-(a.n||0); });
      var pnames=ppl.slice(0,3).map(function(p){ return esc(names[p.user]||p.user); });
      var whoTxt = pnames.length ? pnames.join(", ")+(ppl.length>3?" +"+(ppl.length-3)+" more":"") : esc(r.step);
      var waitTxt="—", wstyle="";
      if(r.pending_n){
        waitTxt="<b>"+fmt(r.pending_n)+"</b> item"+(r.pending_n>1?"s":"");
        if(r.pending_avg_wait!=null){
          waitTxt+=" · "+(r.pending_avg_wait<0.5?"arrived today":("waiting about "+fmt(r.pending_avg_wait,0)+" day"+(r.pending_avg_wait>=1.5?"s":"")));
          if(ok && r.pending_avg_wait>Math.max(r.avg_days,1)) wstyle=' style="color:#b45309;font-weight:600"';
        }
      }
      h+='<tr>'+
        '<td class="m"><b>'+rank+'</b></td>'+
        '<td style="white-space:normal"><b>'+esc(r.group)+'</b><br><span style="color:var(--mute);font-size:10.5px">'+esc(r.step)+' sign-off</span></td>'+
        '<td style="white-space:normal">'+whoTxt+'</td>'+
        '<td class="m">'+(ok?speedWord(r.avg_days):"—")+'</td>'+
        '<td>'+(ok?speedBar(r.avg_days,maxAvg,color):"")+'</td>'+
        '<td class="n m">'+(r.eff_pct!=null?Math.round(r.eff_pct)+"%":"—")+'</td>'+
        '<td class="n m">'+fmt(r.n)+'</td>'+
        '<td'+wstyle+'>'+waitTxt+'</td></tr>';
    });
    h+='</tbody></table>';
    h+='<div style="font-size:10.5px;color:var(--mute);margin-top:8px;line-height:1.5">Each row is one sign-off step, fastest at the top. <b>Waiting now</b> shows what is sitting at that step today — it turns amber when items have waited longer than that step normally takes.</div>';
    return h;
  }

  // ============ TRENDS & ANALYTICS ============
  function wireApprPeople(pp){
    if(!pp) return;
    pp.querySelectorAll("[data-gf]").forEach(function(b){
      b.onclick=function(ev){ ev.stopPropagation(); AN.apprFilter=b.getAttribute("data-gf");
        pp.innerHTML=anApprovers(AN.data.approvers||[], AN.data.apr_names||{}, AN.data.apr_window||null);
        wireApprPeople(pp); };
    });
  }
  var AN = { data:null, tab:"out", apprFilter:"" };
  function initCharts(){
    var tabs=[["out","Actuals vs target"],["pay","Pay vs plan"],["wrk","Workers by week"],["task","Top tasks"]];
    var host=el("wm-an-tabs"); if(!host) return;
    host.innerHTML="";
    tabs.forEach(function(t){
      var b=document.createElement("button");
      b.textContent=t[1]; b.setAttribute("data-an",t[0]);
      b.style.cssText="font-family:inherit;font-size:11px;font-weight:600;letter-spacing:.02em;border:1px solid var(--line);background:rgba(255,255,255,.7);color:var(--mute);padding:7px 15px;cursor:pointer;border-radius:999px;transition:all .15s";
      b.onclick=function(){ AN.tab=t[0]; paintAnTabs(); drawAnalytic(); };
      host.appendChild(b);
    });
    paintAnTabs();
    AN.data=null;
    ["an-farm","an-from","an-to"].forEach(function(id){
      var e=el(id); if(e && !e.dataset.wired){ e.dataset.wired="1"; e.onchange=function(){ loadCharts(); }; }
    });
    var anc=el("an-clear");
    if(anc && !anc.dataset.wired){
      anc.dataset.wired="1";
      anc.onclick=function(){ ["an-from","an-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; });
        var f=el("an-farm"); if(f) f.value=""; loadCharts(); };
    }
    loadCharts();
  }
  function loadCharts(){
    var a={action:"charts", farm:(el("an-farm")||{}).value||"",
      from_date:(el("an-from")||{}).value||"", to_date:(el("an-to")||{}).value||""};
    call(a).then(function(d){
      // the farm picker fills from the response's farm list, or the dashboard's
      // own once it has one; it used to wait for a list this endpoint never sent
      var fsel=el("an-farm");
      var flist=(d.farms&&d.farms.length&&typeof d.farms[0]==="string")?d.farms:FARM_LIST;
      if(fsel && fsel.options.length<=1 && flist && flist.length){
        flist.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
      }
      if(d.error){ var bd=el("wm-an-body"); if(bd) bd.innerHTML='<div style="padding:16px;text-align:center">Could not load charts: '+esc(d.error)+'</div>';
        var pp0=el("wm-appr-people"); if(pp0) pp0.innerHTML='<div style="color:var(--mute)">Ranking unavailable.</div>'; return; }
      AN.data=d; drawAnalytic();
      var pp=el("wm-appr-people");
      if(pp){ pp.innerHTML=anApprovers(d.approvers||[], d.apr_names||{}, d.apr_window||null); wireApprPeople(pp); }
    }).catch(function(e){
      var bd=el("wm-an-body"); if(bd) bd.innerHTML='<div style="padding:16px;text-align:center">Could not load charts.</div>';
      var pp1=el("wm-appr-people"); if(pp1) pp1.innerHTML='<div style="color:var(--mute)">Ranking unavailable.</div>';
    });
  }
  function paintAnTabs(){
    var host=el("wm-an-tabs"); if(!host) return;
    host.querySelectorAll("button").forEach(function(b){
      var on=b.getAttribute("data-an")===AN.tab;
      b.style.background=on?"var(--ink)":"#fff";
      b.style.color=on?"#fff":"var(--mute)";
      b.style.borderColor=on?"var(--ink)":"var(--line)";
    });
  }
  function wkLabel(d){
    if(!d) return "";
    var x=new Date(d+"T00:00:00"); if(isNaN(x)) return String(d);
    return x.getDate()+"/"+(x.getMonth()+1);
  }
  // Weekly bars, in the card's own style, with what makes a bar mean something:
  //   solid  - the confirmed figure
  //   pale   - recorded but still in approval, stacked on top (sign-off lags the
  //            field, so confirmed alone makes the latest weeks look like a stop)
  //   tick   - the week's target or plan, so a bar is read against something
  //   avg    - a dashed line at the range average, where there is no target
  // The week containing today is drawn paler and labelled "in progress".
  function anBarsV(rows, o){
    var none='<div style="padding:24px;text-align:center;color:var(--mute)">Nothing recorded in this period yet.</div>';
    if(!rows||!rows.length) return none;
    var sv=function(r){ return Number(r[o.solid])||0; };
    var pv=function(r){ return o.pale?(Number(r[o.pale])||0):0; };
    var tv=function(r){ return o.tick?(Number(r[o.tick])||0):0; };
    var max=0; rows.forEach(function(r){ max=Math.max(max, sv(r)+pv(r), tv(r)); });
    if(max<=0) return none;
    var n=rows.length, W=1200, H=380, L=84, R=22, T=34, B=58, iw=W-L-R, ih=H-T-B;
    var ymax=max*1.12, slot=iw/n, bw=Math.min(72,slot*0.55);
    function X(i){ return L+slot*(i+0.5); }
    function Y(v){ return T+ih-(v/ymax)*ih; }
    var g='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block">';
    for(var gi=0;gi<=5;gi++){ var gv=ymax*gi/5, gy=Y(gv);
      g+='<line x1="'+L+'" y1="'+gy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+gy.toFixed(1)+'" stroke="rgba(10,10,10,.06)"/>'+
         '<text x="'+(L-10)+'" y="'+(gy+4).toFixed(1)+'" text-anchor="end" font-size="11" fill="#5a5a52" font-family="Poppins,sans-serif">'+o.fmt(gv)+'</text>'; }
    g+='<line x1="'+L+'" y1="'+T+'" x2="'+L+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<line x1="'+L+'" y1="'+(T+ih)+'" x2="'+(W-R)+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<text transform="rotate(-90)" x="'+(-(T+ih/2))+'" y="20" text-anchor="middle" font-size="11.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">'+esc(o.yTitle||"")+'</text>';
    if(o.avg){
      var full=rows.filter(function(r){ return !anPartial(r.wstart); });
      var av=full.length?full.reduce(function(t,r){ return t+sv(r); },0)/full.length:0;
      if(av>0){ var ay=Y(av).toFixed(1);
        g+='<line x1="'+L+'" y1="'+ay+'" x2="'+(W-R)+'" y2="'+ay+'" stroke="#1a1a18" stroke-width="1.2" stroke-dasharray="5 4" opacity=".55"/>'+
           '<text x="'+(W-R-4)+'" y="'+(Y(av)-6).toFixed(1)+'" text-anchor="end" font-size="10.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">average '+o.fmt(av)+'</text>'; }
    }
    rows.forEach(function(r,i){
      var s0=sv(r), p0=pv(r), t0=tv(r), cur=anPartial(r.wstart);
      var ys=Y(s0), yp=Y(s0+p0), x0=(X(i)-bw/2).toFixed(1);
      var tipTxt="week of "+r.wstart+(cur?" ("+cur+")":"")+" · "+(o.solidLabel||"")+" "+o.fmt(s0)+
        (p0?" · awaiting approval "+o.fmt(p0):"")+(t0?" · "+(o.tickLabel||"target")+" "+o.fmt(t0):"");
      g+='<g><title>'+esc(tipTxt)+'</title>';
      if(p0>0) g+='<rect x="'+x0+'" y="'+yp.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(1,ys-yp).toFixed(1)+'" rx="5" fill="'+o.color+'" opacity=".32"/>';
      g+='<rect x="'+x0+'" y="'+ys.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(2,T+ih-ys).toFixed(1)+'" rx="5" fill="'+o.color+'"'+(cur?' opacity=".45"':'')+'/>';
      if(t0>0){ var ty=Y(t0).toFixed(1);
        g+='<line x1="'+(X(i)-bw/2-6).toFixed(1)+'" y1="'+ty+'" x2="'+(X(i)+bw/2+6).toFixed(1)+'" y2="'+ty+'" stroke="#1a1a18" stroke-width="2.4" stroke-linecap="round"/>'; }
      g+='</g>';
      var top=Math.min(yp, t0>0?Y(t0):yp);
      var lab=o.label?o.label(r):(s0+p0>0?o.fmt(s0+p0):"");
      if(lab) g+='<text x="'+X(i).toFixed(1)+'" y="'+(top-8).toFixed(1)+'" text-anchor="middle" font-size="10.5" font-weight="700" fill="#1a1a18" font-family="Poppins,sans-serif">'+esc(lab)+'</text>';
      g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+18)+'" text-anchor="middle" font-size="10.5" fill="#5a5a52" font-family="Poppins,sans-serif">'+wkLabel(r.wstart)+'</text>';
      if(cur) g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+32)+'" text-anchor="middle" font-size="9.5" font-style="italic" fill="#8a8780" font-family="Poppins,sans-serif">'+cur+'</text>';
    });
    g+='<text x="'+(L+iw/2)+'" y="'+(H-6)+'" text-anchor="middle" font-size="11.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">Week starting</text>';
    g+='</svg>';
    // a legend for every mark the chart uses, so nothing rests on colour alone
    var leg='<div class="an-leg"><span><i style="background:'+o.color+'"></i>'+esc(o.solidLabel||"")+'</span>'+
      (o.pale?'<span><i style="background:'+o.color+';opacity:.32"></i>awaiting approval</span>':'')+
      (o.tick?'<span><i class="tk"></i>'+esc(o.tickLabel||"target")+'</span>':'')+
      (o.avg?'<span><i class="av"></i>average of full weeks</span>':'')+
      '<span><i style="background:'+o.color+';opacity:.45"></i>part week (in progress, or cut by the dates)</span></div>';
    return leg+g+'<div style="font-size:10.5px;color:var(--mute);margin-top:8px">'+o.cap+' Hover any bar for its exact values.</div>';
  }
  function anMonday(iso){
    if(!iso) return "";
    var d=new Date(String(iso).slice(0,10)+"T00:00:00"); if(isNaN(d)) return "";
    d.setDate(d.getDate()-((d.getDay()+6)%7)); return localISO(d);
  }
  // One plain sentence above each chart: the last full week, how it compares,
  // the best week and the total. Numbers without a comparison say nothing.
  // A week the chart cannot show whole: the one containing today, or one the
  // chosen dates cut into at either end. Returns its label, or "" for a full week.
  function anPartial(wstart){
    var d=AN.data||{}, rg=d.range||{};
    var mon=new Date(wstart+"T00:00:00"), sun=new Date(mon); sun.setDate(sun.getDate()+6);
    var end=localISO(sun), today=String(d.today||"").slice(0,10);
    if(today && wstart<=today && today<=end) return "in progress";
    if(rg.to && rg.to<end) return "part week";
    if(rg.from && rg.from>wstart) return "part week";
    return "";
  }
  function anSummary(rows, val, fmtv, noun, ref, refLabel, average){
    var full=(rows||[]).filter(function(r){ return !anPartial(r.wstart); });
    if(!full.length) return "";
    var last=full[full.length-1], lv=val(last);
    var prev=full.slice(Math.max(0,full.length-5), full.length-1);
    var pavg=prev.length?prev.reduce(function(t,r){ return t+val(r); },0)/prev.length:0;
    var best=full.slice().sort(function(a,b){ return val(b)-val(a); })[0];
    var tot=full.reduce(function(t,r){ return t+val(r); },0);
    var parts=['Last full week (from '+esc(wkLabel(last.wstart))+'): <b>'+fmtv(lv)+'</b> '+noun];
    if(ref){ var rv=ref(last); if(rv>0) parts[0]+=' — <b class="'+(lv>=rv*0.95?'an-up':'an-down')+'">'+fmt(lv/rv*100,0)+'% of '+refLabel+'</b>'; }
    if(pavg>0){ var ch=(lv-pavg)/pavg*100;
      parts.push('<b class="'+(ch>=0?'an-up':'an-down')+'">'+(ch>=0?'▲ ':'▼ ')+fmt(Math.abs(ch),0)+'%</b> against the 4 weeks before'); }
    parts.push('best week '+esc(wkLabel(best.wstart))+' ('+fmtv(val(best))+')');
    // headcounts do not add up across weeks (the same person works many), so
    // the workers chart gives the typical week instead of a total
    parts.push(average ? ('typically '+fmtv(tot/full.length)+' a week') : (fmtv(tot)+' across '+full.length+' full week'+(full.length===1?'':'s')));
    return '<div class="an-sum">'+parts.join(' &middot; ')+'</div>';
  }
  // ── STAGE STRIP ─────────────────────────────────────────────────────────
  // Master Plan -> Planned Tasks -> Worker Assignment -> Actual Done -> Paid Work,
  // with the number waiting at each hand-off on the rail between two circles.
  //
  // The endpoint sends keys and counts; the words live here. Stage names are the
  // app's own vocabulary rather than the site's, so the taxonomy does not rename
  // them -- a farm may rename a block, but "Master Plan" is what this pipeline is.
  var STAGE_STEPS=[["master_plan","Master plans approved","#4f46e5","Approved master plans running in the dates."],
                   ["planned","Requests approved","#2563eb","Approved requests (work orders raised against a plan) in the dates."],
                   ["actual","Actuals confirmed","#0a7a43","Actuals (recorded work) that finished approval."],
                   ["paid","Payment runs paid","#7c3aed","Payment runs marked Paid. One run is one worker for one pay week, so this counts more than actuals do."]];
  var STAGE_GAPS=[["to_planned","requests awaiting approval"],
                  ["to_actual","actuals awaiting approval"],["to_paid","payment runs unpaid"]];
  function stageStrip(d){
    var st=(d && d.stages)||{}, wait=(d && d.stage_waiting)||{};
    var mo=(d && d.stage_money)||{}, wm=(d && d.stage_waiting_money)||{};
    var sub={master_plan:money(mo.master_plan)+" KES planned", planned:money(mo.planned)+" KES requested",
      actual:money(mo.actual)+" KES confirmed",
      paid:money(mo.paid)+" KES paid out"};
    var h='<div class="stagestrip" role="list">';
    STAGE_STEPS.forEach(function(sp,i){
      var n=Number(st[sp[0]])||0;
      h+='<div class="ss-node" role="listitem" title="'+esc(sp[3])+'">'+
           '<div class="ss-circle"'+(i===0?' data-first="1"':'')+' style="border-color:'+sp[2]+'">'+
             '<span style="color:'+sp[2]+'">'+fmt(n)+'</span></div>'+
           '<div class="ss-label">'+esc(sp[1])+'</div>'+
           (d && d.stage_money?'<div class="ss-sub">'+esc(sub[sp[0]])+'</div>':'')+
         '</div>';
      if(i<STAGE_GAPS.length){
        var gk=STAGE_GAPS[i][0], w=Number(wait[gk])||0, wk=wm[gk];
        var cap=fmt(w)+' '+STAGE_GAPS[i][1]+(wk?' · '+money(wk)+' KES':'');
        h+='<div class="ss-rail" title="'+esc(cap)+'">'+
             (w>0?'<span class="ss-dot" style="background:'+STAGE_STEPS[i+1][2]+'"><em>'+fmt(w)+'</em></span>'+
                  '<span class="ss-cap">'+esc(STAGE_GAPS[i][1])+(wk?'<br>'+esc(money(wk))+' KES':'')+'</span>':'')+
           '</div>';
      }
    });
    h+='</div>';
    if(mo.planned>0) h+='<div class="an-sum" style="margin-top:-6px">Of the money requested in these dates, <b>'+fmt(mo.actual/mo.planned*100,0)+
      '%</b> has been confirmed as done and <b>'+fmt(mo.paid/mo.planned*100,0)+'%</b> paid out.</div>';
    return h;
  }

  function anBarsH(rows, labelKey, color, valFn, subFn, capText){
    if(!rows||!rows.length) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var max=0, total=0;
    rows.forEach(function(r){ var v=Number(r.pay)||0; if(v>max) max=v; total+=v; });
    if(max<=0) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var n=rows.length;
    var W=1200,rowH=46,H=n*rowH+52,L=250,R=230,iw=W-L-R;
    function XV(v){ return L+(v/(max*1.06||1))*iw; }
    var g='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block">';
    for(var gi=1;gi<=4;gi++){ var gx=L+iw*gi/4;
      g+='<line x1="'+gx.toFixed(1)+'" y1="8" x2="'+gx.toFixed(1)+'" y2="'+(H-40)+'" stroke="rgba(10,10,10,.05)"/>'+
         '<text x="'+gx.toFixed(1)+'" y="'+(H-26)+'" text-anchor="middle" font-size="11" fill="#5a5a52" font-family="Poppins,sans-serif">'+kesShort(max*1.06*gi/4)+'</text>'; }
    g+='<line x1="'+L+'" y1="8" x2="'+L+'" y2="'+(H-40)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<line x1="'+L+'" y1="'+(H-40)+'" x2="'+(W-R)+'" y2="'+(H-40)+'" stroke="#8a8780" stroke-width="1.4"/>';
    rows.forEach(function(r,i){
      var v=Number(r.pay)||0;
      var pct=total>0?Math.round(v/total*100):0;
      var y0=12+i*rowH;
      var w=Math.max(2,XV(v)-L);
      var nm=String(r[labelKey]||"—"); if(nm.length>30) nm=nm.slice(0,29)+"…";
      g+='<text x="'+(L-10)+'" y="'+(y0+(r.std?13:17))+'" text-anchor="end" font-size="12" font-weight="600" fill="#1a1a18" font-family="Poppins,sans-serif">'+esc(nm)+'</text>';
      if(r.std) g+='<text x="'+(L-10)+'" y="'+(y0+27)+'" text-anchor="end" font-size="9.5" fill="#8a8780" font-family="Poppins,sans-serif">Std '+esc(r.std)+'</text>';
      g+='<rect x="'+L+'" y="'+(y0+4)+'" width="'+w.toFixed(1)+'" height="18" rx="9" fill="'+color+'"><title>'+esc(String(r[labelKey]||""))+' · '+esc(valFn(v,pct,r))+' · '+esc(subFn(r))+'</title></rect>';
      g+='<text x="'+(L+w+8).toFixed(1)+'" y="'+(y0+17)+'" font-size="11" font-weight="700" fill="#1a1a18" font-family="Poppins,sans-serif">'+esc(valFn(v,pct,r))+'</text>';
    });
    g+='<text x="'+(L+iw/2)+'" y="'+(H-6)+'" text-anchor="middle" font-size="11.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">Confirmed pay (KES)</text>';
    g+='</svg>';
    return g+'<div style="font-size:10.5px;color:var(--mute);margin-top:8px">'+capText+' Hover a bar for the full detail.</div>';
  }
  function anApprovers(rows, names, win){
    var GROUP_ORDER=["Work plans","Assignments","Work records","Payments"];
    rows=rows||[]; names=names||{};
    if(!rows.length) return '<div style="padding:24px;text-align:center;color:var(--mute)">No sign-offs recorded in this period yet.</div>';
    var avail={}; rows.forEach(function(r){ avail[r.group]=1; });
    var gf=AN.apprFilter||"";
    if(gf && !avail[gf]) gf="";
    var bar='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;align-items:center">'+
      '<span style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Rank within</span>';
    var opts=[["","Whole pipeline"]];
    GROUP_ORDER.forEach(function(g){ if(avail[g]) opts.push([g,g]); });
    opts.forEach(function(o){
      var on=(o[0]===gf);
      bar+='<button type="button" data-gf="'+esc(o[0])+'" style="font-family:inherit;font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;border:1px solid '+(on?"var(--ink)":"var(--line)")+';background:'+(on?"var(--ink)":"#fff")+';color:'+(on?"#fff":"var(--mute)")+';padding:5px 11px;cursor:pointer">'+esc(o[1])+'</button>';
    });
    bar+='</div>';
    var frows=gf?rows.filter(function(r){ return r.group===gf; }):rows;
    if(!frows.length) return bar+'<div style="padding:24px;text-align:center;color:var(--mute)">No sign-offs in this part of the pipeline yet.</div>';
    var per={};
    frows.forEach(function(r){
      var p=per[r.who];
      if(!p){ p={who:r.who,n:0,wsum:0,d0:0,slow:0,mx:0,groups:{}}; per[r.who]=p; }
      p.n+=r.n; p.wsum+=(r.avg_d||0)*r.n; p.d0+=r.d0; p.slow+=r.slow;
      if(r.mx!=null && r.mx>p.mx) p.mx=r.mx;
      p.groups[r.group]=1;
    });
    var list=[]; for(var k in per){ list.push(per[k]); }
    list.forEach(function(p){ p.avg=p.n?(p.wsum/p.n):null; p.eff=p.n?(p.d0/p.n*100):0; });
    list.sort(function(a,b){
      if(b.eff!==a.eff) return b.eff-a.eff;
      if((a.avg||0)!==(b.avg||0)) return (a.avg||0)-(b.avg||0);
      return b.n-a.n;
    });
    var h=bar+'<table><thead><tr><th class="n">#</th><th>Who</th><th>Approves in</th><th class="n">Sign-offs</th><th class="n">Efficiency</th><th style="min-width:110px"></th><th class="n">Avg days</th><th class="n">Slow (≥2d)</th></tr></thead><tbody>';
    list.forEach(function(p,idx){
      var effColor = p.eff>=95 ? "#0a7a43" : (p.eff>=80 ? "#6b7280" : "#b45309");
      var few = p.n<5 ? ' <span style="color:var(--mute);font-size:9.5px">(only '+fmt(p.n)+')</span>' : '';
      var slowTxt = p.slow>0 ? ('<span style="color:#b45309;font-weight:700">'+fmt(p.slow)+'</span> <span style="color:var(--mute);font-size:9.5px">worst '+fmt(p.mx)+'d</span>') : "—";
      var medal = idx===0 ? " 🥇" : (idx===1 ? " 🥈" : (idx===2 ? " 🥉" : ""));
      var chips=""; GROUP_ORDER.forEach(function(g){
        if(p.groups[g]) chips+='<span data-gf="'+esc(g)+'" title="rank within '+esc(g)+'" style="display:inline-block;font-size:9px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;border:1px solid var(--line);padding:2px 7px;margin:1px 3px 1px 0;cursor:pointer;color:var(--mute)">'+esc(g)+'</span>';
      });
      h+='<tr>'+
        '<td class="n m"><b>'+(idx+1)+medal+'</b></td>'+
        '<td><b>'+esc(names[p.who]||p.who)+'</b></td>'+
        '<td style="white-space:normal">'+chips+'</td>'+
        '<td class="n m">'+fmt(p.n)+few+'</td>'+
        '<td class="n m"><b>'+(Math.round(p.eff*10)/10)+'%</b></td>'+
        '<td><div style="background:var(--faint);height:10px;width:100%;min-width:90px"><div style="background:'+effColor+';height:10px;width:'+Math.max(2,Math.round(p.eff))+'%"></div></div></td>'+
        '<td class="n m">'+(p.avg!=null?p.avg.toFixed(2):"—")+'</td>'+
        '<td class="n m">'+slowTxt+'</td></tr>';
    });
    h+='</tbody></table>';
    h+='<div style="font-size:10.5px;color:var(--mute);margin-top:8px;line-height:1.5">Click a <b>chip</b> (or the Rank-within buttons) to re-rank inside one part of the pipeline. <b>Efficiency</b> = share signed off the same day it arrived. Window: '+esc((win&&win.from)||"")+' → '+esc((win&&win.to)||"")+'.</div>';
    return h;
  }
  function drawAnalytic(){
    var bd=el("wm-an-body"); if(!bd) return;
    var sb=el("wm-stage-strip");
    if(sb) sb.innerHTML=stageStrip(AN.data||{});
    if(!AN.data){ bd.innerHTML='<div style="padding:16px;color:var(--mute)">Loading charts…</div>'; return; }
    var wk=AN.data.weekly||[];
    var rg=AN.data.range||{};
    var rgNote=(rg.from&&rg.to)?'<div class="an-sum" style="color:var(--mute);margin-bottom:4px">Showing '+esc(shortDate(rg.from))+' – '+esc(shortDate(rg.to))+
      ((el("an-from")||{}).value||(el("an-to")||{}).value?'':' (the last 12 weeks; pick dates above to change it)')+'</div>':'';
    if(AN.tab==="out"){
      bd.innerHTML=anSummary(wk, function(r){ return (r.val_conf||0)+(r.val_pend||0); }, function(v){ return money(v)+" KES"; },
          "of work done", function(r){ return r.target||0; }, "target")+
        anBarsV(wk, {solid:"val_conf", pale:"val_pend", tick:"target", color:"#0a7a43", fmt:function(v){ return money(v); },
          solidLabel:"actual work, confirmed", tickLabel:"target (requested)", yTitle:"Work valued at its rate (KES)",
          label:function(r){ var a=(r.val_conf||0)+(r.val_pend||0); return r.target>0?fmt(a/r.target*100,0)+"%":(a?money(a):""); },
          cap:"Actual output against the target the week's requests set. Both are valued at the task's rate so different units add up; salaried staff's output counts too. The figure over each bar is actual ÷ target."});
    } else if(AN.tab==="pay"){
      bd.innerHTML=anSummary(wk, function(r){ return (r.pay||0)+(r.pay_pend||0); }, function(v){ return money(v)+" KES"; },
          "of pay recorded", function(r){ return r.planned||0; }, "plan")+
        anBarsV(wk, {solid:"pay", pale:"pay_pend", tick:"planned", color:"#7c3aed", fmt:function(v){ return money(v); },
          solidLabel:"pay, confirmed", tickLabel:"planned (master plans)", yTitle:"Pay (KES)",
          label:function(r){ var a=(r.pay||0)+(r.pay_pend||0); return r.planned>0?fmt(a/r.planned*100,0)+"%":(a?money(a):""); },
          cap:"What the work cost each week against what the master plans budgeted for it. The figure over each bar is pay ÷ plan (the KES alone where no plan covered the week). Pay is below plan where work was not done or was done by salaried staff."});
    } else if(AN.tab==="wrk"){
      bd.innerHTML=anSummary(wk, function(r){ return r.workers||0; }, function(v){ return fmt(v); }, "people", null, null, true)+
        anBarsV(wk, {solid:"workers", avg:true, color:"#2563eb", fmt:function(v){ return fmt(v); },
          solidLabel:"people with confirmed work", yTitle:"Workers (count)",
          cap:"How many different people did confirmed work each week."});
    } else if(AN.tab==="task"){
      // the endpoint sends the docname; taskName() is the one place that knows
      // the map, so resolve here rather than teaching the bar renderer about tasks
      var pw=AN.data.prev_window;
      // compare only with a period the records fully cover
      var pwPartial=pw && AN.data.data_from && pw.from < AN.data.data_from;
      if(pwPartial) pw=null;
      var anTT=(AN.data.top_tasks||[]).map(function(r){
        var o={}; for(var k in r){ o[k]=r[k]; } o.label=taskName(r.task); o.std=taskStdText(r.task); return o; });
      bd.innerHTML=anBarsH(anTT,"label","#0a7a43",
        function(v,pct,r){
          var t="KES "+money(v)+" · "+pct+"%";
          if(pw && r){ var pp=r.prev_pay||0;
            t+= pp>0 ? (" · "+(v>=pp?"▲ ":"▼ ")+fmt(Math.abs(v-pp)/pp*100,0)+"%") : " · new"; }
          return t; },
        function(r){ return fmt(r.workers)+" people"; },
        "Your 10 biggest tasks by confirmed pay, each with its share of the total"+(pw?" and its change against the "+wkLabel(pw.from)+"–"+wkLabel(pw.to)+" period of the same length (new = nothing confirmed then).":
          (pwPartial?". No change is shown: the period of the same length before these dates starts before the first recorded work ("+wkLabel(AN.data.data_from)+")."
                    :".")));
    }
    bd.innerHTML=rgNote+bd.innerHTML+anKey();
  }

  // every term in the card, in one place
  function anKey(){
    var dl=function(rows){ return rows.map(function(r){ return r[0]==="#"?'<h6>'+esc(r[1])+'</h6>':'<dt>'+esc(r[0])+'</dt><dd>'+esc(r[1])+'</dd>'; }).join(""); };
    return '<details class="ex-key"><summary>Key: what every number means</summary><dl>'+dl([
      ["#","The pipeline strip"],
      ["Master plans approved","Approved plans running in the dates, with the money their approved lines budget."],
      ["Requests approved","Approved requests in the dates and the money they ask for."],
      ["Actuals confirmed","Recorded work that finished approval, and its pay."],
      ["Payment runs paid","Payment runs marked Paid. One run is one worker for one pay week, so it counts more than actuals do."],
      ["Numbers on the rails","What is waiting at that hand-off: requests or actuals awaiting approval, and payment runs not yet paid."],
      ["#","The weekly charts"],
      ["Actual work (KES)","Output for the week valued at the task's rate (quantity × rate), so trees, hours and kilograms add up. Includes salaried staff's output."],
      ["Target","What the week's requests asked for, valued the same way and spread evenly over each request's days."],
      ["Planned","What the approved master plans budgeted, spread evenly over each plan's days."],
      ["Solid / pale","Solid is confirmed; the paler part on top is recorded but still in approval."],
      ["Part week","The week containing today, or a week the chosen dates cut into: drawn paler and left out of the comparisons, since it is not a whole week."],
      ["▲ / ▼ against the 4 weeks before","The last full week compared with the average of the four full weeks before it."],
      ["#","Top tasks"],
      ["Share","The task's part of all confirmed pay in the dates."],
      ["▲ / ▼","Change against the period of the same length just before; \"new\" when nothing was confirmed then."]
    ])+'</dl></details>';
  }

  function farmTable(rows){
    if(!rows.length) return '<div class="empty">No '+esc(TX("top_singular","Farm")).toLowerCase()+' data.</div>';
    var h='<table><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Appr</th><th class="n">Planned KES</th><th class="n">Assigned</th><th class="n">Confirmed Pay KES</th><th class="n">Unassigned</th></tr></thead><tbody>';
    var tc=0,td=0,tp=0,tu=0;
    rows.forEach(function(r){
      tc+=r.approved_cost; td+=r.assigned_workers; tp+=r.actual_payment; tu+=r.unassigned;
      var un=r.unassigned>0?'<span class="tag hot">'+fmt(r.unassigned)+'</span>':fmt(r.unassigned);
      h+='<tr><td><b>'+esc(r.farm)+'</b></td><td class="n m">'+fmt(r.approved_plans)+'</td><td class="n m">'+fmt(r.approved_cost)+'</td><td class="n m">'+fmt(r.assigned_workers)+'</td><td class="n m">'+fmt(r.actual_payment)+'</td><td class="n m">'+un+'</td></tr>';
    });
    h+='</tbody><tfoot><tr><td>All</td><td class="n"></td><td class="n">'+fmt(tc)+'</td><td class="n">'+fmt(td)+'</td><td class="n">'+fmt(tp)+'</td><td class="n">'+fmt(tu)+'</td></tr></tfoot></table>';
    return h;
  }

  function qCard(title, rows, cols){
    var h='<div class="card"><div class="hd"><h3>'+title+'</h3><div class="cap">'+rows.length+'</div></div><div class="bd">';
    if(!rows.length) return h+'<div class="empty">Empty.</div></div></div>';
    h+='<table><thead><tr><th>Ref</th>';
    cols.forEach(function(c){ h+='<th class="'+(c[2]?"n":"")+'">'+c[1]+'</th>'; });
    h+='</tr></thead><tbody>';
    rows.forEach(function(r){
      h+='<tr><td>'+esc(r.name)+'</td>';
      cols.forEach(function(c){
        var v=r[c[0]];
        if(c[0]==="block_section") v=lbl(v);
        if(c[0]==="total_cost") v=fmt(v);
        h+='<td class="'+(c[2]?"n m":"")+'">'+esc(v==null?"—":v)+'</td>';
      });
      h+='</tr>';
    });
    return h+'</tbody></table></div></div>';
  }

  function actCard(rows){
    var h='<div class="card"><div class="hd"><h3>Actuals in approval</h3><div class="cap">'+rows.length+' · HR / GM</div></div><div class="bd">';
    if(!rows.length) return h+'<div class="empty">Empty.</div></div></div>';
    h+='<table><thead><tr><th>Ref</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>Task</th><th>Stage</th><th class="n">Pay KES</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var st=r.workflow_state==="Pending GM"?'<span class="tag hot">GM</span>':'<span class="tag">HR</span>';
      h+='<tr><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td><td>'+st+'</td><td class="n m">'+fmt(r.total_payment)+'</td></tr>';
    });
    return h+'</tbody></table></div></div>';
  }

  function payCard(rows){
    var h='<div class="card"><div class="hd"><h3>Payment runs &rarr; accounts</h3><div class="cap">'+rows.length+'</div></div><div class="bd">';
    if(!rows.length) return h+'<div class="empty">Empty.</div></div></div>';
    h+='<table><thead><tr><th>Ref</th><th>Run</th><th class="n">Workers</th><th class="n">Total KES</th></tr></thead><tbody>';
    rows.forEach(function(r){
      h+='<tr><td>'+esc(r.name)+'</td><td>'+esc(r.run_title)+'</td><td class="n m">'+fmt(r.total_workers)+'</td><td class="n m">'+fmt(r.amount)+'</td></tr>';
    });
    return h+'</tbody></table></div></div>';
  }

  var COMBO={tab:"funnel"};
  function comboFlow(wk){
    if(!wk||!wk.length) return '<div class="empty">No approvals in this window yet.</div>';
    var SERIES=[["planned_v","Plans approved","#a06000"],["assigned_v","Assignments staffed","#2563eb"],["confirmed_v","Actuals confirmed","#0a7a43"]];
    var max=0;
    wk.forEach(function(w){ SERIES.forEach(function(sr){ var v=Number(w[sr[0]])||0; if(v>max) max=v; }); });
    if(max<=0) return '<div class="empty">No value has moved yet.</div>';
    var n=wk.length;
    var W=1200,H=400,L=84,R=22,T=30,B=58,iw=W-L-R,ih=H-T-B;
    var ymax=max*1.12;
    var slot=iw/n, gw=Math.min(28,slot*0.24);
    function X(i){ return L+slot*(i+0.5); }
    function Y(v){ return T+ih-(v/ymax)*ih; }
    var g='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block">';
    for(var gi=0;gi<=5;gi++){ var gv=ymax*gi/5, gy=Y(gv);
      g+='<line x1="'+L+'" y1="'+gy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+gy.toFixed(1)+'" stroke="rgba(10,10,10,.06)"/>'+
         '<text x="'+(L-10)+'" y="'+(gy+4).toFixed(1)+'" text-anchor="end" font-size="11" fill="#5a5a52" font-family="Poppins,sans-serif">'+kesShort(gv)+'</text>'; }
    g+='<line x1="'+L+'" y1="'+T+'" x2="'+L+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<line x1="'+L+'" y1="'+(T+ih)+'" x2="'+(W-R)+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<text transform="rotate(-90)" x="'+(-(T+ih/2))+'" y="20" text-anchor="middle" font-size="11.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">Value approved (KES)</text>';
    wk.forEach(function(w,i){
      SERIES.forEach(function(sr,si){
        var v=Number(w[sr[0]])||0;
        var x=X(i)+(si-1)*(gw+3)-gw/2;
        var y=Y(v);
        var nfield=sr[0].replace("_v","_n");
        g+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+gw.toFixed(1)+'" height="'+Math.max(1.5,T+ih-y).toFixed(1)+'" rx="4" fill="'+sr[2]+'"><title>week of '+esc(wkLabel(w.wstart))+'\n'+sr[1]+': KES '+kesShort(v)+' ('+fmt(w[nfield]||0)+' documents)</title></rect>';
        if(v>0&&v>ymax*0.045) g+='<text x="'+(x+gw/2).toFixed(1)+'" y="'+(y-6).toFixed(1)+'" text-anchor="middle" font-size="9" font-weight="700" fill="#1a1a18" font-family="Poppins,sans-serif">'+kesShort(v)+'</text>';
      });
      g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+18)+'" text-anchor="middle" font-size="10.5" fill="#5a5a52" font-family="Poppins,sans-serif">'+wkLabel(w.wstart)+'</text>';
    });
    g+='<text x="'+(L+iw/2)+'" y="'+(H-8)+'" text-anchor="middle" font-size="11.5" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">Week starting</text>';
    g+='</svg>';
    return '<div style="font-size:12px;color:var(--mute);margin:2px 0 8px">Value approved at each stage per week — plans should be matched by staffing, and staffing by confirmed work. A widening gap between bars is work leaking between stages.</div>'+g+
      '<div class="clegend" style="font-size:11px;margin-top:6px">'+
      SERIES.map(function(sr){ return '<span><i style="background:'+sr[2]+';width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:5px"></i>'+sr[1]+'</span>'; }).join("")+
      '</div>'+
      '<div style="font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute);font-weight:700;margin:18px 0 8px">Per plan — value through the stages, and who touched it</div>'+
      '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px">'+
        '<div><div class="tl-lab">'+esc(TX("top_singular","Farm"))+'</div><select id="wm-vf-farm" class="tl-in"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option></select></div>'+
        '<div><div class="tl-lab">Plan period from</div><input type="date" id="wm-vf-from" class="tl-in"></div>'+
        '<div><div class="tl-lab">to</div><input type="date" id="wm-vf-to" class="tl-in"></div>'+
        '<button type="button" class="refresh" id="wm-vf-apply" style="margin-bottom:1px">Apply</button>'+
        '<span class="cap" id="wm-vf-count" style="margin-left:auto"></span>'+
      '</div>'+
      '<div id="wm-vf-table" style="max-height:460px;overflow:auto"><div class="loading">Loading plans…</div></div>';
  }

  function vfShort(u){
    if(!u) return "—";
    return String(u).split(",").map(function(x){ return x.replace(/@.*$/,""); }).join(", ");
  }
  function initFlowPlans(){
    var ap=el("wm-vf-apply"); if(!ap) return;
    if(!el("wm-vf-from").value){
      var d=new Date(); d.setDate(d.getDate()-27);
      el("wm-vf-from").value=d.toISOString().slice(0,10);
    }
    if(!el("wm-vf-to").value) el("wm-vf-to").value=new Date().toISOString().slice(0,10);
    ap.onclick=loadFlowPlans;
    el("wm-vf-farm").onchange=loadFlowPlans;
    loadFlowPlans();
  }
  function loadFlowPlans(){
    var box=el("wm-vf-table"); if(!box) return;
    box.innerHTML='<div class="loading">Loading plans…</div>';
    call({action:"flow_plans", farm:el("wm-vf-farm").value||"",
          from_date:el("wm-vf-from").value||"", to_date:el("wm-vf-to").value||""})
      .then(function(d){
        if(d.error){ box.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
        var fs=el("wm-vf-farm");
        if(fs && fs.options.length<=1 && (d.farms||[]).length){
          (d.farms||[]).forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); });
          if(d.window&&d.window.farm) fs.value=d.window.farm;
        }
        renderFlowPlans(d.plans||[]);
      })
      .catch(function(e){ box.innerHTML='<div class="empty">Could not load plans: '+esc(e.message)+'</div>'; });
  }
  function renderFlowPlans(plans){
    var box=el("wm-vf-table"); if(!box) return;
    var cnt=el("wm-vf-count");
    if(cnt) cnt.textContent=fmt(plans.length)+" plan"+(plans.length===1?"":"s");
    if(!plans.length){ box.innerHTML='<div class="empty">No plans in this window.</div>'; return; }
    var max=0;
    plans.forEach(function(x){ ["planned_v","assigned_v","confirmed_v"].forEach(function(k){ if(x[k]>max) max=x[k]; }); });
    max=max||1;
    function hbar(v,color,label){
      var w=Math.max(v>0?1.5:0, v/max*100);
      return '<div style="display:flex;align-items:center;gap:6px;margin:1.5px 0">'+
        '<div style="flex:1;background:rgba(10,10,10,.05);height:9px;border-radius:999px;overflow:hidden">'+
          (v>0?'<div style="height:9px;width:'+w+'%;border-radius:999px;background:'+color+'" title="'+label+' KES '+kesShort(v)+'"></div>':'')+
        '</div>'+
        '<span class="m" style="width:56px;text-align:right;font-size:9.5px;color:var(--ink)">'+ (v>0?kesShort(v):"—") +'</span></div>';
    }
    var h='<table style="margin-top:0"><thead><tr>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">Plan</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">'+esc(TX("top_singular","Farm"))+' · Task</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">Period</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1;min-width:230px">Planned / Assigned / Confirmed</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">Created</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">Plan approved</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">Actuals entered</th>'+
      '<th style="position:sticky;top:0;background:#fff;z-index:1">HR · GM confirmed</th></tr></thead><tbody>';
    plans.forEach(function(x){
      var leak = x.planned_v>0 && x.confirmed_v<x.planned_v*0.5;
      h+='<tr>'+
        '<td class="m" style="font-size:10.5px">'+esc(x.plan)+'<div style="font-size:9px;color:var(--mute)">'+esc(x.state||"")+'</div></td>'+
        '<td style="white-space:normal;max-width:190px"><b>'+esc(x.farm||"—")+'</b> · '+esc(taskName(x.task)||"—")+taskStdSub(x.task)+'<div style="font-size:9.5px;color:var(--mute)">'+esc(lbl(x.block)||"")+' · '+fmt(x.qty)+' '+esc(x.uom||"")+' @ '+fmt(x.rate,2)+'</div></td>'+
        '<td class="m" style="font-size:10px;white-space:nowrap">'+esc(x.from_date||"")+'<br>'+esc(x.to_date||"")+'</td>'+
        '<td>'+hbar(x.planned_v,"#a06000","planned")+hbar(x.assigned_v,"#2563eb","assigned")+hbar(x.confirmed_v,"#0a7a43","confirmed")+'</td>'+
        '<td style="font-size:10.5px">'+esc(vfShort(x.created_by))+'</td>'+
        '<td style="font-size:10.5px">'+esc(vfShort(x.plan_approved_by))+'</td>'+
        '<td style="font-size:10.5px">'+esc(vfShort(x.entered_by))+'</td>'+
        '<td style="font-size:10.5px">'+esc(vfShort(x.hr_by))+' · '+esc(vfShort(x.gm_by))+'</td>'+
        '</tr>';
    });
    h+='</tbody></table>';
    box.innerHTML=h;
  }

  function comboInit(D){
    COMBO.D=D;
    var bar=el("wm-combo-tabs");
    if(bar){
      bar.querySelectorAll("[data-ct]").forEach(function(b){
        b.onclick=function(){
          COMBO.tab=b.getAttribute("data-ct");
          bar.querySelectorAll("[data-ct]").forEach(function(x){ x.classList.toggle("on", x===b); });
          comboView();
        };
      });
    }
    comboView();
  }
  function comboBar(v,mx,color){
    var w=mx>0?Math.max(1,Math.round((v||0)/mx*100)):0;
    return '<div class="cb-bar" style="width:140px"><div class="cb-fill" style="width:'+w+'%;background:'+color+'"></div></div>';
  }
  function fdot(farm){ return '<i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+ccFarmColor(farm)+';margin-right:6px"></i>'; }
  function comboView(){
    var box=el("wm-combo"); if(!box) return;
    var D=COMBO.D||{}; var f=D.funnel||{}; var rows=D.farms||[];
    var h="";
    box.style.maxHeight = COMBO.tab==="flow" ? "none" : "420px";
    if(COMBO.tab==="flow"){
      if(AN.data&&AN.data.stage_weekly){ box.innerHTML=comboFlow(AN.data.stage_weekly); initFlowPlans(); }
      else{
        box.innerHTML='<div class="loading">Loading value flow…</div>';
        call({action:"charts"}).then(function(d){ AN.data=d; if(COMBO.tab==="flow"){ box.innerHTML=comboFlow(d.stage_weekly||[]); initFlowPlans(); } })
          .catch(function(){ box.innerHTML='<div class="empty">Could not load value flow.</div>'; });
      }
      return;
    }
    if(COMBO.tab==="funnel"){
      var stg=[["Approved plans",f.planned||0,"#0a0a0a","plans signed off and ready to staff"],
               ["Assigned",f.assigned||0,"#2563eb","plans with a crew on them"],
               ["Confirmed actuals",f.confirmed||0,"#0a7a43","work recorded and fully approved"],
               ["Payment runs",f.paid||0,"#7c3aed","runs paid out by accounts"]];
      var mx=0; stg.forEach(function(x){ if(x[1]>mx) mx=x[1]; });
      h='<table class="pex"><thead><tr><th>Stage</th><th class="n">Count</th><th class="n">Conversion</th><th></th><th>What it means</th></tr></thead><tbody>';
      stg.forEach(function(x,i){
        var conv=i===0?"":(stg[i-1][1]>0?Math.round(x[1]/stg[i-1][1]*100)+"%":"—");
        h+='<tr><td><b style="color:'+x[2]+'">'+x[0]+'</b></td><td class="n m" style="font-size:15px;font-weight:800">'+fmt(x[1])+'</td><td class="n m">'+conv+'</td><td>'+comboBar(x[1],mx,x[2])+'</td><td style="white-space:normal;color:var(--mute)">'+x[3]+'</td></tr>';
      });
      h+='</tbody></table>';
    } else if(COMBO.tab==="deploy"){
      var mx1=0; rows.forEach(function(r){ mx1=Math.max(mx1,r.planned_people||0,r.assigned_workers||0); });
      var tp=0,ta=0;
      h='<table class="pex"><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Planned slots/day</th><th></th><th class="n">Assigned (people)</th><th></th></tr></thead><tbody>';
      rows.forEach(function(r){
        tp+=r.planned_people||0; ta+=r.assigned_workers||0;
        h+='<tr><td>'+fdot(r.farm)+'<b>'+esc(r.farm)+'</b></td>'+
           '<td class="n m">'+fmt(r.planned_people)+'</td><td>'+comboBar(r.planned_people,mx1,"#94a3b8")+'</td>'+
           '<td class="n m" style="font-weight:700">'+fmt(r.assigned_workers)+'</td><td>'+comboBar(r.assigned_workers,mx1,"#2563eb")+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><td>Total</td><td class="n m">'+fmt(tp)+'</td><td></td><td class="n m">'+fmt(ta)+'</td><td></td></tr></tfoot></table>';
      h+='<div style="font-size:10.5px;color:var(--mute);margin-top:8px">Planned slots/day adds up every plan’s crew — it counts slots, not people, so it can exceed the workforce.</div>';
    } else if(COMBO.tab==="output"){
      var mx2=0; rows.forEach(function(r){ mx2=Math.max(mx2,r.planned_qty||0,r.actual_qty||0); });
      var tq=0,td2=0;
      h='<table class="pex"><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Target</th><th class="n">Done</th><th class="n">%</th><th>Progress</th></tr></thead><tbody>';
      rows.forEach(function(r){
        tq+=r.planned_qty||0; td2+=r.actual_qty||0;
        var pct=(r.planned_qty>0)?Math.round((r.actual_qty||0)/r.planned_qty*100):0;
        var col=pct>=100?"#0a7a43":(pct>=75?"#10b981":(pct>=40?"#2563eb":"#b45309"));
        h+='<tr><td>'+fdot(r.farm)+'<b>'+esc(r.farm)+'</b></td><td class="n m">'+fmt(r.planned_qty)+'</td><td class="n m" style="font-weight:700">'+fmt(r.actual_qty)+'</td><td class="n m" style="color:'+col+';font-weight:700">'+pct+'%</td><td>'+comboBar(r.actual_qty,mx2,col)+'</td></tr>';
      });
      var tpct=tq>0?Math.round(td2/tq*100):0;
      h+='</tbody><tfoot><tr><td>Total</td><td class="n m">'+fmt(tq)+'</td><td class="n m">'+fmt(td2)+'</td><td class="n m">'+tpct+'%</td><td></td></tr></tfoot></table>';
    } else {
      var mx3=0; rows.forEach(function(r){ mx3=Math.max(mx3,r.planned_value||0,r.actual_payment||0,r.paid_amount||0); });
      var tv=0,tc=0,tpd=0;
      h='<table class="pex"><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Planned</th><th></th><th class="n">Confirmed</th><th></th><th class="n">Paid</th><th></th></tr></thead><tbody>';
      rows.forEach(function(r){
        tv+=r.planned_value||0; tc+=r.actual_payment||0; tpd+=r.paid_amount||0;
        h+='<tr><td>'+fdot(r.farm)+'<b>'+esc(r.farm)+'</b></td>'+
           '<td class="n m">'+money(r.planned_value)+'</td><td>'+comboBar(r.planned_value,mx3,"#94a3b8")+'</td>'+
           '<td class="n m" style="color:#2563eb;font-weight:700">'+money(r.actual_payment)+'</td><td>'+comboBar(r.actual_payment,mx3,"#2563eb")+'</td>'+
           '<td class="n m" style="color:#7c3aed;font-weight:700">'+money(r.paid_amount)+'</td><td>'+comboBar(r.paid_amount,mx3,"#7c3aed")+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><td>Total</td><td class="n m">'+money(tv)+'</td><td></td><td class="n m">'+money(tc)+'</td><td></td><td class="n m">'+money(tpd)+'</td><td></td></tr></tfoot></table>';
    }
    box.innerHTML=h;
  }
  function drawFunnel(f){
    var box=el("wm-funnel"); if(!box) return;
    var stg=[["Approved plans",f.planned||0],["Assigned",f.assigned||0],["Confirmed actuals",f.confirmed||0],["Payment runs",f.paid||0]];
    var w=760,bh=30,gv=16,top=6,padL=130,h=top+stg.length*(bh+gv);
    var s=svgEl("svg",{viewBox:"0 0 "+w+" "+h});
    var mx=1; stg.forEach(function(x){ mx=Math.max(mx,x[1]); });
    var sc=(w-padL-110)/mx;
    stg.forEach(function(x,i){
      var y=top+i*(bh+gv);
      s.appendChild(svgEl("text",{x:padL-10,y:y+bh/2+4,"text-anchor":"end","font-size":11,"font-weight":600},x[0]));
      var bw=Math.max(3,x[1]*sc);
      s.appendChild(svgEl("rect",{x:padL,y:y+3,width:bw,height:bh-6,fill:"#0a0a0a"}));
      s.appendChild(svgEl("text",{x:padL+bw+8,y:y+bh/2+4,"font-size":13,"font-weight":700},fmt(x[1])));
    });
    box.innerHTML=""; box.appendChild(s);
  }

  function drawBars(rows){
    var box=el("wm-bars"); if(!box) return;
    if(!rows.length){ box.innerHTML='<div class="empty">No data.</div>'; return; }
    var w=760,rowH=44,padL=90,padR=70,top=8,h=top+rows.length*rowH+4;
    var s=svgEl("svg",{viewBox:"0 0 "+w+" "+h});
    var defs=svgEl("defs"); var pat=svgEl("pattern",{id:"wmh",width:5,height:5,patternUnits:"userSpaceOnUse",patternTransform:"rotate(45)"});
    pat.appendChild(svgEl("rect",{width:5,height:5,fill:"#fff"}));
    pat.appendChild(svgEl("line",{x1:0,y1:0,x2:0,y2:5,stroke:"#c2c2c2","stroke-width":2}));
    defs.appendChild(pat); s.appendChild(defs);
    var mx=1; rows.forEach(function(r){ mx=Math.max(mx,r.planned_people||0,r.assigned_workers||0); });
    var sc=(w-padL-padR)/mx;
    rows.forEach(function(r,i){
      var y=top+i*rowH;
      s.appendChild(svgEl("text",{x:padL-10,y:y+rowH/2,"text-anchor":"end","font-size":11,"font-weight":700},r.farm));
      var pw=Math.max(2,(r.planned_people||0)*sc), aw=Math.max(2,(r.assigned_workers||0)*sc);
      s.appendChild(svgEl("rect",{x:padL,y:y+6,width:pw,height:11,fill:"url(#wmh)",stroke:"#0a0a0a","stroke-width":.7}));
      s.appendChild(svgEl("text",{x:padL+pw+6,y:y+15,"font-size":10,"font-weight":600,fill:"#444"},fmt(r.planned_people)));
      s.appendChild(svgEl("rect",{x:padL,y:y+21,width:aw,height:11,fill:"#0a0a0a"}));
      s.appendChild(svgEl("text",{x:padL+aw+6,y:y+30,"font-size":10,"font-weight":700},fmt(r.assigned_workers)));
    });
    box.innerHTML=""; box.appendChild(s);
  }

  function drawBars2(rows){
    var box=el("wm-bars2"); if(!box) return;
    if(!rows.length){ box.innerHTML='<div class="empty">No data.</div>'; return; }
    var w=760,rowH=44,padL=90,padR=90,top=8,h=top+rows.length*rowH+4;
    var s=svgEl("svg",{viewBox:"0 0 "+w+" "+h});
    var mx=1; rows.forEach(function(r){ mx=Math.max(mx,r.planned_qty||0,r.actual_qty||0); });
    var sc=(w-padL-padR)/mx;
    rows.forEach(function(r,i){
      var y=top+i*rowH;
      s.appendChild(svgEl("text",{x:padL-10,y:y+rowH/2,"text-anchor":"end","font-size":11,"font-weight":700},r.farm));
      var pw=Math.max(2,(r.planned_qty||0)*sc), aw=Math.max(2,(r.actual_qty||0)*sc);
      var pct=(r.planned_qty>0)?Math.round((r.actual_qty||0)/r.planned_qty*100):0;
      s.appendChild(svgEl("rect",{x:padL,y:y+6,width:pw,height:11,fill:"#e5e7eb",stroke:"#9ca3af","stroke-width":.7}));
      s.appendChild(svgEl("text",{x:padL+pw+6,y:y+15,"font-size":10,"font-weight":600,fill:"#666"},fmt(r.planned_qty)));
      var col=(pct>=100)?"#0a7a43":"#2563eb";
      s.appendChild(svgEl("rect",{x:padL,y:y+21,width:aw,height:11,fill:col}));
      s.appendChild(svgEl("text",{x:padL+aw+6,y:y+30,"font-size":10,"font-weight":700,fill:col},fmt(r.actual_qty)+" ("+pct+"%)"));
    });
    box.innerHTML=""; box.appendChild(s);
  }

  function drawBars3(rows){
    var box=el("wm-bars3"); if(!box) return;
    if(!rows.length){ box.innerHTML='<div class="empty">No data.</div>'; return; }
    var w=760,rowH=56,padL=90,padR=90,top=8,h=top+rows.length*rowH+4;
    var s=svgEl("svg",{viewBox:"0 0 "+w+" "+h});
    var mx=1; rows.forEach(function(r){ mx=Math.max(mx,r.planned_value||0,r.actual_payment||0,r.paid_amount||0); });
    var sc=(w-padL-padR)/mx;
    rows.forEach(function(r,i){
      var y=top+i*rowH;
      s.appendChild(svgEl("text",{x:padL-10,y:y+rowH/2,"text-anchor":"end","font-size":11,"font-weight":700},r.farm));
      var pv=Math.max(2,(r.planned_value||0)*sc), cv=Math.max(2,(r.actual_payment||0)*sc), pd=Math.max(2,(r.paid_amount||0)*sc);
      s.appendChild(svgEl("rect",{x:padL,y:y+4,width:pv,height:11,fill:"#e5e7eb",stroke:"#9ca3af","stroke-width":.7}));
      s.appendChild(svgEl("text",{x:padL+pv+6,y:y+13,"font-size":9,"font-weight":600,fill:"#666"},money(r.planned_value)));
      s.appendChild(svgEl("rect",{x:padL,y:y+17,width:cv,height:11,fill:"#2563eb"}));
      s.appendChild(svgEl("text",{x:padL+cv+6,y:y+26,"font-size":9,"font-weight":700,fill:"#2563eb"},money(r.actual_payment)));
      s.appendChild(svgEl("rect",{x:padL,y:y+30,width:pd,height:11,fill:"#7c3aed"}));
      s.appendChild(svgEl("text",{x:padL+pd+6,y:y+39,"font-size":9,"font-weight":700,fill:"#7c3aed"},money(r.paid_amount)));
    });
    box.innerHTML=""; box.appendChild(s);
  }

  // ===== PIPELINE EXPLORER =====
  var PEX={stage:"plans"};
  function pexState(){
    return {
      farm: (el("pex-farm")||{}).value||"",
      state: (el("pex-state")||{}).value||"",
      task: (el("pex-task")||{}).value||"",
      block: (el("pex-block")||{}).value||"",
      from_date: (el("pex-from")||{}).value||"",
      to_date: (el("pex-to")||{}).value||"",
      q: (el("pex-q")||{}).value||""
    };
  }
  function fmtDT(v){ if(!v) return "—"; var s=String(v).replace("T"," "); return s.length>=16?s.substring(0,16):s; }
  function stateTag(st){
    var c="#6b7280";
    if(st==="Approved"||st==="Assigned"||st==="CONFIRMED"||st==="Confirmed"||st==="Paid") c="#0a7a43";
    else if(st&&st.indexOf("Pending")>=0) c="#a06000";
    else if(st==="Rejected") c="#b91c1c";
    else if(st==="Draft") c="#6b7280";
    return '<span class="pex-st" style="background:'+c+'">'+esc(st||"Draft")+'</span>';
  }
  function lifePill(r){
    var order=["planned","assigned","done","paid"];
    var labels={planned:"Planned",assigned:"Assigned",done:"Done",paid:"Paid"};
    var cols={planned:"#b91c1c",assigned:"#a06000",done:"#2563eb",paid:"#0a7a43"};
    var s=r.life_status||"planned";
    if(r.is_closed) s = (order.indexOf(s)>=0? s : "planned");
    var idx=order.indexOf(s); if(idx<0) idx=0;
    var reachedCol = r.is_closed ? "#334155" : cols[s];
    var seg="";
    for(var i=0;i<4;i++){
      var on = i<=idx;
      seg+='<span class="lt-seg" style="background:'+(on?reachedCol:"var(--faint)")+'"></span>';
    }
    var txt = r.is_closed ? "Closed" : labels[s];
    return '<span class="lt" title="'+esc(txt)+'"><span class="lt-track">'+seg+'</span><span class="lt-lbl" style="color:'+reachedCol+'">'+esc(txt)+'</span></span>';
  }
  function deskLink(dt, name){
    var slug=dt.toLowerCase().split(" ").join("-");
    return '<a class="pex-desk" href="/app/'+slug+'/'+encodeURIComponent(name)+'" target="_blank" onclick="event.stopPropagation()">Desk ↗</a>';
  }
  function loadPex(){
    var box=el("pex-list"); if(!box) return;
    box.innerHTML="Loading…";
    var a=pexState(); a.action="pipeline"; a.pstage=PEX.stage;
    call(a).then(function(d){
      var rows=d.rows||[];
      var farmSel=el("pex-farm");
      if(farmSel && farmSel.options.length<=1 && d.farms){
        d.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; farmSel.appendChild(o); });
      }
      // lifecycle status filter (plans tab only)
      var lifeSel=el("pex-life");
      if(lifeSel) lifeSel.style.display = (PEX.stage==="plans") ? "" : "none";
      if(PEX.stage==="plans" && lifeSel && lifeSel.value){
        var want=lifeSel.value;
        rows=rows.filter(function(r){
          var st = r.is_closed ? "closed" : (r.life_status||"planned");
          return st===want;
        });
      }
      if(!rows.length){ box.innerHTML='<div class="empty">No records match.</div>'; return; }
      box.innerHTML=pexTable(PEX.stage, rows);
      box.querySelectorAll("tr[data-open]").forEach(function(tr){
        tr.onclick=function(){ openPlanModal(tr.getAttribute("data-open"), tr.getAttribute("data-dt")); };
      });
      box.querySelectorAll("tr[data-actual]").forEach(function(tr){
        tr.onclick=function(){ openActualModal(tr.getAttribute("data-actual")); };
      });
      box.querySelectorAll("tr[data-payment]").forEach(function(tr){
        tr.onclick=function(){ openPaymentModal(tr.getAttribute("data-payment")); };
      });
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load.</div>'; });
  }
  function stdFmt(r){
    if(!r.std || r.std<=0) return '—';
    var u = r.std_uom ? (' '+r.std_uom) : '';
    return fmt(r.std)+u+'/day';
  }
  function pexTable(stage, rows){
    var h='<table class="pex"><thead><tr>';
    if(stage==="plans"){
      h+='<th class="n">Std</th><th>Plan</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>'+esc(TX("unit_singular","Block"))+'</th><th>Task</th><th>Status</th><th class="n">Target</th><th class="n">People/day</th><th class="n">Value</th><th>Period</th><th>State</th><th>Created</th>';
    } else if(stage==="assignments"){
      h+='<th class="n">Std</th><th>Assignment</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th class="n">Cost</th><th>Period</th><th>State</th><th>Created</th>';
    } else if(stage==="actuals"){
      h+='<th class="n">Std</th><th>Actual</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>Task</th><th class="n">Qty</th><th class="n">Workers</th><th class="n">Payment</th><th>State</th><th>Entered by</th><th>Created</th>';
    } else {
      h+='<th>Payment</th><th class="n">Amount</th><th>Period</th><th>State</th><th>Created</th>';
    }
    h+='</tr></thead><tbody>';
    rows.forEach(function(r){
      var dt = stage==="plans"?"Work Management Planner":(stage==="assignments"?"Work Management Assigner":(stage==="actuals"?"Work Management Actuals":"Work Management Payment"));
      var openId=r.name;
      if(stage==="plans"){
        h+='<tr data-open="'+esc(r.name)+'" data-dt="plan"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(taskName(r.task))+'</td><td>'+lifePill(r)+'</td><td class="n m">'+fmt(r.quantity)+' '+esc(r.uom||"")+'</td><td class="n m">'+fmt(r.people_per_day)+'</td><td class="n m">'+money(r.total_cost)+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else if(stage==="assignments"){
        h+='<tr data-open="'+esc(r.planner_request||"")+'" data-dt="plan"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(taskName(r.task))+'</td><td class="n m">'+fmt(r.planned_people)+'</td><td class="n m">'+fmt(r.assigned_count)+'</td><td class="n m">'+money(r.planned_cost)+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else if(stage==="actuals"){
        h+='<tr data-actual="'+esc(r.name)+'"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(taskName(r.task))+'</td><td class="n m">'+fmt(r.total_actual_qty)+'</td><td class="n m">'+fmt(r.payroll_people)+'</td><td class="n m">'+money(r.total_payment)+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+esc(r.entered_by||"—")+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else {
        h+='<tr data-payment="'+esc(r.name)+'"><td><b>'+esc(r.run_title||r.name)+'</b></td><td class="n m">'+money(r.amount)+'</td><td>'+esc(r.period_from||"?")+' → '+esc(r.period_to||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      }
    });
    return h+'</tbody></table>';
  }
  function trail(label, who, when){
    if(!who && !when) return "";
    return '<div class="pex-trailrow"><span>'+label+'</span><b>'+esc(who||"—")+'</b><i>'+fmtDT(when)+'</i></div>';
  }
  function openPlanModal(planName, dt){
    if(!planName){ toast("No linked plan"); return; }
    var m=el("pex-modal"), body=el("pex-modal-body");
    body.innerHTML="Loading lineage…"; m.classList.add("on");
    call({action:"plan_lineage", plan:planName}).then(function(d){
      var p=d.plan||{}; var asgs=d.assignments||[];
      var h='<div class="pex-h"><h2>'+esc(p.name||planName)+'</h2>'+stateTag(p.workflow_state)+deskLink("Work Management Planner",p.name||planName)+'</div>';
      h+='<div class="pex-sec">PLAN</div><div class="pex-kv">'+
         '<div><span>'+esc(TX("top_singular","Farm"))+'</span><b>'+esc(p.farm||"—")+'</b></div>'+
         '<div><span>'+esc(TX("unit_singular","Block"))+'</span><b>'+esc(lbl(p.block_section)||"—")+'</b></div>'+
         '<div><span>Task</span><b>'+esc(taskName(p.task)||"—")+taskStdSub(p.task)+'</b></div>'+
         '<div><span>Target</span><b>'+fmt(p.quantity)+' '+esc(p.uom||"")+'</b></div>'+
         '<div><span>Qty done</span><b>'+fmt(p.done_qty)+' '+esc(p.uom||"")+(p.is_complete?' <span class="pex-cmp">complete</span>':'')+'</b></div>'+
         '<div><span>Qty remaining</span><b>'+(p.over_qty>0?('<span class="pex-over">over by '+fmt(p.over_qty)+'</span>'):(fmt(p.remaining_qty)+' '+esc(p.uom||"")))+(p.pending_qty>0?(' <span class="pex-pend">+'+fmt(p.pending_qty)+' pending</span>'):'')+'</b></div>'+
         '<div><span>People/day</span><b>'+fmt(p.people_per_day)+'</b></div>'+
         '<div><span>Crew-days</span><b>'+fmt(p.person_days)+'</b></div>'+
         '<div><span>Value</span><b>'+money(p.total_cost)+' KES</b></div>'+
         '<div><span>Period</span><b>'+esc(p.from_date||"?")+' → '+esc(p.to_date||"?")+'</b></div>'+
         '<div><span>Created</span><b>'+fmtDT(p.creation)+'</b></div>'+
         '</div>';
      h+='<div class="pex-trail">'+trail("Requested",p.requested_by,p.request_date)+trail("Approved",p.approved_by,p.approval_date)+'</div>';
      // cost reconciliation: planned vs task-worker paid vs salaried-covered vs balance
      if((p.planned_value||0)>0 || (p.salaried_qty||0)>0){
        var pv=p.planned_value||0, twv=p.tw_paid_value||0, salv=p.salaried_value||0, balv=p.balance_value||0;
        var savedPct = pv>0 ? Math.round((salv/pv)*100) : 0;
        h+='<div class="pex-sec">COST RECONCILIATION</div>'+
           '<div class="cb-totals">'+
             '<div class="cb-tot-card"><span>Planned value</span><b>'+money(pv)+'</b></div>'+
             '<div class="cb-tot-card paid"><span>Task-worker paid</span><b>'+money(twv)+'</b></div>'+
             '<div class="cb-tot-card" style="border-left:3px solid #0a7a43"><span>Salaried-covered</span><b>'+money(salv)+'</b></div>'+
             '<div class="cb-tot-card out"><span>Balance (undelivered)</span><b>'+money(balv)+'</b></div>'+
           '</div>'+
           '<div style="font-size:11px;color:#4b5563;margin:6px 0 2px">'+
             'Of the planned <b>'+money(pv)+'</b>, task-workers are paid <b>'+money(twv)+'</b> ('+fmt(p.tw_qty)+' '+esc(p.uom||"")+'). '+
             'Salaried crew delivered <b>'+fmt(p.salaried_qty)+' '+esc(p.uom||"")+'</b> worth <b>'+money(salv)+'</b> at no piece-rate cost'+(savedPct>0?(' — '+savedPct+'% of the planned value covered by salaried labour'):'')+'. '+
             (balv>0?('Remaining <b>'+money(balv)+'</b> ('+fmt(p.balance_qty)+' '+esc(p.uom||"")+') not yet delivered.'):'Target fully delivered.')+
           '</div>';
      }
      h+='<div class="pex-sec">ASSIGNMENTS ('+asgs.length+')</div>';
      if(!asgs.length){ h+='<div class="empty">No assignments yet.</div>'; }
      asgs.forEach(function(a){
        h+='<div class="pex-block">';
        h+='<div class="pex-blockh"><b>'+esc(a.name)+'</b> '+stateTag(a.workflow_state)+deskLink("Work Management Assigner",a.name)+'</div>';
        h+='<div class="pex-kv sm">'+
           '<div><span>Planned</span><b>'+fmt(a.planned_people)+'</b></div>'+
           '<div><span>Assigned</span><b>'+fmt(a.assigned_count)+'</b></div>'+
           '<div><span>Cost</span><b>'+money(a.planned_cost)+'</b></div>'+
           '<div><span>Period</span><b>'+esc(a.from_date||"?")+' → '+esc(a.to_date||"?")+'</b></div>'+
           '<div><span>Created</span><b>'+fmtDT(a.creation)+'</b></div>'+
           '</div>';
        h+='<div class="pex-trail">'+trail("Assigned by",a.assigned_by,a.assign_date)+trail("FM approved",a.fm_approved_by,null)+trail("HR approved",a.hr_approved_by,null)+trail("GM approved",a.gm_approved_by||a.approved_by,a.approval_date)+'</div>';
        var ws=a.workers||[];
        if(ws.length){
          h+='<div class="pex-mini">Workers ('+ws.length+'): '+ws.slice(0,40).map(function(w){ return '<span class="pex-chip'+((w.status==="Left")?" left":"")+'">'+esc(w.employee_name||w.employee)+(w.status==="Left"?" (left)":"")+'</span>'; }).join(" ")+(ws.length>40?" …":"")+'</div>';
        }
        var acts=a.actuals||[];
        if(acts.length){
          h+='<div class="pex-mini"><b>Actuals:</b></div>';
          acts.forEach(function(ac){
            h+='<div class="pex-act">'+
               '<div class="pex-acth">'+esc(ac.name)+' '+stateTag(ac.workflow_state)+' · qty <b>'+fmt(ac.total_actual_qty)+'</b> · pay <b>'+money(ac.total_payment)+'</b> '+deskLink("Work Management Actuals",ac.name)+'</div>'+
               '<div class="pex-trail sm">'+trail("Entered",ac.entered_by,ac.entry_date)+trail("FM",ac.fm_approved_by,null)+trail("HR",ac.hr_approved_by,null)+trail("GM",ac.gm_approved_by,null)+'</div>';
            var dl=ac.daily||[];
            if(dl.length){
              h+='<table class="pex-daily"><thead><tr><th>Date</th><th>Worker</th><th class="n">Qty</th><th class="n">Amount</th><th>Payroll</th><th>Paid</th></tr></thead><tbody>';
              dl.slice(0,300).forEach(function(x){ h+='<tr><td>'+esc(x.work_date||"")+'</td><td>'+esc(x.employee_name||x.employee||"")+'</td><td class="n m">'+fmt(x.actual_quantity)+'</td><td class="n m">'+money(x.amount)+'</td><td>'+(x.count_in_payroll?"✓":"")+'</td><td>'+(x.paid?"✓"+(x.payment_ref?(" "+esc(x.payment_ref)):""):"")+'</td></tr>'; });
              h+='</tbody></table>';
            }
            h+='</div>';
          });
        }
        h+='</div>';
      });
      var pays=d.payments||[];
      h+='<div class="pex-sec">PAYMENT RUNS ('+pays.length+')</div>';
      if(!pays.length){ h+='<div class="empty">No payment runs.</div>'; }
      else {
        h+='<table class="pex"><thead><tr><th>Run</th><th class="n">Amount</th><th>Period</th><th>State</th><th>Created</th><th></th></tr></thead><tbody>';
        pays.forEach(function(pm){ h+='<tr><td>'+esc(pm.name)+'</td><td class="n m">'+money(pm.amount)+'</td><td>'+esc(pm.period_from||"?")+' → '+esc(pm.period_to||"?")+'</td><td>'+stateTag(pm.workflow_state)+'</td><td>'+fmtDT(pm.creation)+'</td><td>'+deskLink("Work Management Payment",pm.name)+'</td></tr>'; });
        h+='</tbody></table>';
      }
      body.innerHTML=h;
    }).catch(function(e){ body.innerHTML='<div class="empty">Could not load lineage.</div>'; });
  }
  function openActualModal(actualName){
    var m=el("pex-modal"), body=el("pex-modal-body");
    body.innerHTML="Loading actual…"; m.classList.add("on");
    call({action:"actual_detail", actual:actualName}).then(function(d){
      var a=d.actual||{}; var dl=d.daily||[];
      var h='<div class="pex-h"><h2>'+esc(a.name||actualName)+'</h2>'+stateTag(a.workflow_state)+deskLink("Work Management Actuals",a.name||actualName)+'</div>';
      h+='<div class="pex-sec">ACTUAL</div><div class="pex-kv">'+
         '<div><span>'+esc(TX("top_singular","Farm"))+'</span><b>'+esc(a.farm||"—")+'</b></div>'+
         '<div><span>'+esc(TX("unit_singular","Block"))+'</span><b>'+esc(lbl(a.block_section)||"—")+'</b></div>'+
         '<div><span>Task</span><b>'+esc(taskName(a.task)||"—")+taskStdSub(a.task)+'</b></div>'+
         '<div><span>Qty done</span><b>'+fmt(a.total_actual_qty)+'</b></div>'+
         '<div><span>Workers (payroll)</span><b>'+fmt(a.payroll_people)+'</b></div>'+
         '<div><span>Payment</span><b>'+money(a.total_payment)+' KES</b></div>'+
         '<div><span>Created</span><b>'+fmtDT(a.creation)+'</b></div>'+
         '</div>';
      h+='<div class="pex-trail">'+trail("Entered",a.entered_by,a.entry_date)+trail("FM approved",a.fm_approved_by,null)+trail("HR approved",a.hr_approved_by,null)+trail("GM approved",a.gm_approved_by,null)+'</div>';
      if(d.plan_ref){
        h+='<div class="pex-up"><button class="pex-uplink" data-plan="'+esc(d.plan_ref)+'">↑ View full plan lineage ('+esc(d.plan_ref)+')</button>'+(d.assignment_ref?(' · assignment: '+esc(d.assignment_ref)+deskLink("Work Management Assigner",d.assignment_ref)):'')+'</div>';
      }
      h+='<div class="pex-sec">DAILY ENTRIES ('+dl.length+')</div>';
      if(!dl.length){ h+='<div class="empty">No daily entries.</div>'; }
      else {
        h+='<table class="pex-daily"><thead><tr><th>Date</th><th>Worker</th><th>Type</th><th class="n">Qty</th><th class="n">Amount</th><th>Payroll</th><th>Paid</th></tr></thead><tbody>';
        dl.slice(0,400).forEach(function(x){ h+='<tr><td>'+esc(x.work_date||"")+'</td><td>'+esc(x.employee_name||x.employee||"")+'</td><td>'+esc(x.employment_type||"")+'</td><td class="n m">'+fmt(x.actual_quantity)+'</td><td class="n m">'+money(x.amount)+'</td><td>'+(x.count_in_payroll?"✓":"")+'</td><td>'+(x.paid?"✓"+(x.payment_ref?(" "+esc(x.payment_ref)):""):"")+'</td></tr>'; });
        h+='</tbody></table>';
      }
      body.innerHTML=h;
      var up=body.querySelector(".pex-uplink");
      if(up){ up.onclick=function(){ openPlanModal(up.getAttribute("data-plan"),"plan"); }; }
    }).catch(function(e){ body.innerHTML='<div class="empty">Could not load actual.</div>'; });
  }

  function openEmpModal(emp){
    if(!emp){ return; }
    var m=el("pex-modal"), body=el("pex-modal-body");
    body.innerHTML="Loading worker…"; m.classList.add("on");
    call({action:"emp_detail", employee:emp}).then(function(d){
      var p=d.profile||{}; var t=d.totals||{}; var asg=d.assignments||[]; var acts=d.actuals||[];
      var h='<div class="pex-h"><h2>'+esc(p.employee_name||emp)+'</h2>'+(p.status?('<span class="pex-st" style="background:'+((p.status==="Active")?"#0a7a43":"#6b7280")+'">'+esc(p.status)+'</span>'):'')+deskLink("Employee",p.name||emp)+'</div>';
      h+='<div class="pex-sec">WORKER</div><div class="pex-kv">'+
         '<div><span>Employee ID</span><b>'+esc(p.name||emp)+'</b></div>'+
         '<div><span>'+esc(TX("top_singular","Farm"))+'</span><b>'+esc(p.custom_farm||"—")+'</b></div>'+
         '<div><span>Business unit</span><b>'+esc(p.custom_business_unit||"—")+'</b></div>'+
         '<div><span>Group</span><b>'+esc(p.custom_group_name||"—")+'</b></div>'+
         '<div><span>Designation</span><b>'+esc(p.designation||"—")+'</b></div>'+
         '<div><span>Type</span><b>'+esc(p.employment_type||"—")+'</b></div>'+
         '<div><span>Joined</span><b>'+esc(p.date_of_joining||"—")+'</b></div>'+
         '</div>';
      h+='<div class="cb-totals" style="margin-top:14px">'+
         '<div class="cb-tot-card"><span>Assignments</span><b>'+fmt(t.assignments)+'</b></div>'+
         '<div class="cb-tot-card"><span>Days worked</span><b>'+fmt(t.days_worked)+'</b></div>'+
         '<div class="cb-tot-card"><span>Qty done</span><b>'+fmt(t.qty)+'</b></div>'+
         '<div class="cb-tot-card"><span>Earned</span><b>'+money(t.earned)+'</b></div>'+
         '<div class="cb-tot-card paid"><span>Paid</span><b>'+money(t.paid)+'</b></div>'+
         '<div class="cb-tot-card out"><span>Outstanding</span><b>'+money(t.outstanding)+'</b></div>'+
         '</div>';
      h+='<div class="pex-sec">ASSIGNMENTS ('+asg.length+')</div>';
      if(!asg.length){ h+='<div class="empty">No assignments.</div>'; }
      else {
        h+='<table class="pex"><thead><tr><th>Task</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>'+esc(TX("unit_singular","Block"))+'</th><th>Period</th><th>State</th><th>Worker</th><th></th></tr></thead><tbody>';
        asg.forEach(function(r){
          var wtag=(r.wstatus==="Left")?'<span class="pex-st" style="background:#b91c1c">left</span>':'<span class="pex-st" style="background:#0a7a43">active</span>';
          h+='<tr><td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(lbl(r.block_section)||"")+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.state)+'</td><td>'+wtag+'</td><td>'+(r.plan?('<a href="#" class="et-planlink" data-plan="'+esc(r.plan)+'">plan ↗</a>'):'')+'</td></tr>';
        });
        h+='</tbody></table>';
      }
      h+='<div class="pex-sec">ACTUALS &mdash; daily work &amp; pay ('+acts.length+')</div>';
      if(!acts.length){ h+='<div class="empty">No actuals recorded.</div>'; }
      else {
        h+='<table class="pex-daily"><thead><tr><th>Date</th><th>Task</th><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Qty</th><th class="n">Amount</th><th>Payroll</th><th>Paid</th><th>State</th></tr></thead><tbody>';
        acts.slice(0,500).forEach(function(r){
          h+='<tr><td>'+esc(r.work_date||"")+'</td><td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td><td>'+esc(r.farm||"")+'</td><td class="n">'+fmt(r.qty)+'</td><td class="n">'+money(r.amount)+'</td><td>'+(r.in_payroll?"✓":"")+'</td><td>'+(r.paid?("✓"+(r.payment_ref?(" "+esc(r.payment_ref)):"")):"")+'</td><td>'+stateTag(r.state)+'</td></tr>';
        });
        h+='</tbody></table>';
      }
      body.innerHTML=h;
      body.querySelectorAll(".et-planlink").forEach(function(lnk){
        lnk.onclick=function(ev){ ev.preventDefault(); openPlanModal(lnk.getAttribute("data-plan"),"plan"); };
      });
    }).catch(function(e){ body.innerHTML='<div class="empty">Could not load worker detail.</div>'; });
  }

  function openPaymentModal(payName){
    var m=el("pex-modal"), body=el("pex-modal-body");
    body.innerHTML="Loading payment…"; m.classList.add("on");
    call({action:"payment_detail", payment:payName}).then(function(d){
      var p=d.payment||{}; var lines=d.lines||[];
      var h='<div class="pex-h"><h2>'+esc(p.run_title||p.name||payName)+'</h2>'+stateTag(p.workflow_state)+deskLink("Work Management Payment",p.name||payName)+'</div>';
      h+='<div class="pex-sec">PAYMENT RUN</div><div class="pex-kv">'+
         '<div><span>Amount</span><b>'+money(p.amount)+' KES</b></div>'+
         '<div><span>Period</span><b>'+esc(p.period_from||"?")+' → '+esc(p.period_to||"?")+'</b></div>'+
         '<div><span>Payroll date</span><b>'+esc(p.payroll_date||"—")+'</b></div>'+
         '<div><span>Company</span><b>'+esc(p.company||"—")+'</b></div>'+
         '<div><span>Actuals in run</span><b>'+fmt(p.total_actuals)+'</b></div>'+
         '<div><span>Workers paid</span><b>'+fmt(p.total_workers)+'</b></div>'+
         '<div><span>Created</span><b>'+fmtDT(p.creation)+'</b></div>'+
         '</div>';
      h+='<div class="pex-trail">'+trail("Prepared by",p.prepared_by,p.payroll_date)+trail("Accounts approved",p.accounts_approved_by,p.accounts_approval_date)+'</div>';
      h+='<div class="pex-sec">PAYMENT LINES ('+lines.length+')</div>';
      if(!lines.length){ h+='<div class="empty">No payment lines.</div>'; }
      else {
        var tot=0;
        h+='<table class="pex-daily"><thead><tr><th>Worker</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>Task</th><th class="n">Days</th><th class="n">Qty</th><th class="n">Amount</th></tr></thead><tbody>';
        lines.slice(0,2000).forEach(function(x){ tot+=(x.amount||0); h+='<tr><td>'+esc(x.employee_name||x.employee||"")+'</td><td>'+esc(x.farm||"")+'</td><td>'+esc(taskName(x.task))+taskStdSub(x.task)+'</td><td class="n m">'+fmt(x.days)+'</td><td class="n m">'+fmt(x.qty)+'</td><td class="n m">'+money(x.amount)+'</td></tr>'; });
        h+='</tbody><tfoot><tr><td><b>Total</b></td><td></td><td></td><td></td><td></td><td class="n m"><b>'+money(tot)+'</b></td></tr></tfoot></table>';
      }
      body.innerHTML=h;
    }).catch(function(e){ body.innerHTML='<div class="empty">Could not load payment.</div>'; });
  }

  function setStates(){
    var stSel=el("pex-state");
    if(!stSel) return;
    var opts={plans:["Draft","Pending Approval","Approved","Rejected"],assignments:["Draft","Pending Farm Manager","Pending HR Head","Pending GM","Assigned","Rejected"],actuals:["Draft","Pending Farm Manager","Pending HR Head","Pending GM","Confirmed","Rejected"],payments:["Draft","Unpaid","Paid","Rejected"]};
    stSel.innerHTML='<option value="">All states</option>';
    (opts[PEX.stage]||[]).forEach(function(o){ var e=document.createElement("option"); e.value=o; e.textContent=o; stSel.appendChild(e); });
  }
  var CB={group:"task"};
  function cbState(){
    return {
      farm:(el("cb-farm")||{}).value||"",
      task:(el("cb-task")||{}).value||"",
      from_date:(el("cb-from")||{}).value||"",
      to_date:(el("cb-to")||{}).value||"",
      q:(el("cb-q")||{}).value||""
    };
  }
  function loadCost(){
    var box=el("cb-list"); if(!box) return;
    box.innerHTML="Loading…";
    var a=cbState(); a.action="cost_breakdown"; a.group=CB.group;
    call(a).then(function(d){
      var fs=el("cb-farm");
      if(fs && fs.options.length<=1 && d.farms){ d.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); }); }
      var t=d.totals||{};
      var tt=el("cb-totals");
      if(tt){
        tt.innerHTML='<div class="cb-tot-card"><span>Estimated</span><b>'+money(t.estimated)+'</b></div>'+
                     '<div class="cb-tot-card paid"><span>Paid out</span><b>'+money(t.paid)+'</b></div>'+
                     '<div class="cb-tot-card out"><span>Outstanding</span><b>'+money(t.outstanding)+'</b></div>';
      }
      var rows=d.breakdown||[];
      if(!rows.length){ box.innerHTML='<div class="empty">No cost data for this filter.</div>'; return; }
      var head = (CB.group==="worker")?"Worker":((CB.group==="farm")?esc(TX("top_singular","Farm")):"Activity");
      var h='<table class="pex"><thead><tr><th>'+head+'</th>';
      if(CB.group!=="worker") h+='<th class="n">Workers</th>';
      h+='<th class="n">Qty</th><th class="n">Estimated</th><th class="n">Paid out</th><th class="n">Outstanding</th><th>Progress</th></tr></thead><tbody>';
      rows.forEach(function(r){
        var pct = r.estimated>0 ? Math.round(r.paid/r.estimated*100) : 0;
        h+='<tr><td><b>'+esc(r.key)+'</b></td>';
        if(CB.group!=="worker") h+='<td class="n m">'+fmt(r.worker_count)+'</td>';
        h+='<td class="n m">'+fmt(r.qty)+'</td>'+
           '<td class="n m">'+money(r.estimated)+'</td>'+
           '<td class="n m">'+money(r.paid)+'</td>'+
           '<td class="n m">'+(r.outstanding>0?('<span style="color:#a06000">'+money(r.outstanding)+'</span>'):money(r.outstanding))+'</td>'+
           '<td><div class="cb-bar"><div class="cb-fill" style="width:'+Math.min(100,pct)+'%"></div></div><span class="cb-pct">'+pct+'%</span></td></tr>';
      });
      box.innerHTML=h+'</tbody></table>';
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load cost breakdown.</div>'; });
  }
  // ===== COST CENTRE (block) =====
  var CC={};
  function ccState(){
    return {
      farm:(el("cc-farm")||{}).value||"",
      from_date:(el("cc-from")||{}).value||"",
      to_date:(el("cc-to")||{}).value||"",
      q:(el("cc-q")||{}).value||"",
      group_by:(el("cc-group")||{}).value||"block"
    };
  }
  // What the rows are, right now. Everything the table says about them -- the
  // first column heading, the empty state, the tab, the search box -- reads it
  // here rather than assuming blocks, which is what left the block heading
  // standing over a column of section names.
  //
  // ccGroupText() is the only place in this file that reads a level name
  // without escaping it, and the only two things it feeds are .textContent and
  // .placeholder: both take text, neither parses markup, and escaping for them
  // would print &amp; at a reader. Anything going into markup takes
  // ccGroupLabel() instead. test_taxonomy.py's escaping guard exempts this one
  // function by name, and still trips on an unescaped level name anywhere else.
  function ccGroupText(){
    return ((el("cc-group")||{}).value==="section")
      ? TX("section_singular","Section") : TX("unit_singular","Block");
  }
  function ccGroupLabel(){ return esc(ccGroupText()); }
  function closeAllExpanded(scope){
    (scope||document).querySelectorAll("tr.wm-detail").forEach(function(tr){ tr.parentNode.removeChild(tr); });
    (scope||document).querySelectorAll("tr.wm-x.open").forEach(function(tr){ tr.classList.remove("open"); });
  }
  function makeExpandable(container, rowSelector, colspan, fetchArgs, renderDetail){
    if(!container) return;
    container.querySelectorAll(rowSelector).forEach(function(tr){
      tr.classList.add("wm-x");
      tr.addEventListener("click", function(ev){
        if(ev.target.closest && ev.target.closest("a")) return;
        var ref=tr.getAttribute("data-ref");
        var isOpen=tr.classList.contains("open");
        closeAllExpanded(container);
        if(isOpen) return;
        tr.classList.add("open");
        var dtr=document.createElement("tr");
        dtr.className="wm-detail";
        var td=document.createElement("td");
        td.colSpan=colspan;
        td.innerHTML='<div class="wm-dwrap"><div class="wm-dload">Loading detail…</div></div>';
        dtr.appendChild(td);
        tr.parentNode.insertBefore(dtr, tr.nextSibling);
        call(fetchArgs(ref,tr)).then(function(data){
          td.querySelector(".wm-dwrap").innerHTML=renderDetail(data,ref);
        }).catch(function(){
          td.querySelector(".wm-dwrap").innerHTML='<div class="wm-dload">Could not load detail.</div>';
        });
      });
    });
  }
  var CCDATA={blocks:[],totals:{},farm_totals:[],view:"block"};
  var CC_FARM_COLORS={};
  var CC_PALETTE=["#0a7a43","#2563eb","#7c3aed","#b45309","#0891b2","#be123c","#4d7c0f","#9333ea"];
  function ccFarmColor(farm){
    if(!CC_FARM_COLORS[farm]){
      var n=Object.keys(CC_FARM_COLORS).length;
      CC_FARM_COLORS[farm]=CC_PALETTE[n % CC_PALETTE.length];
    }
    return CC_FARM_COLORS[farm];
  }
  // green->amber->red by how a value compares to a median (efficiency: lower is better)
  function ccEffColor(v, med){
    if(v==null||med==null||med<=0) return "#9ca3af";
    var r=v/med;
    if(r<=0.8) return "#0a7a43";
    if(r<=1.1) return "#4d7c0f";
    if(r<=1.5) return "#b45309";
    return "#be123c";
  }
  function ccSpendColor(v, max){
    if(!max||max<=0) return "#e5e7eb";
    var r=v/max;
    if(r>=0.66) return "#0a7a43";
    if(r>=0.33) return "#4d9e6a";
    if(r>=0.12) return "#8fc4a6";
    return "#cfe3d7";
  }
  function sparkline(series, w, hgt, color){
    series=series||[];
    if(series.length<2) return '<span style="color:#bbb;font-size:10px">—</span>';
    var max=0; series.forEach(function(p){ if(p.pay>max) max=p.pay; });
    if(max<=0) return '<span style="color:#bbb;font-size:10px">—</span>';
    var n=series.length, step=w/(n-1), pts=[];
    for(var i=0;i<n;i++){ var x=i*step; var y=hgt-(series[i].pay/max*(hgt-2))-1; pts.push(x.toFixed(1)+","+y.toFixed(1)); }
    var last=series[n-1].pay, prev=series[n-2].pay;
    var arrow = last>prev ? "▲" : (last<prev ? "▼" : "▬");
    var acol = last>prev ? "#be123c" : (last<prev ? "#0a7a43" : "#9ca3af");
    return '<svg width="'+w+'" height="'+hgt+'" style="vertical-align:middle"><polyline fill="none" stroke="'+(color||"#2563eb")+'" stroke-width="1.5" points="'+pts.join(" ")+'"/></svg> <span style="color:'+acol+';font-size:10px">'+arrow+'</span>';
  }
  function ccTreemap(rows, mode, total, med){
    var box=el("cc-treemap"); if(!box) return;
    if(!rows.length){ box.innerHTML=""; return; }
    // squarified-ish: simple row-packing by descending spend into a fixed-height band
    var W=100; // percent width base
    var top=rows.slice(0,24); // cap boxes for legibility
    var sum=0; top.forEach(function(r){ sum+=r.labour_spend; });
    if(sum<=0){ box.innerHTML=""; return; }
    var maxL=0; rows.forEach(function(r){ if(r.labour_spend>maxL) maxL=r.labour_spend; });
    var h='<div style="display:flex;flex-wrap:wrap;gap:3px;align-items:stretch">';
    top.forEach(function(r){
      var pct=r.labour_spend/sum*100;
      // width scales with share; min 8% so labels fit, cap rows by flex-wrap
      var basis=Math.max(8, Math.min(48, pct*1.6));
      var col;
      if(mode==="cpu") col=ccEffColor(r.cost_per_unit, med);
      else if(mode==="farm") col=ccFarmColor(r.farm);
      else col=ccSpendColor(r.labour_spend, maxL);
      var share=total>0?Math.round(r.labour_spend/total*100):0;
      var cpu = r.cost_per_unit!=null ? ("KES "+money(r.cost_per_unit)+"/unit") : "";
      h+='<div class="cc-tile" data-ref="'+esc(r.block)+'" title="'+esc(lbl(r.block))+' — '+money(r.labour_spend)+' ('+share+'%) '+cpu+'" '+
         'style="flex:1 1 '+basis.toFixed(1)+'%;min-width:96px;min-height:64px;background:'+col+';color:#fff;padding:8px 9px;cursor:pointer;display:flex;flex-direction:column;justify-content:space-between;border-radius:3px;overflow:hidden">'+
           '<div style="font-size:11px;font-weight:700;line-height:1.15;text-shadow:0 1px 1px rgba(0,0,0,.25)">'+esc(lbl(r.block))+'</div>'+
           '<div style="font-size:10px;opacity:.95">'+money(r.labour_spend)+' · '+share+'%</div>'+
         '</div>';
    });
    h+='</div>';
    // colour legend
    if(mode==="cpu"){
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Colour = cost per unit vs the median '+ccGroupLabel().toLowerCase()+': <span style="color:#0a7a43;font-weight:700">efficient</span> → <span style="color:#b45309;font-weight:700">costly</span> → <span style="color:#be123c;font-weight:700">most costly</span>. Box size = labour spend.</div>';
    } else if(mode==="farm"){
      var leg=''; Object.keys(CC_FARM_COLORS).forEach(function(f){ leg+='<span style="display:inline-block;margin-right:10px"><i style="display:inline-block;width:10px;height:10px;background:'+CC_FARM_COLORS[f]+';vertical-align:middle;margin-right:4px"></i>'+esc(f)+'</span>'; });
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Box size = labour spend. '+leg+'</div>';
    } else {
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Box size &amp; shade = labour spend (darker green = bigger running cost). Click any '+ccGroupLabel().toLowerCase()+' to drill in.</div>';
    }
    box.innerHTML=h;
    box.querySelectorAll(".cc-tile").forEach(function(t){
      t.onclick=function(){
        var ref=t.getAttribute("data-ref");
        // scroll to and open the matching table row
        var tbl=el("cc-list").querySelector('table[data-cctable="1"]');
        if(tbl){ var tr=tbl.querySelector('tbody tr[data-ref="'+cssEsc(ref)+'"]'); if(tr){ tr.scrollIntoView({behavior:"smooth",block:"center"}); tr.click(); } }
      };
    });
  }
  function cssEsc(s){ return String(s).replace(/["\\]/g,"\\$&"); }
  function renderCcDetail(d){
    var tasks=d.tasks||[], workers=d.workers||[], weekly=d.weekly||[], gla=d.gl_accounts||[];
    var h='<div class="wm-dhead"><div class="wm-dtitle">'+esc(lbl(d.block||""))+'<small>cost centre · '+fmt(tasks.length)+' tasks · '+fmt(workers.length)+' workers</small></div></div>';
    // weekly spend trend
    if(weekly.length>1){
      var maxp=0; weekly.forEach(function(x){ if(x.pay>maxp) maxp=x.pay; });
      h+='<div class="wm-dsec">Weekly running cost</div><div style="display:flex;align-items:flex-end;gap:4px;height:90px;padding:4px 0">';
      weekly.forEach(function(x){
        var hh=maxp>0?Math.max(2,Math.round(x.pay/maxp*76)):2;
        h+='<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:0">'+
           '<div style="font-size:8px;color:var(--mute);white-space:nowrap">'+money(x.pay)+'</div>'+
           '<div title="'+esc(x.w)+'" style="width:100%;max-width:34px;background:#2563eb;height:'+hh+'px"></div>'+
           '<div style="font-size:8px;color:var(--mute);margin-top:2px;white-space:nowrap">'+ccWk(x.w)+'</div></div>';
      });
      h+='</div>';
    }
    // GL account breakdown
    if(gla.length){
      var gtot=d.gl_total||0;
      h+='<div class="wm-dsec">GL cost-centre breakdown — what the posted spend hit ('+money(gtot)+')</div>';
      h+='<div class="wm-dtscroll"><table class="wm-dtable"><thead><tr><th>Account</th><th>Type</th><th class="n">Amount KES</th><th class="n">Share</th></tr></thead><tbody>';
      gla.forEach(function(x){
        var sh=gtot>0?Math.round(x.amount/gtot*100):0;
        h+='<tr><td>'+esc(x.account)+'</td><td>'+esc(x.root_type||"")+'</td><td class="n">'+money(x.amount)+'</td><td class="n">'+sh+'%</td></tr>';
      });
      h+='</tbody></table></div>';
    }
    // tasks table (+ cost/unit)
    h+='<div class="wm-dsec">Tasks in this '+esc(TX("unit_singular","Block")).toLowerCase()+' ('+tasks.length+')</div>';
    if(tasks.length){
      h+='<div class="wm-dtscroll"><table class="wm-dtable"><thead><tr><th>Task</th><th class="n">Spend KES</th><th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Workers</th><th class="n">Worker-days</th></tr></thead><tbody>';
      tasks.forEach(function(t){ h+='<tr><td>'+esc(t.label)+'</td><td class="n">'+fmt(t.spend)+'</td><td class="n">'+fmt(t.qty)+'</td><td class="n">'+(t.cost_per_unit!=null?money(t.cost_per_unit):"—")+'</td><td class="n">'+fmt(t.workers)+'</td><td class="n">'+fmt(t.worker_days)+'</td></tr>'; });
      h+='</tbody></table></div>';
    } else { h+='<div class="wm-dload">No tasks.</div>'; }
    // workers table (+ cost/unit)
    h+='<div class="wm-dsec">Workers on this '+esc(TX("unit_singular","Block")).toLowerCase()+' ('+workers.length+')</div>';
    if(workers.length){
      h+='<div class="wm-dtscroll"><table class="wm-dtable"><thead><tr><th>Worker</th><th class="n">Spend KES</th><th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Days</th><th class="n">Tasks</th></tr></thead><tbody>';
      workers.forEach(function(w){ h+='<tr><td>'+esc(w.nm||w.emp)+'</td><td class="n">'+fmt(w.spend)+'</td><td class="n">'+fmt(w.qty)+'</td><td class="n">'+(w.cost_per_unit!=null?money(w.cost_per_unit):"—")+'</td><td class="n">'+fmt(w.days)+'</td><td class="n">'+fmt(w.tasks)+'</td></tr>'; });
      h+='</tbody></table></div>';
    } else { h+='<div class="wm-dload">No workers.</div>'; }
    return h;
  }
  function ccWk(d){ if(!d) return ""; var x=new Date(d+"T00:00:00"); if(isNaN(x)) return ""; return x.getDate()+"/"+(x.getMonth()+1); }
  function renderCcTable(){
    var box=el("cc-list"); if(!box) return;
    var t=CCDATA.totals||{};
    var med=t.median_cost_per_unit;
    // Above the farm-tab return on purpose: the toggle can be moved while that
    // tab is in front, and leaving these behind it meant the heading and the
    // search box still said "block" until you switched tabs back.
    var word=ccGroupText(), label=ccGroupLabel();
    var qbox=el("cc-q"); if(qbox) qbox.placeholder="Search "+word.toLowerCase()+"\u2026";
    var gtab=document.querySelector('#cc-tabs button[data-ccview="block"]');
    if(gtab) gtab.textContent="By "+word.toLowerCase();
    if(CCDATA.view==="farm"){
      var frows=CCDATA.farm_totals||[];
      if(!frows.length){ box.innerHTML='<div class="empty">No data.</div>'; return; }
      var maxF=0; frows.forEach(function(r){ if(r.labour>maxF) maxF=r.labour; });
      var fh='<table class="pex"><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">'+esc(TX("unit_plural","Blocks"))+'</th><th class="n">Labour spend</th>'+(t.has_gl?'<th class="n">GL actuals</th>':'')+'<th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Worker-days</th><th>Share</th></tr></thead><tbody>';
      frows.forEach(function(r){
        var w=maxF>0?Math.round(r.labour/maxF*100):0;
        fh+='<tr><td><b><i style="display:inline-block;width:9px;height:9px;background:'+ccFarmColor(r.farm)+';margin-right:6px"></i>'+esc(r.farm)+'</b></td>'+
            '<td class="n m">'+fmt(r.blocks)+'</td><td class="n m">'+money(r.labour)+'</td>'+
            (t.has_gl?('<td class="n m">'+money(r.gl)+'</td>'):'')+
            '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+(r.cost_per_unit!=null?money(r.cost_per_unit):"—")+'</td>'+
            '<td class="n m">'+fmt(r.worker_days)+'</td>'+
            '<td><div class="cb-bar"><div class="cb-fill" style="width:'+w+'%;background:'+ccFarmColor(r.farm)+'"></div></div><span class="cb-pct">'+w+'%</span></td></tr>';
      });
      box.innerHTML=fh+'</tbody></table>';
      return;
    }
    var rows=CCDATA.blocks||[];
    if(!rows.length){ box.innerHTML='<div class="empty">No '+label.toLowerCase()+' spend for this filter.</div>'; return; }
    var maxL=0; rows.forEach(function(r){ if(r.labour_spend>maxL) maxL=r.labour_spend; });
    var h='<table class="pex" data-cctable="1"><thead><tr>'+
      '<th>'+label+' (cost centre)</th><th>'+esc(TX("top_singular","Farm"))+'</th>'+
      '<th class="n">Labour spend</th>'+(t.has_gl?'<th class="n">GL actuals</th><th class="n">Labour %</th>':'')+
      '<th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Cost/day</th><th class="n">Avg crew</th><th class="n">Days</th><th class="n">Workers</th>'+
      '<th>Trend</th><th>Share</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var w=maxL>0?Math.round(r.labour_spend/maxL*100):0;
      var cpuCol=ccEffColor(r.cost_per_unit, med);
      // A section row carries no cost centre of its own but does carry the GL
      // its blocks posted, and the Labour % beside this cell is derived from
      // it -- gating on cost_center alone printed a dash next to "75%".
      var glCell = t.has_gl ? ('<td class="n m">'+((r.cost_center||r.gl_spend>0)?money(r.gl_spend):'<span style="color:#bbb">—</span>')+'</td>'+
                   '<td class="n m">'+(r.labour_share!=null?('<span style="color:'+(r.labour_share>90?"#be123c":(r.labour_share>60?"#b45309":"#0a7a43"))+'">'+Math.round(r.labour_share)+'%</span>'):"—")+'</td>') : '';
      h+='<tr data-ref="'+esc(r.block)+'"><td><b>'+esc(lbl(r.block))+'</b></td><td>'+
         '<i style="display:inline-block;width:8px;height:8px;background:'+ccFarmColor(r.farm)+';margin-right:5px"></i>'+esc(r.farm||"")+'</td>'+
         '<td class="n m" style="font-weight:700">'+money(r.labour_spend)+'<div class="cb-bar" style="width:70px;height:5px;margin-top:3px;display:block"><div class="cb-fill" style="width:'+w+'%;background:#0a7a43"></div></div></td>'+
         glCell+
         '<td class="n m">'+fmt(r.qty)+'</td>'+
         '<td class="n m" style="color:'+cpuCol+';font-weight:600">'+(r.cost_per_unit!=null?money(r.cost_per_unit):"—")+'</td>'+
         '<td class="n m">'+(r.cost_per_wd!=null?money(r.cost_per_wd):"—")+'</td>'+
         '<td class="n m">'+(r.avg_crew!=null?fmt(r.avg_crew,1):"—")+'</td>'+
         '<td class="n m">'+fmt(r.days_active)+'</td>'+
         '<td class="n m">'+fmt(r.workers)+'</td>'+
         '<td>'+(function(){ var tr=r.trend||[]; var up=tr.length>1 && tr[tr.length-1]>tr[0]; var tcol=up?"#b91c1c":"#0a7a43"; return sparkline(tr,54,20,tcol)+(tr.length>1?('<span style="font-size:9px;font-weight:700;color:'+tcol+';margin-left:4px">'+(up?"▲":"▼")+'</span>'):''); })()+'</td>'+
         '<td><div class="cb-bar" style="width:110px"><div class="cb-fill" style="width:'+w+'%;background:'+ccFarmColor(r.farm)+'"></div></div><span class="cb-pct">'+w+'%</span></td></tr>';
    });
    box.innerHTML=h+'</tbody></table>';
    var ccT=box.querySelector('table[data-cctable="1"]');
    var colspan = t.has_gl ? 13 : 11;
    makeExpandable(ccT, "tbody tr", colspan, function(ref){
      var a=ccState(); a.action="cost_center_detail"; a.block=ref;
      return a;
    }, renderCcDetail);
  }
  function loadCostCentre(){
    var box=el("cc-list"); if(!box) return;
    box.innerHTML="Loading…";
    var a=ccState(); a.action="cost_center";
    call(a).then(function(d){
      var fs=el("cc-farm");
      if(fs && fs.options.length<=1 && d.farms){ d.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); }); }
      CCDATA.blocks=d.blocks||[]; CCDATA.totals=d.totals||{}; CCDATA.farm_totals=d.farm_totals||[];
      var t=CCDATA.totals;
      var tt=el("cc-totals");
      if(tt){
        tt.innerHTML='<div class="cb-tot-card"><span>'+esc(TX("unit_plural","Blocks"))+'</span><b>'+fmt(t.blocks)+'</b></div>'+
          '<div class="cb-tot-card"><span>Labour spend</span><b>'+money(t.labour)+'</b></div>'+
          (t.has_gl?('<div class="cb-tot-card paid"><span>GL cost-centre</span><b>'+money(t.gl)+'</b></div>'):'')+
          '<div class="cb-tot-card"><span>Blended cost/unit</span><b>'+(t.cost_per_unit!=null?money(t.cost_per_unit):"—")+'</b></div>'+
          '<div class="cb-tot-card"><span>Worker-days</span><b>'+fmt(t.worker_days)+'</b></div>';
      }
      var mode=(el("cc-color")&&el("cc-color").value)||"spend";
      ccTreemap(CCDATA.blocks, mode, t.labour, t.median_cost_per_unit);
      renderCcTable();
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load cost centres.</div>'; });
  }
  function wireCostCentre(){
    ["cc-q"].forEach(function(id){ var e=el(id); if(e) e.oninput=debounce(loadCostCentre,300); });
    ["cc-farm","cc-from","cc-to","cc-group"].forEach(function(id){ var e=el(id); if(e) e.onchange=loadCostCentre; });
    var clr=el("cc-clear"); if(clr) clr.onclick=function(){ ["cc-q","cc-from","cc-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); var f=el("cc-farm"); if(f) f.value=""; loadCostCentre(); };
    var col=el("cc-color"); if(col) col.onchange=function(){ ccTreemap(CCDATA.blocks, col.value, (CCDATA.totals||{}).labour, (CCDATA.totals||{}).median_cost_per_unit); };
    var tabs=el("cc-tabs");
    if(tabs){ tabs.querySelectorAll("button").forEach(function(b){ b.onclick=function(){ tabs.querySelectorAll("button").forEach(function(x){ x.classList.remove("on"); }); b.classList.add("on"); CCDATA.view=b.getAttribute("data-ccview"); renderCcTable(); }; }); }
    loadCostCentre();
  }

  function wireCost(){
    var tabs=el("cb-tabs");
    if(tabs){
      tabs.querySelectorAll("button").forEach(function(b){
        b.onclick=function(){
          tabs.querySelectorAll("button").forEach(function(x){ x.classList.remove("on"); });
          b.classList.add("on");
          CB.group=b.getAttribute("data-cg");
          loadCost();
        };
      });
    }
    ["cb-q","cb-task"].forEach(function(id){ var e=el(id); if(e) e.oninput=debounce(loadCost,300); });
    ["cb-farm","cb-from","cb-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=loadCost; });
    var clr=el("cb-clear"); if(clr) clr.onclick=function(){ ["cb-q","cb-task","cb-from","cb-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); var f=el("cb-farm"); if(f) f.value=""; loadCost(); };
    loadCost();
  }

  function wirePex(){
    var tabs=el("pex-tabs");
    if(tabs){
      tabs.querySelectorAll("button").forEach(function(b){
        b.onclick=function(){
          tabs.querySelectorAll("button").forEach(function(x){ x.classList.remove("on"); });
          b.classList.add("on");
          PEX.stage=b.getAttribute("data-ps");
          setStates();
          loadPex();
        };
      });
    }
    ["pex-q","pex-task","pex-block"].forEach(function(id){ var e=el(id); if(e) e.oninput=debounce(loadPex,300); });
    ["pex-farm","pex-state","pex-life","pex-from","pex-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=loadPex; });
    var clr=el("pex-clear"); if(clr) clr.onclick=function(){ ["pex-q","pex-task","pex-block","pex-from","pex-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); ["pex-farm","pex-state","pex-life"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); loadPex(); };
    var modal=el("pex-modal");
    if(modal){
      modal.querySelector(".pex-back").onclick=function(){ modal.classList.remove("on"); };
      modal.querySelector(".pex-x").onclick=function(){ modal.classList.remove("on"); };
    }
    setStates();
    loadPex();
  }
  function debounce(fn,ms){ var t; return function(){ clearTimeout(t); t=setTimeout(fn,ms); }; }

  function loadSubs(){
    var box=el("wm-subs"); if(!box) return;
    call({action:"substitutions"}).then(function(d){
      SUBS_ROWS = d.subs||[];
      // populate the farm filter from the data (once), preserving any current choice
      var fsel=el("subs-farm");
      if(fsel){
        var keep=fsel.value;
        var farms={};
        SUBS_ROWS.forEach(function(r){ if(r.farm) farms[r.farm]=1; });
        fsel.innerHTML='<option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option>';
        Object.keys(farms).sort().forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
        fsel.value=keep||"";
        fsel.onchange=renderSubs;
      }
      renderSubs();
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load substitutions.</div>'; });
  }
  function renderSubs(){
    var box=el("wm-subs"); if(!box) return;
    var ffarm=(el("subs-farm")&&el("subs-farm").value)||"";
    var rows=(SUBS_ROWS||[]).filter(function(r){ return !ffarm || r.farm===ffarm; });
    if(!rows.length){ box.innerHTML='<div class="empty">'+(ffarm?("No crew movements for "+esc(ffarm)+"."):"No crew movements yet.")+'</div>'; return; }
    var h='<table><thead><tr><th>Event</th><th>Plan</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>Task</th><th>Worker left</th><th class="n">Last day</th><th>Worker joined</th><th class="n">Joined on</th><th class="n">Days done</th><th class="n">Qty done</th><th class="n">Pay earned</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var kind=r.kind||(r.rep_name?"Swap":"Left");
      var kindTag=kind==="Joined"?'<span class="tag" style="background:rgba(10,122,67,.12);color:#0a7a43;border-color:transparent">Joined</span>'
        :kind==="Swap"?'<span class="tag" style="background:rgba(37,99,235,.10);color:#2563eb;border-color:transparent">Swap</span>'
        :kind==="Released"?'<span class="tag" style="background:rgba(160,96,0,.12);color:#a06000;border-color:transparent" title="The plan was closed early — the whole remaining crew was released on the close date; days worked stay paid">Released &middot; plan closed</span>'
        :'<span class="tag hot">Left</span>';
      var leftCell = r.left_emp
        ? '<a href="#" class="subs-emplink" data-emp="'+esc(r.left_emp)+'" style="text-decoration:line-through;color:#999">'+esc(r.left_name||r.left_emp)+'</a>'
        : '<span style="color:var(--mute)">— added to crew</span>';
      var repShared = r.rep_shared ? ' <span style="font-size:8.5px;color:var(--mute)" title="This person joined the crew after the leaver — they may follow several leavers, not a one-for-one swap">(joined crew)</span>' : '';
      var repCell = r.rep_name
        ? (r.rep_emp
            ? '<a href="#" class="subs-emplink" data-emp="'+esc(r.rep_emp)+'" style="color:#0a7a43;font-weight:600'+(r.rep_shared?';opacity:.75':'')+'">'+esc(r.rep_name)+'</a>'+repShared
            : '<span style="color:#0a7a43;font-weight:600">'+esc(r.rep_name)+'</span>'+repShared)
        : '—';
      h+='<tr>'+
         '<td>'+kindTag+'</td>'+
         '<td>'+esc(r.plan)+'</td>'+
         '<td>'+esc(r.farm)+'</td>'+
         '<td>'+esc(taskName(r.task))+taskStdSub(r.task)+'</td>'+
         '<td>'+leftCell+'</td>'+
         '<td class="n">'+esc(r.left_date||"—")+'</td>'+
         '<td>'+repCell+'</td>'+
         '<td class="n">'+esc(r.rep_start||"—")+'</td>'+
         '<td class="n m">'+fmt(r.left_days)+'</td>'+
         '<td class="n m">'+fmt(r.left_qty)+'</td>'+
         '<td class="n m">'+fmt(r.left_pay)+'</td>'+
         '</tr>';
    });
    h+='</tbody></table>';
    box.innerHTML=h;
    box.querySelectorAll(".subs-emplink").forEach(function(lnk){
      lnk.onclick=function(ev){ ev.preventDefault(); ev.stopPropagation(); var e=lnk.getAttribute("data-emp"); if(e) openEmpModal(e); };
    });
  }

  function initCalPicker(){
    var sel=el("wm-cal-pick"); if(!sel) return;
    call({action:"burndown"}).then(function(d){
      var rows=d.plans||[];
      sel.innerHTML='<option value="">— select a plan —</option>';
      rows.forEach(function(r){
        var o=document.createElement("option");
        o.value=r.name;
        o.textContent=r.name+" · "+r.farm+" · "+r.task+" ("+fmt(r.pct,0)+"%)";
        sel.appendChild(o);
      });
      sel.onchange=function(){ loadCal(this.value); };
      var pick=""; for(var i=0;i<rows.length;i++){ if((rows[i].fulfilled||0)>0){ pick=rows[i].name; break; } }
      if(!pick && rows.length) pick=rows[0].name;
      if(pick){ sel.value=pick; loadCal(pick); }
    });
  }
  function loadCal(name){
    var box=el("wm-cal-box"); if(!box) return;
    if(!name){ box.innerHTML=""; return; }
    box.innerHTML='<div class="empty">Loading calendar…</div>';
    call({action:"plan_calendar",planner:name}).then(function(m){
      box.innerHTML=buildCalendar(m.plan||{}, m.days||{});
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load calendar.</div>'; });
  }
  function buildCalendar(plan, days){
    var from=plan.from_date, to=plan.to_date;
    if(!from||!to) return '<div class="empty">No period set on this plan.</div>';
    var uom=plan.uom||"";
    var start=new Date(from+"T00:00:00"), end=new Date(to+"T00:00:00");
    var monthsHtml="", totalQty=0, totalPay=0, activeDays=0;
    var cur=new Date(start.getFullYear(),start.getMonth(),1);
    var last=new Date(end.getFullYear(),end.getMonth(),1);
    while(cur<=last){ monthsHtml+=renderMonth(cur.getFullYear(),cur.getMonth(),start,end,days,uom); cur=new Date(cur.getFullYear(),cur.getMonth()+1,1); }
    Object.keys(days).forEach(function(k){ totalQty+=cflt(days[k].qty); totalPay+=cflt(days[k].pay); activeDays+=1; });
    var head='<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:2px 0 12px;font-size:11px;color:#444">'+
      '<span><i style="display:inline-block;width:11px;height:11px;background:#0a0a0a;vertical-align:middle;margin-right:5px"></i>work logged</span>'+
      '<span><i style="display:inline-block;width:11px;height:11px;background:#fafafa;border:1px solid #e4e4e4;vertical-align:middle;margin-right:5px"></i>in period, none</span>'+
      '<span style="margin-left:auto;font-weight:600">Plan: <b>'+fmt(plan.person_days)+'</b> mandays · <b>'+fmt(plan.total_hours)+'</b> h · Period total: <b>'+fmt(totalQty)+' '+uom+'</b> · <b>KES '+fmt(totalPay)+'</b> · '+activeDays+' active day'+(activeDays===1?'':'s')+'</span></div>';
    return head+'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px">'+monthsHtml+'</div>';
  }
  function renderMonth(year,month,start,end,days,uom){
    var mn=["January","February","March","April","May","June","July","August","September","October","November","December"];
    var first=new Date(year,month,1), startDow=first.getDay(), dim=new Date(year,month+1,0).getDate();
    var h='<div><div style="font-size:12px;font-weight:700;margin-bottom:6px">'+mn[month]+' '+year+'</div>'+
      '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px">';
    ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].forEach(function(d){ h+='<div style="font-size:9px;letter-spacing:.06em;text-transform:uppercase;color:#999;font-weight:600;text-align:center;padding:2px 0">'+d+'</div>'; });
    for(var b=0;b<startDow;b++) h+='<div></div>';
    for(var day=1;day<=dim;day++){
      var dt=new Date(year,month,day);
      var iso=dt.getFullYear()+"-"+cpad(dt.getMonth()+1)+"-"+cpad(day);
      var inP=(dt>=cstrip(start)&&dt<=cstrip(end));
      h+=cellHtml(day,inP,days[iso],uom);
    }
    return h+'</div></div>';
  }
  function cellHtml(day,inP,rec,uom){
    if(!inP) return '<div style="min-height:56px;border:1px dashed #eee;padding:4px;border-radius:2px;opacity:.4"><div style="font-size:10px;color:#bbb">'+day+'</div></div>';
    if(rec&&cflt(rec.qty)>0) return '<div style="min-height:56px;border:1px solid #0a0a0a;background:#0a0a0a;color:#fff;padding:4px 5px;border-radius:2px">'+
      '<div style="font-size:10px;font-weight:700;opacity:.7">'+day+'</div>'+
      '<div style="font-size:12px;font-weight:700;margin-top:2px;line-height:1.15">'+fmt(rec.qty)+'<span style="font-size:8px;font-weight:500;opacity:.7"> '+uom+'</span></div>'+
      '<div style="font-size:9px;opacity:.85;margin-top:1px">'+fmt(rec.workers)+' wk · '+ckfmt(rec.pay)+'</div></div>';
    return '<div style="min-height:56px;border:1px solid #e4e4e4;padding:4px 5px;border-radius:2px;background:#fafafa"><div style="font-size:10px;color:#999;font-weight:600">'+day+'</div></div>';
  }
  function cpad(n){ return (n<10?"0":"")+n; }
  function cstrip(d){ return new Date(d.getFullYear(),d.getMonth(),d.getDate()); }
  function cflt(n){ n=parseFloat(n); return isNaN(n)?0:n; }
  function ckfmt(n){ n=cflt(n); if(n>=1000) return "KES "+(n/1000).toLocaleString("en-KE",{maximumFractionDigits:1})+"k"; return "KES "+fmt(n); }

  // ============ ACTION QUEUES (one card, mini tabs) ============
  var QT={tab:"plans"};
  function initQueues(D){
    var defs=[
      ["plans","Plans → farm manager",(D.plan_pending||[]).length],
      ["asg","Assignments → HR head",(D.asg_pending||[]).length],
      ["act","Actuals in approval",(D.act_pending||[]).length],
      ["pay","Payments → accounts",(D.pay_pending_list||[]).length]
    ];
    var host=el("wm-q-tabs"); if(!host) return;
    host.innerHTML="";
    defs.forEach(function(t){
      var b=document.createElement("button");
      b.type="button"; b.className="subtab"+(QT.tab===t[0]?" on":"");
      b.setAttribute("data-q",t[0]);
      b.innerHTML=t[1]+' <span style="font-variant-numeric:tabular-nums;opacity:.75">· '+fmt(t[2])+'</span>';
      b.onclick=function(){ QT.tab=t[0];
        host.querySelectorAll(".subtab").forEach(function(x){ x.classList.toggle("on", x.getAttribute("data-q")===t[0]); });
        drawQueue(D); };
      host.appendChild(b);
    });
    drawQueue(D);
  }
  function qTable(rows, heads, cells){
    if(!rows.length) return '<div class="empty">Nothing waiting here — queue is clear.</div>';
    var h='<table><thead><tr>';
    heads.forEach(function(x){ h+='<th'+(x[1]?' class="n"':'')+'>'+x[0]+'</th>'; });
    h+='</tr></thead><tbody>';
    rows.forEach(function(r){ h+='<tr>'+cells(r)+'</tr>'; });
    return h+'</tbody></table>';
  }
  function drawQueue(D){
    var box=el("wm-q-body"); if(!box) return;
    if(QT.tab==="plans"){
      box.innerHTML=qTable(D.plan_pending||[],
        [["Ref"],[esc(TX("top_singular","Farm"))],[esc(TX("unit_singular","Block"))],["Task"],["People/day",1],["Cost KES",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(lbl(r.block_section)||"—")+'</td><td>'+esc(taskName(r.task)||"—")+taskStdSub(r.task)+'</td><td class="n m">'+fmt(r.people_per_day)+'</td><td class="n m">'+fmt(r.total_cost)+'</td>'; });
    } else if(QT.tab==="asg"){
      box.innerHTML=qTable(D.asg_pending||[],
        [["Ref"],[esc(TX("top_singular","Farm"))],["Task"],["Planned",1],["Assigned",1],["Variance",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(taskName(r.task)||"—")+taskStdSub(r.task)+'</td><td class="n m">'+fmt(r.planned_people)+'</td><td class="n m">'+fmt(r.assigned_count)+'</td><td class="n m">'+fmt(r.variance)+'</td>'; });
    } else if(QT.tab==="act"){
      box.innerHTML=qTable(D.act_pending||[],
        [["Ref"],[esc(TX("top_singular","Farm"))],["Task"],["Stage"],["Pay KES",1]],
        function(r){ var st=r.workflow_state==="Pending GM"?'<span class="tag hot">GM</span>':'<span class="tag">HR</span>';
          return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(taskName(r.task)||"—")+taskStdSub(r.task)+'</td><td>'+st+'</td><td class="n m">'+fmt(r.total_payment)+'</td>'; });
    } else {
      box.innerHTML=qTable(D.pay_pending_list||[],
        [["Ref"],["Run"],["Workers",1],["Total KES",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.run_title||"—")+'</td><td class="n m">'+fmt(r.total_workers)+'</td><td class="n m">'+fmt(r.amount)+'</td>'; });
    }
  }

  // ============ DELIVERY TIMELINE (plans vs assignments vs actuals) ============
  var TL={measure:"qty", data:null};
  function initTimeline(){
    var ap=el("wm-tl-apply"); if(!ap) return;
    if(!el("wm-tl-from").value){
      var d=new Date(); d.setDate(d.getDate()-41);
      el("wm-tl-from").value=d.toISOString().slice(0,10);
    }
    if(!el("wm-tl-to").value) el("wm-tl-to").value=new Date().toISOString().slice(0,10);
    ap.onclick=loadTimeline;
    el("wm-tl-farm").onchange=loadTimeline;
    el("wm-tl-measure").querySelectorAll("button").forEach(function(b){
      b.onclick=function(){
        TL.measure=b.getAttribute("data-m");
        el("wm-tl-measure").querySelectorAll("button").forEach(function(x){ x.classList.toggle("on", x===b); });
        renderTimeline();
      };
    });
    loadTimeline();
  }
  function loadTimeline(){
    var box=el("wm-tl-chart"); if(!box) return;
    box.innerHTML='<div class="empty">Loading timeline…</div>';
    call({action:"timeline", farm:el("wm-tl-farm").value||"",
          from_date:el("wm-tl-from").value||"", to_date:el("wm-tl-to").value||""})
      .then(function(d){
        if(d.error){ box.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
        TL.data=d;
        var fs=el("wm-tl-farm");
        if(fs && fs.options.length<=1 && (d.farms||[]).length){
          (d.farms||[]).forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); });
        }
        renderTimeline();
      })
      .catch(function(e){ box.innerHTML='<div class="empty">Could not load the timeline: '+esc(e.message)+'</div>'; });
  }
  function tlShort(iso){
    var d=new Date(iso+"T00:00:00"); if(isNaN(d)) return iso;
    return d.getDate()+" "+["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()];
  }
  function tlNum(v){
    if(v>=1e6) return (v/1e6).toLocaleString("en-KE",{maximumFractionDigits:1})+"M";
    if(v>=1e3) return (v/1e3).toLocaleString("en-KE",{maximumFractionDigits:1})+"k";
    return fmt(v);
  }
  function renderTimeline(){
    var box=el("wm-tl-chart"); if(!box||!TL.data) return;
    var days=TL.data.days||[];
    var m=TL.measure;
    var S=[
      {key:"planned_"+m, name:"Planned", color:"#a06000", dash:"6 5"},
      {key:"assigned_"+m,name:"Assigned",color:"#2563eb", dash:""},
      {key:"actual_"+m,  name:"Actual",  color:"#0a7a43", dash:"", area:1}
    ];
    var max=0;
    days.forEach(function(r){ S.forEach(function(sr){ var v=Number(r[sr.key])||0; if(v>max) max=v; }); });
    if(!days.length||max<=0){ box.innerHTML='<div class="empty">No plans or confirmed work in this window.</div>'; return; }
    var W=Math.max(560, box.clientWidth||860), H=280;
    var L=52,R=16,T=14,B=30;
    var iw=W-L-R, ih=H-T-B;
    var ymax=max*1.1;
    function X(i){ return L + (days.length===1?iw/2:(i/(days.length-1))*iw); }
    function Y(v){ return T + ih - (v/ymax)*ih; }
    function path(key){
      var pth="";
      days.forEach(function(r,i){ pth+=(i?"L":"M")+X(i).toFixed(1)+","+Y(Number(r[key])||0).toFixed(1); });
      return pth;
    }
    var g='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block" role="img" aria-label="Daily planned, assigned and actual '+(m==="qty"?"quantity":"value")+'">';
    // gridlines + y labels
    for(var gi=0;gi<=4;gi++){
      var gv=ymax*gi/4, gy=Y(gv);
      g+='<line x1="'+L+'" y1="'+gy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+gy.toFixed(1)+'" stroke="rgba(10,10,10,0.06)" stroke-width="1"/>';
      g+='<text x="'+(L-8)+'" y="'+(gy+3).toFixed(1)+'" text-anchor="end" font-family="Poppins,sans-serif" font-size="9.5" fill="#8a8780">'+tlNum(gv)+'</text>';
    }
    // x ticks (~6)
    var step=Math.max(1,Math.round(days.length/6));
    for(var xi=0;xi<days.length;xi+=step){
      g+='<text x="'+X(xi).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" font-family="Poppins,sans-serif" font-size="9.5" fill="#8a8780">'+tlShort(days[xi].d)+'</text>';
    }
    // actual area fill
    var area="M"+X(0).toFixed(1)+","+Y(0).toFixed(1);
    days.forEach(function(r,i){ area+="L"+X(i).toFixed(1)+","+Y(Number(r["actual_"+m])||0).toFixed(1); });
    area+="L"+X(days.length-1).toFixed(1)+","+Y(0).toFixed(1)+"Z";
    g+='<path d="'+area+'" fill="rgba(10,122,67,0.09)"/>';
    // lines
    S.forEach(function(sr){
      g+='<path d="'+path(sr.key)+'" fill="none" stroke="'+sr.color+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"'+(sr.dash?' stroke-dasharray="'+sr.dash+'"':'')+'/>';
    });
    // direct labels at line ends
    S.forEach(function(sr,si){
      var lv=Number(days[days.length-1][sr.key])||0;
      g+='<text x="'+(W-R)+'" y="'+(Y(lv)+(si===0?-6:si===1?-6:12)).toFixed(1)+'" text-anchor="end" font-family="Poppins,sans-serif" font-size="9.5" font-weight="600" fill="'+sr.color+'">'+sr.name+'</text>';
    });
    // hover layer
    g+='<line id="wm-tl-cross" x1="0" y1="'+T+'" x2="0" y2="'+(T+ih)+'" stroke="rgba(10,10,10,0.35)" stroke-width="1" style="display:none"/>';
    S.forEach(function(sr,si){
      g+='<circle id="wm-tl-dot'+si+'" r="4" fill="'+sr.color+'" stroke="#fff" stroke-width="1.5" style="display:none"/>';
    });
    g+='<rect id="wm-tl-hover" x="'+L+'" y="'+T+'" width="'+iw+'" height="'+ih+'" fill="transparent"/>';
    g+='</svg>';
    var legend='<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--ink);margin:2px 0 8px">'+
      S.map(function(sr){ return '<span style="display:inline-flex;align-items:center;gap:6px"><i style="width:16px;height:0;border-top:2px '+(sr.dash?"dashed":"solid")+' '+sr.color+'"></i>'+sr.name+(sr.name==="Planned"?" (approved plans)":sr.name==="Assigned"?" (staffed share)":" (confirmed)")+'</span>'; }).join("")+
      '</div>';
    box.innerHTML=legend+'<div style="position:relative">'+g+'<div id="wm-tl-tip" style="position:absolute;pointer-events:none;display:none;background:rgba(10,10,10,0.92);color:#fafaf6;border-radius:10px;padding:8px 11px;font-size:11px;line-height:1.5;white-space:nowrap;z-index:5"></div></div>';
    // wire hover
    var svg=box.querySelector("svg"), hov=box.querySelector("#wm-tl-hover"),
        cross=box.querySelector("#wm-tl-cross"), tip=box.querySelector("#wm-tl-tip");
    function pt(evt){
      var r=svg.getBoundingClientRect();
      return (evt.clientX-r.left)*(W/r.width);
    }
    hov.addEventListener("mousemove",function(evt){
      var mx=pt(evt);
      var idx=Math.round((mx-L)/(iw)*(days.length-1));
      idx=Math.max(0,Math.min(days.length-1,idx));
      var r=days[idx], cx=X(idx);
      cross.setAttribute("x1",cx); cross.setAttribute("x2",cx); cross.style.display="";
      S.forEach(function(sr,si){
        var dot=box.querySelector("#wm-tl-dot"+si);
        dot.setAttribute("cx",cx); dot.setAttribute("cy",Y(Number(r[sr.key])||0)); dot.style.display="";
      });
      var unit=m==="qty"?" units":" KES";
      tip.innerHTML='<b>'+tlShort(r.d)+'</b><br>'+
        S.map(function(sr){ return '<span style="color:'+sr.color.replace("#a06000","#e3b25f").replace("#2563eb","#93b8f8").replace("#0a7a43","#7fd0a2")+'">●</span> '+sr.name+': <b>'+fmt(Number(r[sr.key])||0)+'</b>'; }).join("<br>")+
        '<span style="opacity:.6">'+unit+'</span>';
      tip.style.display="";
      var rct=svg.getBoundingClientRect();
      var px=(cx/W)*rct.width;
      tip.style.left=Math.min(px+14, rct.width-190)+"px";
      tip.style.top="18px";
    });
    hov.addEventListener("mouseleave",function(){
      cross.style.display="none"; tip.style.display="none";
      S.forEach(function(sr,si){ box.querySelector("#wm-tl-dot"+si).style.display="none"; });
    });
  }

  // ============ FIELD INTELLIGENCE: efficiency + availability ============
  var FI={data:null};
  function initFieldIntel(){
    var tabs=el("wm-fi-tabs"); if(!tabs) return;
    tabs.querySelectorAll(".subtab").forEach(function(b){
      b.onclick=function(){
        tabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.toggle("on", x===b); });
        var k=b.getAttribute("data-fi");
        el("wm-fi-eff").style.display=(k==="eff")?"":"none";
        el("wm-fi-avail").style.display=(k==="avail")?"":"none";
      };
    });
    var d=new Date(); d.setDate(d.getDate()-30);
    el("wm-fi-from").value=d.toISOString().slice(0,10);
    el("wm-fi-to").value=new Date().toISOString().slice(0,10);
    el("wm-fi-date").value=new Date().toISOString().slice(0,10);
    el("wm-fi-apply").onclick=loadFieldIntel;
    el("wm-fi-avapply").onclick=loadFieldIntel;
    el("wm-fi-search").oninput=function(){ renderFiAvail(); };
    el("wm-fi-farm").onchange=function(){ renderFiAvail(); };
    loadFieldIntel();
  }
  function loadFieldIntel(){
    call({action:"field_intel", from_date:el("wm-fi-from").value||"", to_date:el("wm-fi-to").value||"", date:el("wm-fi-date").value||""})
      .then(function(d){
        if(d.error){ el("wm-fi-eff-body").innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
        FI.data=d;
        var fs=el("wm-fi-farm");
        if(fs && fs.options.length<=1){
          Object.keys((d.available||{}).farms||{}).forEach(function(f){
            var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o);
          });
        }
        renderFiEff();
        renderFiAvail();
      })
      .catch(function(e){ el("wm-fi-eff-body").innerHTML='<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function renderFiEff(){
    var box=el("wm-fi-eff-body"); if(!box||!FI.data) return;
    var farms=FI.data.farms||[], tasks=FI.data.tasks||[];
    if(!farms.length){ box.innerHTML='<div class="empty">No confirmed work in this window.</div>'; return; }
    function hpm(v){ return v>0? fmt(v,3) : "—"; }
    function cph(v){ return v>0? fmt(v,0) : "—"; }
    var h='<div class="tablewrap"><table><thead><tr><th>'+esc(TX("top_singular","Farm"))+'</th><th class="n">Area Ha</th><th class="n">Man-days</th><th class="n">Ha / man-day</th><th class="n">Cost KES</th><th class="n">Cost / Ha</th><th class="n">All-time KES</th></tr></thead><tbody>';
    var ta=0,tm=0,tc=0;
    farms.forEach(function(f){
      ta+=f.area; tm+=f.mandays; tc+=f.cost;
      // an unset area is called out rather than shown as a dash: the two
      // ratios beside it are blank *because* nobody has entered one
      // say where the area came from: entered against the farm, or derived from
      // its blocks. Same number either way, but one of them is somebody's answer.
      var areaCell = f.area>0
        ? fmt(f.area,1)+(f.area_source==="blocks"
            ? '<span title="Summed from this '+esc(TX("top_singular","Farm")).toLowerCase()+"'s "+esc(TX("unit_plural","Blocks")).toLowerCase()+'. Set an area on the '+esc(TX("top_singular","Farm")).toLowerCase()+' to override." style="color:var(--mute);font-size:9px"> \u2248</span>'
            : '')
        : '<span title="No area on this '+esc(TX("top_singular","Farm")).toLowerCase()+' and none on its '+esc(TX("unit_plural","Blocks")).toLowerCase()+'" style="color:#b45309">not set</span>';
      h+='<tr><td><b>'+esc(f.farm)+'</b></td><td class="n m">'+areaCell+'</td><td class="n m">'+fmt(f.mandays)+'</td>'+
         '<td class="n m">'+hpm(f.ha_per_manday)+'</td><td class="n m">'+fmt(f.cost,0)+'</td><td class="n m">'+cph(f.cost_per_ha)+'</td>'+
         '<td class="n m" title="Everything confirmed to date, ignoring the date filter">'+fmt(f.cum_pay||0,0)+'</td></tr>';
    });
    var tcum=0; farms.forEach(function(f){ tcum+=(f.cum_pay||0); });
    h+='</tbody><tfoot><tr><th>TOTAL</th><th class="n">'+(ta>0?fmt(ta,1):"—")+'</th><th class="n">'+fmt(tm)+'</th>'+
       '<th class="n">'+(ta>0&&tm>0?fmt(ta/tm,3):"—")+'</th><th class="n">'+fmt(tc,0)+'</th><th class="n">'+(ta>0?fmt(tc/ta,0):"—")+'</th>'+
       '<th class="n">'+fmt(tcum,0)+'</th></tr></tfoot></table></div>';
    if(tasks.length){
      h+='<div class="sech" style="margin-top:12px;font-size:10px">By task &middot; top by man-days</div>'+
        '<div class="tablewrap" style="max-height:220px;overflow-y:auto"><table><thead><tr><th>Task</th><th class="n">Man-days</th><th class="n">Ha/md</th><th class="n">Cost/Ha</th></tr></thead><tbody>';
      tasks.forEach(function(x){
        h+='<tr><td>'+esc(taskName(x.task))+taskStdSub(x.task)+'</td><td class="n m">'+fmt(x.mandays)+'</td><td class="n m">'+hpm(x.ha_per_manday)+'</td><td class="n m">'+cph(x.cost_per_ha)+'</td></tr>';
      });
      h+='</tbody></table></div>';
    }
    h+='<div class="explain" style="margin-top:8px;font-size:10px"><span>&mdash; means the '+esc(TX("unit_plural","Blocks")).toLowerCase()+' have no area (Ha) captured in the system yet; ask admin to fill <b>Area (Ha)</b> on the '+esc(TX("unit_singular","Block")).toLowerCase()+' records.</span></div>';
    box.innerHTML=h;
  }
  function renderFiAvail(){
    var box=el("wm-fi-avail-body"); if(!box||!FI.data) return;
    var av=FI.data.available||{}, allFarms=av.farms||{};
    var fsel=el("wm-fi-farm")?(el("wm-fi-farm").value||""):"";
    var farms={};
    Object.keys(allFarms).forEach(function(f){ if(!fsel||f===fsel) farms[f]=allFarms[f]; });
    var q=(el("wm-fi-search").value||"").toLowerCase();
    var selTotal=0; Object.keys(farms).forEach(function(f){ selTotal+=farms[f].count; });
    var h='<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">'+
      '<div style="border:1px solid var(--line);border-radius:12px;padding:6px 12px;background:var(--wash)"><b style="font-size:15px">'+fmt(selTotal)+'</b> <span style="font-size:10px;color:var(--mute)">available on '+esc(av.date||"")+(fsel?' at '+esc(fsel):'')+'</span></div>';
    Object.keys(farms).forEach(function(f){
      h+='<div style="border:1px solid var(--line);border-radius:12px;padding:6px 12px"><b>'+esc(f)+'</b> <span style="font-size:11px">'+fmt(farms[f].count)+'</span> <span style="font-size:9.5px;color:#0a7a43">('+fmt(farms[f].present)+' scanned in)</span></div>';
    });
    h+='</div><div style="max-height:300px;overflow-y:auto">';
    var shown=0;
    Object.keys(farms).forEach(function(f){
      var list=(farms[f].list||[]).filter(function(w){ return !q || ((w.name||"")+" "+(w.emp||"")).toLowerCase().indexOf(q)>=0; });
      if(!list.length) return;
      h+='<div class="sech" style="font-size:10px;margin:8px 0 4px">'+esc(f)+' &middot; '+fmt(list.length)+'</div><table><tbody>';
      list.forEach(function(w){
        shown++;
        h+='<tr><td>'+esc(w.name||w.emp)+'</td><td class="m" style="font-size:10px">'+esc(w.emp)+'</td>'+
           '<td style="font-size:10px;color:var(--mute)">'+esc(w.designation||w.etype||"")+'</td>'+
           '<td class="c">'+(w.present?'<span style="color:#0a7a43;font-weight:700;font-size:10px">P</span>':'<span style="color:#a8a59b;font-size:10px">—</span>')+'</td></tr>';
      });
      h+='</tbody></table>';
    });
    h+='</div>';
    if(!shown) h+='<div class="empty">Nobody matches.</div>';
    h+='<div class="explain" style="margin-top:8px;font-size:10px"><span><b>Available</b> = active employee with no live assignment covering the chosen date. <b>P</b> = scanned in that day.</span></div>';
    box.innerHTML=h;
  }

  // ============ OPERATIONS CONTROL (money · bottlenecks · desks) ============
  var OPS={data:null};
  var OPS_C={good:"#0a7a43",mid:"#d9a514",bad:"#b91c1c"};
  function initApproverKpis(){
    var box=el("wm-apk-body"); if(!box) return;
    call({action:"ops_kpis"}).then(function(d){
      if(d.error){ box.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
      OPS.data=d; renderOps();
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load the control board: '+esc(e.message)+'</div>'; });
  }
  function kesShort(v){
    v=Number(v)||0;
    if(v>=1e6) return (v/1e6).toLocaleString("en-KE",{maximumFractionDigits:2})+"M";
    if(v>=1e3) return (v/1e3).toLocaleString("en-KE",{maximumFractionDigits:0})+"k";
    return fmt(v);
  }
  function agePill(d){
    if(d==null||d<=0) return "";
    var c=d>7?OPS_C.bad:(d>=3?"#8a6a10":OPS_C.good);
    var t=d>=1?(Math.round(d*10)/10)+"d":Math.round(d*24)+"h";
    return '<span style="font-size:9.5px;font-weight:700;color:'+c+';border:1px solid '+c+'33;background:'+c+'14;border-radius:999px;padding:1.5px 8px;white-space:nowrap">oldest '+t+'</span>';
  }
  function renderOps(){
    var box=el("wm-apk-body"); if(!box||!OPS.data) return;
    var stages=(OPS.data.stages||[]);
    if(!stages.length){ box.innerHTML='<div class="empty">No approval activity recorded yet.</div>'; return; }
    if(OPS.si==null) OPS.si=0;
    if(!OPS.measure) OPS.measure="n";
    var h='<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:4px">'+
      '<div class="subtabs" id="wm-ops-stages">'+
        stages.map(function(st,i){
          var TL={"Plan approval — Farm Manager":"Plans · FM","Assignment approval — GM":"Assignments · GM",
                  "Actuals — FM sign-off":"Actuals · FM","Actuals — HR sign-off":"Actuals · HR",
                  "Actuals — GM confirmation":"Actuals · GM","Payment — accounts release":"Payment · Accounts"};
          return '<button type="button" class="subtab'+(OPS.si===i?" on":"")+'" data-os="'+i+'">'+esc(TL[st.stage]||st.stage)+
            ' <span style="font-variant-numeric:tabular-nums;opacity:.7">· '+fmt(st.total_n)+'</span></button>';
        }).join("")+
      '</div>'+
      '<span style="flex:1"></span>'+
      '<div id="wm-ops-measure" style="display:inline-flex;gap:2px;background:var(--wash);border:1px solid var(--line);border-radius:999px;padding:3px">'+
        [["n","Sign-offs"],["value","Value KES"],["time","Time taken"]].map(function(m){
          return '<button type="button" data-om="'+m[0]+'" style="font-family:inherit;font-size:11px;font-weight:600;border:0;background:'+(OPS.measure===m[0]?"var(--ink)":"transparent")+';color:'+(OPS.measure===m[0]?"#fff":"var(--mute)")+';padding:6px 14px;border-radius:999px;cursor:pointer">'+m[1]+'</button>';
        }).join("")+
      '</div></div>'+
      '<div id="wm-ops-body" style="margin-top:10px"></div>';
    box.innerHTML=h;
    box.querySelectorAll("[data-os]").forEach(function(b){
      b.onclick=function(){ OPS.si=parseInt(b.getAttribute("data-os"),10);
        box.querySelectorAll("[data-os]").forEach(function(x){ x.classList.toggle("on", x===b); });
        drawOpsStage(); };
    });
    box.querySelectorAll("[data-om]").forEach(function(b){
      b.onclick=function(){ OPS.measure=b.getAttribute("data-om");
        box.querySelectorAll("[data-om]").forEach(function(x){
          var on=x===b; x.style.background=on?"var(--ink)":"transparent"; x.style.color=on?"#fff":"var(--mute)"; });
        drawOpsStage(); };
    });
    drawOpsStage();
  }

  function opsFmtH(hh){
    if(hh==null) return "—";
    if(hh<1) return Math.round(hh*60)+" min";
    if(hh<48) return (Math.round(hh*10)/10)+" h";
    return (Math.round(hh/24*10)/10)+" days";
  }
  function drawOpsStage(){
    var bd=el("wm-ops-body"); if(!bd||!OPS.data) return;
    var st=(OPS.data.stages||[])[OPS.si||0];
    if(!st){ bd.innerHTML='<div class="empty">No stage selected.</div>'; return; }
    var m=OPS.measure||"n";
    var MEAS={
      n:    {label:"Approvals signed (count)", color:"#2a2a26", val:function(a){ return a.n; },      fmtv:function(v){ return fmt(v); }},
      value:{label:"Value approved (KES)",     color:"#0a7a43", val:function(a){ return a.value; }, fmtv:function(v){ return kesShort(v); }},
      time: {label:"Average time to approve",  color:"#a06000", val:function(a){ return a.avg_h==null?0:a.avg_h; }, fmtv:function(v){ return opsFmtH(v); }}
    };
    var M=MEAS[m];
    var aps=(st.approvers||[]).slice();
    if(m==="time") aps=aps.filter(function(a){ return a.avg_h!=null; });
    if(!aps.length){
      bd.innerHTML='<div class="empty">'+(st.total_n?'No timing data recorded at this stage yet.':'Nothing has been signed at this stage yet — this chart fills in as approvals happen.')+'</div>';
      return;
    }
    aps.sort(function(a,b){ return M.val(b)-M.val(a); });
    var max=0; aps.forEach(function(a){ var v=M.val(a); if(v>max) max=v; });
    if(max<=0){ bd.innerHTML='<div class="empty">Nothing to chart for this measure yet.</div>'; return; }

    var n=aps.length;
    var W=1200,L=86,R=26,T=34,iw=W-L-R;
    var slotProbe=iw/n;
    var tight=slotProbe<118;            // many approvers → angled labels, slimmer bars
    var B=tight?118:86;
    var H=460+(tight?32:0);
    var ih=H-T-B;
    var ymax=max*1.12;
    var slot=iw/n, bw=Math.min(tight?64:110,slot*(tight?0.62:0.55));
    function X(i){ return L+slot*(i+0.5); }
    function Y(v){ return T+ih-(v/ymax)*ih; }
    var g='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block" role="img" aria-label="'+esc(st.stage)+' — '+esc(M.label)+' per approver">';
    // gridlines + y ticks
    for(var gi=0;gi<=5;gi++){
      var gv=ymax*gi/5, gy=Y(gv);
      g+='<line x1="'+L+'" y1="'+gy.toFixed(1)+'" x2="'+(W-R)+'" y2="'+gy.toFixed(1)+'" stroke="rgba(10,10,10,.06)"/>'+
         '<text x="'+(L-10)+'" y="'+(gy+4).toFixed(1)+'" text-anchor="end" font-size="11.5" fill="#5a5a52" font-family="Poppins,sans-serif">'+M.fmtv(gv)+'</text>';
    }
    // axes lines
    g+='<line x1="'+L+'" y1="'+T+'" x2="'+L+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    g+='<line x1="'+L+'" y1="'+(T+ih)+'" x2="'+(W-R)+'" y2="'+(T+ih)+'" stroke="#8a8780" stroke-width="1.4"/>';
    // y axis title
    g+='<text transform="rotate(-90)" x="'+(-(T+ih/2))+'" y="20" text-anchor="middle" font-size="12" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">'+esc(M.label)+'</text>';
    // bars
    aps.forEach(function(a,i){
      var v=M.val(a);
      var y=Y(v), hpx=T+ih-y;
      var tip=esc(a.name)+'\n'+fmt(a.n)+' sign-offs · KES '+kesShort(a.value)+' · avg time '+opsFmtH(a.avg_h);
      g+='<rect x="'+(X(i)-bw/2).toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(2,hpx).toFixed(1)+'" rx="5" fill="'+M.color+'"><title>'+tip+'</title></rect>';
      g+='<text x="'+X(i).toFixed(1)+'" y="'+(y-9).toFixed(1)+'" text-anchor="middle" font-size="'+(tight?11:13)+'" font-weight="700" fill="#1a1a18" font-family="Poppins,sans-serif">'+M.fmtv(v)+'</text>';
      if(tight){
        // angled single-line labels so everyone fits, details stay in the hover
        var nm1=(a.name||"");
        if(nm1.length>20) nm1=nm1.slice(0,19)+"…";
        g+='<text transform="rotate(-32 '+X(i).toFixed(1)+' '+(T+ih+14)+')" x="'+X(i).toFixed(1)+'" y="'+(T+ih+14)+'" text-anchor="end" font-size="10.5" font-weight="600" fill="#2a2a26" font-family="Poppins,sans-serif">'+esc(nm1)+'</text>';
        var sub1 = m==="time" ? (fmt(a.n)+' signed') : opsFmtH(a.avg_h);
        if(m==="n") sub1='KES '+kesShort(a.value);
        g+='<text transform="rotate(-32 '+X(i).toFixed(1)+' '+(T+ih+27)+')" x="'+X(i).toFixed(1)+'" y="'+(T+ih+27)+'" text-anchor="end" font-size="8.8" fill="#8a8780" font-family="Poppins,sans-serif">'+sub1+'</text>';
      } else {
        var names=(a.name||"").split(" ");
        var l1=names.slice(0,2).join(" "), l2=names.slice(2).join(" ");
        if(l1.length>16){ l2=(names[1]?names.slice(1).join(" "):""); l1=names[0]; }
        g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+20)+'" text-anchor="middle" font-size="11.5" font-weight="600" fill="#2a2a26" font-family="Poppins,sans-serif">'+esc(l1.length>18?l1.slice(0,17)+"…":l1)+'</text>';
        if(l2) g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+34)+'" text-anchor="middle" font-size="11.5" font-weight="600" fill="#2a2a26" font-family="Poppins,sans-serif">'+esc(l2.length>18?l2.slice(0,17)+"…":l2)+'</text>';
        var sub = m==="n" ? ('KES '+kesShort(a.value)) : m==="value" ? (fmt(a.n)+' sign-offs') : (fmt(a.n)+' sign-offs');
        g+='<text x="'+X(i).toFixed(1)+'" y="'+(T+ih+(l2?48:34))+'" text-anchor="middle" font-size="10" fill="#8a8780" font-family="Poppins,sans-serif">'+sub+(m!=="time"&&a.avg_h!=null?' · '+opsFmtH(a.avg_h):'')+'</text>';
      }
    });
    // x axis title
    g+='<text x="'+(L+iw/2)+'" y="'+(H-8)+'" text-anchor="middle" font-size="12" font-weight="600" fill="#5a5a52" font-family="Poppins,sans-serif">Approver</text>';
    g+='</svg>';
    var head='<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12px;margin-bottom:4px">'+
      '<span><b>'+esc(st.stage)+'</b> — '+fmt(st.total_n)+' approvals · KES '+kesShort(st.total_v)+' in the last 12 weeks</span>'+
      '<span style="color:var(--mute)">hover a bar for all three figures</span></div>';
    bd.innerHTML=head+g;
  }

  // A CSV rather than a real .xlsx: it opens straight into Excel and needs no
  // library, where a true workbook would mean lazy-loading XLSX the way the
  // payment screen does. Say so if you want the workbook instead.
  function load(){
    el("wm-body").innerHTML=skeleton();
    call({action:"dash"}).then(function(D){
      if(D.error){ el("wm-body").innerHTML='<div class="err">Error: '+esc(D.error)+'</div>'; return; }
      render(D);
      wirePex();
      wireCostCentre();
      loadSubs();
    }).catch(function(e){
      el("wm-body").innerHTML='<div class="err">Could not load dashboard: '+esc(e&&e.message?e.message:e)+' &mdash; <a href="#" onclick="location.reload();return false;">retry</a></div>';
    });
  }
  function boot(){
    var rb=el("wm-refresh"); if(rb) rb.onclick=function(){ load(); toast("Refreshed"); };
    // Fetched before the first render so tables draw subjects rather than
    // docnames, but never blocking: a failure here costs readable task names on
    // one screen, and a dashboard that will not load at all costs everything.
    // taskName() falls back to the docname, which is exactly the old behaviour.
    call({action:"task_names"}).then(function(d){
      TASK_NAMES=(d && d.task_names) || {};
      TASK_STD=(d && d.task_standards) || {};
    }).catch(function(){}).then(load, load);
  }
  // No window.frappe check here. This page reads only -- every call is a
  // cookie-authenticated GET with no CSRF token to fetch -- and the route already
  // refuses Guest server-side. The old guard ran the instant the script loaded,
  // which on the app's portal route is before frappe's web bundle has defined
  // window.frappe, so it blanked the whole dashboard and told the reader to open a
  // page they already had open. Nothing else on these pages hit this: the write
  // pages read frappe.csrf_token on click, long after the bundle has landed.
  if(el("wm-body")) boot(); else document.addEventListener("DOMContentLoaded", boot);
})();
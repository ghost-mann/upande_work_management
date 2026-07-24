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
      // KPI cards (Worker assignments tracker) — render as a wrapping row of cards, not stacked text
      ".etkpis{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 14px}"+
      ".etk{flex:1 1 120px;min-width:110px;border:1px solid #e4e4e4;border-radius:6px;padding:10px 12px;background:#fafafa}"+
      ".etk-k{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#777;font-weight:600;margin-bottom:4px}"+
      ".etk-v{font-size:20px;font-weight:700;color:#0a0a0a;line-height:1.1}"+
      ".etk.warn{border-color:#e0b44a;background:#fff9ec}.etk.warn .etk-v{color:#a06000}"+
      ".etk.bad{border-color:#e0b4b4;background:#fff6f6}.etk.bad .etk-v{color:#b91c1c}"+
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
      // worker-timeline summary header + expandable rows
      ".et-summary{margin:10px 0 4px;font-size:12px;color:#555}"+
      ".etw-head{display:flex;align-items:center;gap:8px;cursor:pointer;padding:8px 4px;border-bottom:1px solid #eee}"+
      ".etw-name{font-weight:700}.etw-mini{font-size:11px;color:#777}"+
      ".etw-caret{margin-left:auto;color:#999}"+
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
      .then(function(j){ return j.message||{}; });
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function money(n){ if(n==null||isNaN(n)) return "—"; if(Math.abs(n)>=1000000) return (n/1000000).toLocaleString("en-KE",{maximumFractionDigits:2})+"M"; if(Math.abs(n)>=1000) return (n/1000).toLocaleString("en-KE",{maximumFractionDigits:1})+"k"; return fmt(n); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function el(id){ return document.getElementById(id); }
  function svgEl(t,a,x){ var e=document.createElementNS(NS,t); for(var k in a) e.setAttribute(k,a[k]); if(x!=null) e.textContent=x; return e; }
  function toast(m){ var t=el("wm-toast"); if(!t) return; t.textContent=m; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2000); }
  function kpi(k,v,u){ return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="u">'+(u||"")+'</div></div>'; }
  function dpct(a,b){ a=a||0; b=b||0; if(b<=0) return "—"; return Math.round(a/b*100)+"%"; }
  function stageCard(title, color, rows){
    var body=rows.map(function(r){ return '<div class="sc-row"><span class="sc-k">'+r[0]+'</span><span class="sc-v">'+r[1]+'</span></div>'; }).join("");
    return '<div class="stagecard" style="border-top:3px solid '+color+'">'+
      '<div class="sc-h" style="color:'+color+'">'+title+'</div>'+body+'</div>';
  }
  function farmStrip(rows){
    if(!rows.length) return '<div class="empty">No farm data.</div>';
    var h='<div class="fstrip">';
    rows.forEach(function(r){
      h+='<div class="fs-card">'+
         '<div class="fs-name">'+esc(r.farm)+'</div>'+
         '<div class="fs-big">'+fmt(r.assigned_workers)+'</div><div class="fs-lbl">assigned workers</div>'+
         '<div class="fs-line"><span>Awaiting actuals</span><b>'+fmt(r.awaiting_workers)+'</b></div>'+
         '<div class="fs-line"><span>Confirmed</span><b>'+fmt(r.confirmed_workers)+'</b></div>'+
         '<div class="fs-line"><span>Crew-days of work</span><b>'+fmt(r.crew_days)+'</b></div>'+
         '<div class="fs-line" title="Every plan’s people-per-day added up — counts slots across plans, not distinct people, so it can exceed your workforce."><span>Planned slots/day <i class="qmark">?</i></span><b>'+fmt(r.planned_people)+'</b></div>'+
         '<div class="fs-line"><span>Qty done</span><b>'+fmt(r.actual_qty)+' / '+fmt(r.planned_qty)+'</b></div>'+
         '<div class="fs-line"><span>Payment</span><b>'+money(r.paid_amount)+'</b></div>'+
         '<div class="fs-line"><span>Value</span><b>'+money(r.planned_value)+'</b></div>'+
         '</div>';
    });
    return h+'</div>';
  }

  function skeleton(){
    return '<div class="kpis">'+
      Array(6).join(0).split("0").map(function(){return '<div class="kpi"><div class="sk sk-kpi"></div></div>';}).join("")+
      '</div>'+
      '<div class="sech">Pipeline</div><div class="card"><div class="bd"><div class="sk sk-bar"></div></div></div>'+
      '<div class="sech">Per-farm</div><div class="card"><div class="bd"><div class="sk sk-bar"></div></div></div>';
  }

  function render(D){
    var t=D.totals||{};
    var farms=D.farms||[];
    el("wm-body").innerHTML=
      // ===== TOP: pipeline command center =====
      '<div class="sech">Activity across the pipeline</div>'+
      '<div class="stagegrid">'+
        stageCard("PLANNED","#6b7280",[
          ["Approved plans",fmt(t.approved_plans)],
          ["Crew-days of work",fmt(t.crew_days)],
          ["Sum of daily crews",fmt(t.planned_people)],
          ["Target output",fmt(t.planned_qty)],
          ["Planned value",money(t.planned_value)+" KES"]])+
        stageCard("ASSIGNED","#2563eb",[
          ["Assignments",fmt(t.assignments)],
          ["Assigned workers",fmt(t.assigned_workers)],
          ["Awaiting actuals",fmt(t.awaiting_workers)],
          ["Confirmed",fmt(t.confirmed_workers)]])+
        stageCard("ACTUAL","#0a7a43",[
          ["Confirmed actuals",fmt(t.act_confirmed)],
          ["Qty done",fmt(t.actual_qty)],
          ["Of target",dpct(t.actual_qty,t.planned_qty)],
          ["Confirmed pay",money(t.actual_payment)+" KES"]])+
        stageCard("PAYMENT","#7c3aed",[
          ["Workers paid",fmt(t.workers_paid)],
          ["Payment amount",money(t.paid_amount||t.paid_total)+" KES"],
          ["Unpaid",money(t.unpaid)+" KES"],
          ["Awaiting runs",fmt(t.pay_pending)]])+
      '</div>'+
      '<div class="explain">'+
        '<b>Reading these numbers:</b> '+
        '<span><b>Approved plans</b> — how many work plans are approved.</span>'+
        '<span><b>Crew-days of work</b> — total labour the plans need (workers/day × working days, across every plan). This is the real workload, not a headcount.</span>'+
        '<span><b>Sum of daily crews</b> — every plan’s people-per-day added up. It counts slots across plans, so it is normally far larger than the number of people you employ (that is why it can exceed your workforce).</span>'+
        '<span><b>Planned value</b> — target output × rate across approved plans: what the planned work is worth when fully delivered.</span>'+
        '<span><b>Assigned workers</b> — distinct people actually put on jobs (each counted once).</span>'+
        '<span><b>Awaiting actuals</b> — assigned people whose work has not been recorded/confirmed yet.</span>'+
        '<span><b>Confirmed</b> — people whose work is signed off through FM → HR → GM.</span>'+
      '</div>'+
      // ===== per-farm worker + value summary strip =====
      '<div class="sech">Workers &amp; value per farm</div>'+
      '<div class="card"><div class="bd" id="wm-farmstrip">'+farmStrip(farms)+'</div></div>'+
      // ===== approval speed: how long each sign-off step takes =====
      '<div class="sech">Operations control &mdash; money, bottlenecks &amp; desks</div>'+
      '<div class="card"><div class="hd"><h3>Where the money is &mdash; and who moves it</h3><div class="cap">every shilling in the pipeline right now, how long work takes to become pay, and what each approver cleared &middot; last 12 weeks</div></div>'+
        '<div class="bd" id="wm-apk-body"><div class="loading">Measuring sign-offs&hellip;</div></div></div>'+
      // ===== trends & analytics tabs =====
      '<div class="sech">Trends &amp; analytics</div>'+
      '<div class="card"><div class="hd"><h3>What the numbers are doing</h3><div class="cap">confirmed work only &middot; last 12 weeks</div></div>'+
        '<div class="bd"><div id="wm-an-tabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px"></div><div id="wm-an-body" style="min-height:180px;color:var(--mute)">Loading charts…</div></div></div>'+
      // ===== pipeline + per-farm comparison (one card, pill tabs) =====
      '<div class="sech">Pipeline &mdash; plan &rarr; assign &rarr; confirm &rarr; pay</div>'+
      '<div class="card"><div class="hd"><h3>Pipeline &amp; per-farm comparison</h3><div class="cap">switch views · every number in one scrollable table</div></div>'+
        '<div class="bd">'+
          '<div class="subtabs" id="wm-combo-tabs">'+
            '<button type="button" class="subtab on" data-ct="funnel">Pipeline</button>'+
            '<button type="button" class="subtab" data-ct="deploy">Deployment</button>'+
            '<button type="button" class="subtab" data-ct="output">Output</button>'+
            '<button type="button" class="subtab" data-ct="money">Money</button>'+
          '</div>'+
          '<div id="wm-combo" style="max-height:420px;overflow:auto"></div>'+
        '</div></div>'+
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
            '<input id="pex-q" placeholder="Search name / task / block…" />'+
            '<select id="pex-farm"><option value="">All farms</option></select>'+
            '<select id="pex-state"><option value="">All states</option></select>'+
            '<select id="pex-life"><option value="">All status</option><option value="planned">Planned</option><option value="assigned">Assigned</option><option value="done">Done</option><option value="paid">Paid</option><option value="closed">Closed</option></select>'+
            '<input id="pex-task" placeholder="Task" />'+
            '<input id="pex-block" placeholder="Block" />'+
            '<label>From <input type="date" id="pex-from" /></label>'+
            '<label>To <input type="date" id="pex-to" /></label>'+
            '<button id="pex-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="pex-list" style="max-height:420px;overflow:auto;border-top:1px solid #eee">Loading&hellip;</div>'+
        '</div></div>'+
      '<div id="pex-modal" class="pex-modal"><div class="pex-back"></div><div class="pex-sheet"><button class="pex-x">×</button><div id="pex-modal-body">…</div></div></div>'+
      // ===== COST BREAKDOWN: estimated vs paid, per activity / worker / farm =====
      '<div class="sech">Cost breakdown &mdash; estimated vs paid out</div>'+
      '<div class="card"><div class="hd"><h3>Labour cost</h3><div class="cap">estimated (earned on confirmed actuals) vs actually paid out</div></div>'+
        '<div class="bd">'+
          '<div class="pex-tabs" id="cb-tabs">'+
            '<button data-cg="task" class="on">By activity</button>'+
            '<button data-cg="worker">By worker</button>'+
            '<button data-cg="farm">By farm</button>'+
          '</div>'+
          '<div class="pex-filters" id="cb-filters">'+
            '<input id="cb-q" placeholder="Search…" />'+
            '<select id="cb-farm"><option value="">All farms</option></select>'+
            '<input id="cb-task" placeholder="Task" />'+
            '<label>From <input type="date" id="cb-from" /></label>'+
            '<label>To <input type="date" id="cb-to" /></label>'+
            '<button id="cb-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="cb-totals" class="cb-totals"></div>'+
          '<div id="cb-list" style="max-height:420px;overflow:auto;border-top:1px solid #eee">Loading&hellip;</div>'+
        '</div></div>'+
      // ===== COST CENTRE (BLOCK): which block consumes the most money =====
      '<div class="sech">Cost centres &mdash; spend by block</div>'+
      '<div class="card"><div class="hd"><h3>Block cost centres</h3><div class="cap">running labour cost per block beside GL cost-centre actuals &middot; boxes sized by spend &middot; click a block for its full breakdown</div></div>'+
        '<div class="bd">'+
          '<div class="pex-filters" id="cc-filters">'+
            '<input id="cc-q" placeholder="Search block…" />'+
            '<select id="cc-farm"><option value="">All farms</option></select>'+
            '<label>From <input type="date" id="cc-from" /></label>'+
            '<label>To <input type="date" id="cc-to" /></label>'+
            '<select id="cc-color"><option value="spend">Colour: by spend</option><option value="cpu">Colour: cost per unit</option><option value="farm">Colour: by farm</option></select>'+
            '<button id="cc-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="cc-totals" class="cb-totals"></div>'+
          '<div id="cc-treemap" style="margin:4px 0 14px"></div>'+
          '<div id="cc-tabs" class="pex-tabs" style="margin-bottom:6px">'+
            '<button data-ccview="block" class="on">By block</button>'+
            '<button data-ccview="farm">By farm</button>'+
          '</div>'+
          '<div id="cc-list" style="max-height:520px;overflow:auto;border-top:1px solid #eee">Loading&hellip;</div>'+
        '</div></div>'+
      // ===== EMPLOYEE & ASSIGNMENT TRACKER =====
      '<div class="sech">Employee &amp; assignment tracker &mdash; who is on what</div>'+
      '<div class="card"><div class="hd"><h3>Worker assignments</h3><div class="cap">KPIs, per-worker timeline (active / upcoming / past) &amp; double-booking flags</div></div>'+
        '<div class="bd">'+
          '<div class="pex-filters" id="et-filters">'+
            '<input id="et-q" placeholder="Search worker name or ID…" style="min-width:220px" />'+
            '<select id="et-farm"><option value="">All farms</option></select>'+
            '<select id="et-state"><option value="">All states</option><option>Draft</option><option>Pending Farm Manager</option><option>Pending HR Head</option><option>Pending GM</option><option>Assigned</option><option>Rejected</option></select>'+
            '<input id="et-task" placeholder="Task" />'+
            '<label>From <input type="date" id="et-from" /></label>'+
            '<label>To <input type="date" id="et-to" /></label>'+
            '<button id="et-clear" class="pex-clear">Clear</button>'+
          '</div>'+
          '<div id="et-summary" class="et-summary"></div>'+
          '<div id="et-list"><div class="empty">Type a worker name above to see their assignments.</div></div>'+
        '</div></div>'+
      '<div class="sech">Crew movements &mdash; who left, who joined, who swapped</div>'+
      '<div class="card"><div class="hd"><h3>Substitution history</h3><div class="cap">every mid-period movement &middot; a leaver keeps pay for days worked; Days/Qty/Pay are what that row&rsquo;s worker did on the plan</div></div><div class="bd"><div class="pex-filters" id="subs-filters"><select id="subs-farm"><option value="">All farms</option></select></div><div id="wm-subs" style="max-height:360px;overflow:auto">Loading&hellip;</div></div></div>'+
      '<div class="sech">Delivery timeline &mdash; planned vs staffed vs delivered</div>'+
      '<div class="card"><div class="hd"><h3>Plans, assignments &amp; actuals over time</h3><div class="cap">daily &middot; planned share of approved plans, the staffed share, and confirmed output</div></div>'+
        '<div class="bd">'+
          '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:12px">'+
            '<div><div class="tl-lab">Farm</div><select id="wm-tl-farm" class="tl-in"><option value="">All farms</option></select></div>'+
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
      '<div class="sech">Action queues</div>'+
      '<div class="card"><div class="hd"><h3>Everything waiting on someone</h3><div class="cap">one queue at a time &middot; full-width</div></div>'+
        '<div class="bd">'+
          '<div class="subtabs" id="wm-q-tabs"></div>'+
          '<div id="wm-q-body" style="max-height:420px;overflow:auto;margin-top:10px"></div>'+
        '</div></div>';
    comboInit(D);
    initCharts();
    initQueues(D);
    initTimeline();
    initApproverKpis();
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
    var tabs=[["out","Output by week"],["pay","Pay by week"],["wrk","Workers by week"],["task","Top tasks"]];
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
    call({action:"charts"}).then(function(d){
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
  function anBarsV(rows, key, color, valFn, capText){
    if(!rows||!rows.length) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var max=0; rows.forEach(function(r){ var v=Number(r[key])||0; if(v>max) max=v; });
    if(max<=0) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var peakIdx=-1; rows.forEach(function(r,i){ if((Number(r[key])||0)===max && peakIdx<0) peakIdx=i; });
    var h='<div style="position:relative;padding-top:6px">'+
      '<div style="position:absolute;left:0;right:0;top:6px;bottom:38px;pointer-events:none;background:repeating-linear-gradient(to top,transparent 0,transparent calc(25% - 1px),rgba(10,10,10,0.05) calc(25% - 1px),rgba(10,10,10,0.05) 25%)"></div>'+
      '<div style="display:flex;align-items:flex-end;gap:8px;height:190px;position:relative">';
    rows.forEach(function(r,i){
      var v=Number(r[key])||0;
      var hh=Math.max(3,Math.round(v/max*130));
      var lastOrPeak=(i===rows.length-1)||(i===peakIdx);
      h+='<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:0" title="week of '+esc(r.wstart)+' · '+valFn(v)+'">'+
        '<div style="font-size:9.5px;color:'+(lastOrPeak?"var(--ink)":"var(--mute)")+';font-weight:'+(lastOrPeak?"700":"500")+';font-variant-numeric:tabular-nums;white-space:nowrap;margin-bottom:3px">'+(lastOrPeak?valFn(v):"&nbsp;")+'</div>'+
        '<div style="width:100%;max-width:42px;height:'+hh+'px;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,'+color+' 0%,'+color+'cc 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.25)"></div>'+
        '<div style="width:100%;max-width:42px;height:2px;background:rgba(10,10,10,.18);border-radius:1px;margin-top:2px"></div>'+
        '<div style="font-size:9px;color:var(--mute);margin-top:5px;white-space:nowrap">'+wkLabel(r.wstart)+'</div>'+
      '</div>';
    });
    h+='</div></div>';
    h+='<div style="font-size:10.5px;color:var(--mute);margin-top:10px">'+capText+' Labels mark the peak and the latest week; hover any bar for its value. Weeks start Monday.</div>';
    return h;
  }
  function anBarsH(rows, labelKey, color, valFn, subFn, capText){
    if(!rows||!rows.length) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var max=0, total=0;
    rows.forEach(function(r){ var v=Number(r.pay)||0; if(v>max) max=v; total+=v; });
    if(max<=0) return '<div style="padding:24px;text-align:center;color:var(--mute)">Nothing confirmed in this period yet.</div>';
    var h='';
    rows.forEach(function(r){
      var v=Number(r.pay)||0;
      var w=Math.max(2,Math.round(v/max*100));
      var pct=total>0?Math.round(v/total*100):0;
      h+='<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px" title="'+esc(r[labelKey]||"")+' · '+valFn(v,pct)+'">'+
        '<div style="width:200px;min-width:120px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><b>'+esc(r[labelKey]||"—")+'</b></div>'+
        '<div style="flex:1"><div style="background:rgba(10,10,10,.05);height:12px;border-radius:999px;overflow:hidden"><div style="background:linear-gradient(90deg,'+color+'b3,'+color+');height:12px;width:'+w+'%;border-radius:999px;box-shadow:inset 0 1px 0 rgba(255,255,255,.25)"></div></div></div>'+
        '<div style="width:180px;text-align:right;font-size:11px;font-variant-numeric:tabular-nums">'+valFn(v,pct)+'<br><span style="color:var(--mute);font-size:9.5px">'+subFn(r)+'</span></div>'+
      '</div>';
    });
    h+='<div style="font-size:10.5px;color:var(--mute);margin-top:8px">'+capText+'</div>';
    return h;
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
    if(!AN.data){ bd.innerHTML='<div style="padding:16px;color:var(--mute)">Loading charts…</div>'; return; }
    var wk=AN.data.weekly||[];
    if(AN.tab==="out"){
      bd.innerHTML=anBarsV(wk,"qty","#0a7a43",function(v){return money(v);},
        "How much confirmed work got done each week.");
    } else if(AN.tab==="pay"){
      bd.innerHTML=anBarsV(wk,"pay","#7c3aed",function(v){return money(v);},
        "What that work cost each week in KES.");
    } else if(AN.tab==="wrk"){
      bd.innerHTML=anBarsV(wk,"workers","#2563eb",function(v){return fmt(v);},
        "How many different people did confirmed work each week.");
    } else if(AN.tab==="task"){
      bd.innerHTML=anBarsH(AN.data.top_tasks||[],"label","#0a7a43",
        function(v,pct){ return "KES "+money(v)+" · "+pct+"%"; },
        function(r){ return money(r.qty)+" units · "+fmt(r.workers)+" people"; },
        "Your 10 biggest tasks by confirmed pay.");
    }
  }

  function farmTable(rows){
    if(!rows.length) return '<div class="empty">No farm data.</div>';
    var h='<table><thead><tr><th>Farm</th><th class="n">Appr</th><th class="n">Planned KES</th><th class="n">Assigned</th><th class="n">Confirmed Pay KES</th><th class="n">Unassigned</th></tr></thead><tbody>';
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
    h+='<table><thead><tr><th>Ref</th><th>Farm</th><th>Task</th><th>Stage</th><th class="n">Pay KES</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var st=r.workflow_state==="Pending GM"?'<span class="tag hot">GM</span>':'<span class="tag">HR</span>';
      h+='<tr><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td>'+st+'</td><td class="n m">'+fmt(r.total_payment)+'</td></tr>';
    });
    return h+'</tbody></table></div></div>';
  }

  function payCard(rows){
    var h='<div class="card"><div class="hd"><h3>Payment runs &rarr; accounts</h3><div class="cap">'+rows.length+'</div></div><div class="bd">';
    if(!rows.length) return h+'<div class="empty">Empty.</div></div></div>';
    h+='<table><thead><tr><th>Ref</th><th>Run</th><th class="n">Workers</th><th class="n">Total KES</th></tr></thead><tbody>';
    rows.forEach(function(r){
      h+='<tr><td>'+esc(r.name)+'</td><td>'+esc(r.run_title)+'</td><td class="n m">'+fmt(r.total_workers)+'</td><td class="n m">'+fmt(r.grand_total)+'</td></tr>';
    });
    return h+'</tbody></table></div></div>';
  }

  var COMBO={tab:"funnel"};
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
      h='<table class="pex"><thead><tr><th>Farm</th><th class="n">Planned slots/day</th><th></th><th class="n">Assigned (people)</th><th></th></tr></thead><tbody>';
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
      h='<table class="pex"><thead><tr><th>Farm</th><th class="n">Target</th><th class="n">Done</th><th class="n">%</th><th>Progress</th></tr></thead><tbody>';
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
      h='<table class="pex"><thead><tr><th>Farm</th><th class="n">Planned</th><th></th><th class="n">Confirmed</th><th></th><th class="n">Paid</th><th></th></tr></thead><tbody>';
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
      h+='<th class="n">Std</th><th>Plan</th><th>Farm</th><th>Block</th><th>Task</th><th>Status</th><th class="n">Target</th><th class="n">People/day</th><th class="n">Value</th><th>Period</th><th>State</th><th>Created</th>';
    } else if(stage==="assignments"){
      h+='<th class="n">Std</th><th>Assignment</th><th>Farm</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th class="n">Cost</th><th>Period</th><th>State</th><th>Created</th>';
    } else if(stage==="actuals"){
      h+='<th class="n">Std</th><th>Actual</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">Workers</th><th class="n">Payment</th><th>State</th><th>Entered by</th><th>Created</th>';
    } else {
      h+='<th>Payment</th><th class="n">Grand total</th><th>Period</th><th>State</th><th>Created</th>';
    }
    h+='</tr></thead><tbody>';
    rows.forEach(function(r){
      var dt = stage==="plans"?"Work Management Planner":(stage==="assignments"?"Work Management Assigner":(stage==="actuals"?"Work Management Actuals":"Work Management Payment"));
      var openId=r.name;
      if(stage==="plans"){
        h+='<tr data-open="'+esc(r.name)+'" data-dt="plan"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td>'+lifePill(r)+'</td><td class="n m">'+fmt(r.quantity)+' '+esc(r.uom||"")+'</td><td class="n m">'+fmt(r.people_per_day)+'</td><td class="n m">'+money(r.total_cost)+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else if(stage==="assignments"){
        h+='<tr data-open="'+esc(r.planner_request||"")+'" data-dt="plan"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td class="n m">'+fmt(r.planned_people)+'</td><td class="n m">'+fmt(r.assigned_count)+'</td><td class="n m">'+money(r.planned_cost)+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else if(stage==="actuals"){
        h+='<tr data-actual="'+esc(r.name)+'"><td class="n m">'+stdFmt(r)+'</td><td><b>'+esc(r.name)+'</b></td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td class="n m">'+fmt(r.total_actual_qty)+'</td><td class="n m">'+fmt(r.payroll_people)+'</td><td class="n m">'+money(r.total_payment)+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+esc(r.entered_by||"—")+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
      } else {
        h+='<tr data-payment="'+esc(r.name)+'"><td><b>'+esc(r.run_title||r.name)+'</b></td><td class="n m">'+money(r.grand_total)+'</td><td>'+esc(r.period_from||"?")+' → '+esc(r.period_to||"?")+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+fmtDT(r.creation)+'</td></tr>';
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
         '<div><span>Farm</span><b>'+esc(p.farm||"—")+'</b></div>'+
         '<div><span>Block</span><b>'+esc(lbl(p.block_section)||"—")+'</b></div>'+
         '<div><span>Task</span><b>'+esc(p.task||"—")+'</b></div>'+
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
             'Salaried crew delivered <b>'+fmt(p.salaried_qty)+' '+esc(p.uom||"")+'</b> worth <b>'+money(salv)+'</b> at no piece-rate cost'+(savedPct>0?(' — '+savedPct+'% of the budget covered by salaried labour'):'')+'. '+
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
        h+='<table class="pex"><thead><tr><th>Run</th><th class="n">Grand total</th><th>Period</th><th>State</th><th>Created</th><th></th></tr></thead><tbody>';
        pays.forEach(function(pm){ h+='<tr><td>'+esc(pm.name)+'</td><td class="n m">'+money(pm.grand_total)+'</td><td>'+esc(pm.period_from||"?")+' → '+esc(pm.period_to||"?")+'</td><td>'+stateTag(pm.workflow_state)+'</td><td>'+fmtDT(pm.creation)+'</td><td>'+deskLink("Work Management Payment",pm.name)+'</td></tr>'; });
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
         '<div><span>Farm</span><b>'+esc(a.farm||"—")+'</b></div>'+
         '<div><span>Block</span><b>'+esc(lbl(a.block_section)||"—")+'</b></div>'+
         '<div><span>Task</span><b>'+esc(a.task||"—")+'</b></div>'+
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
         '<div><span>Farm</span><b>'+esc(p.custom_farm||"—")+'</b></div>'+
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
        h+='<table class="pex"><thead><tr><th>Task</th><th>Farm</th><th>Block</th><th>Period</th><th>State</th><th>Worker</th><th></th></tr></thead><tbody>';
        asg.forEach(function(r){
          var wtag=(r.wstatus==="Left")?'<span class="pex-st" style="background:#b91c1c">left</span>':'<span class="pex-st" style="background:#0a7a43">active</span>';
          h+='<tr><td>'+esc(r.task||"")+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(lbl(r.block_section)||"")+'</td><td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td><td>'+stateTag(r.state)+'</td><td>'+wtag+'</td><td>'+(r.plan?('<a href="#" class="et-planlink" data-plan="'+esc(r.plan)+'">plan ↗</a>'):'')+'</td></tr>';
        });
        h+='</tbody></table>';
      }
      h+='<div class="pex-sec">ACTUALS &mdash; daily work &amp; pay ('+acts.length+')</div>';
      if(!acts.length){ h+='<div class="empty">No actuals recorded.</div>'; }
      else {
        h+='<table class="pex-daily"><thead><tr><th>Date</th><th>Task</th><th>Farm</th><th class="n">Qty</th><th class="n">Amount</th><th>Payroll</th><th>Paid</th><th>State</th></tr></thead><tbody>';
        acts.slice(0,500).forEach(function(r){
          h+='<tr><td>'+esc(r.work_date||"")+'</td><td>'+esc(r.task||"")+'</td><td>'+esc(r.farm||"")+'</td><td class="n">'+fmt(r.qty)+'</td><td class="n">'+money(r.amount)+'</td><td>'+(r.in_payroll?"✓":"")+'</td><td>'+(r.paid?("✓"+(r.payment_ref?(" "+esc(r.payment_ref)):"")):"")+'</td><td>'+stateTag(r.state)+'</td></tr>';
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
         '<div><span>Grand total</span><b>'+money(p.grand_total)+' KES</b></div>'+
         '<div><span>Period</span><b>'+esc(p.period_from||"?")+' → '+esc(p.period_to||"?")+'</b></div>'+
         '<div><span>Run date</span><b>'+esc(p.run_date||"—")+'</b></div>'+
         '<div><span>Company</span><b>'+esc(p.company||"—")+'</b></div>'+
         '<div><span>Actuals in run</span><b>'+fmt(p.total_actuals)+'</b></div>'+
         '<div><span>Workers paid</span><b>'+fmt(p.total_workers)+'</b></div>'+
         '<div><span>Created</span><b>'+fmtDT(p.creation)+'</b></div>'+
         '</div>';
      h+='<div class="pex-trail">'+trail("Prepared by",p.prepared_by,p.run_date)+trail("Accounts approved",p.accounts_approved_by,p.accounts_approval_date)+'</div>';
      h+='<div class="pex-sec">PAYMENT LINES ('+lines.length+')</div>';
      if(!lines.length){ h+='<div class="empty">No payment lines.</div>'; }
      else {
        var tot=0;
        h+='<table class="pex-daily"><thead><tr><th>Worker</th><th>Farm</th><th>Task</th><th class="n">Days</th><th class="n">Qty</th><th class="n">Amount</th></tr></thead><tbody>';
        lines.slice(0,2000).forEach(function(x){ tot+=(x.amount||0); h+='<tr><td>'+esc(x.employee_name||x.employee||"")+'</td><td>'+esc(x.farm||"")+'</td><td>'+esc(x.task||"")+'</td><td class="n m">'+fmt(x.days)+'</td><td class="n m">'+fmt(x.qty)+'</td><td class="n m">'+money(x.amount)+'</td></tr>'; });
        h+='</tbody><tfoot><tr><td><b>Total</b></td><td></td><td></td><td></td><td></td><td class="n m"><b>'+money(tot)+'</b></td></tr></tfoot></table>';
      }
      body.innerHTML=h;
    }).catch(function(e){ body.innerHTML='<div class="empty">Could not load payment.</div>'; });
  }

  function setStates(){
    var stSel=el("pex-state");
    if(!stSel) return;
    var opts={plans:["Draft","Pending Approval","Approved","Rejected"],assignments:["Draft","Pending Farm Manager","Pending HR Head","Pending GM","Assigned","Rejected"],actuals:["Draft","Pending Farm Manager","Pending HR Head","Pending GM","Confirmed","Rejected"],payments:["Draft","Pending Accounts","Paid","Rejected"]};
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
      var head = (CB.group==="worker")?"Worker":((CB.group==="farm")?"Farm":"Activity");
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
  function etState(){
    return {
      q:(el("et-q")||{}).value||"",
      farm:(el("et-farm")||{}).value||"",
      state:(el("et-state")||{}).value||"",
      task:(el("et-task")||{}).value||"",
      from_date:(el("et-from")||{}).value||"",
      to_date:(el("et-to")||{}).value||""
    };
  }
  function etKpi(k,v,cls){ return '<div class="etk'+(cls?(" "+cls):"")+'"><div class="etk-k">'+k+'</div><div class="etk-v">'+v+'</div></div>'; }
  function etTimeSplit(list){
    // split a worker's assignments into active / upcoming / past by today's date
    var t=new Date(); t.setHours(0,0,0,0);
    var buckets={active:[],upcoming:[],past:[]};
    list.forEach(function(r){
      var f=r.from_date?new Date(r.from_date+"T00:00:00"):null;
      var to=r.to_date?new Date(r.to_date+"T00:00:00"):null;
      if(f && to){
        if(to<t) buckets.past.push(r);
        else if(f>t) buckets.upcoming.push(r);
        else buckets.active.push(r);
      } else buckets.active.push(r);
    });
    return buckets;
  }
  function etRowsHtml(rows){
    var h='<table class="pex et-inner"><thead><tr><th>Task</th><th>Farm</th><th>Block</th><th>Period</th><th>State</th><th>Worker</th><th>Plan</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var wtag=(r.wstatus==="Left")?'<span class="pex-st" style="background:#b91c1c">left</span>':'<span class="pex-st" style="background:#0a7a43">active</span>';
      var ov=r.overlap?' <span class="et-ovtag" title="Overlaps another live assignment">⚠ overlap</span>':'';
      h+='<tr'+(r.plan?(' data-open="'+esc(r.plan)+'" data-dt="plan" style="cursor:pointer"'):'')+'>'+
         '<td>'+esc(r.task||"")+ov+'</td>'+
         '<td>'+esc(r.farm||"")+'</td>'+
         '<td>'+esc(lbl(r.block_section)||"")+'</td>'+
         '<td>'+esc(r.from_date||"?")+' → '+esc(r.to_date||"?")+'</td>'+
         '<td>'+stateTag(r.state)+'</td>'+
         '<td>'+wtag+'</td>'+
         '<td>'+(r.plan?('<span class="et-planjump" data-plan="'+esc(r.plan)+'">'+esc(r.plan)+' ↗</span>'):"—")+'</td></tr>';
    });
    return h+'</tbody></table>';
  }
  function loadTracker(){
    var box=el("et-list"); if(!box) return;
    var a=etState();
    if(!a.q && !a.farm && !a.task && !a.state){ box.innerHTML='<div class="empty">Type a worker name (or pick a farm) to see assignments.</div>'; var su=el("et-summary"); if(su) su.innerHTML=""; return; }
    box.innerHTML="Loading…";
    a.action="emp_tracker";
    call(a).then(function(d){
      var fs=el("et-farm");
      if(fs && fs.options.length<=1 && d.farms){ d.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); }); }
      var summ=d.summary||[]; var rows=d.assignments||[]; var k=d.kpis||{};
      // ---- KPI strip ----
      var su=el("et-summary");
      if(su){
        if(rows.length){
          su.innerHTML='<div class="etkpis">'+
            etKpi("Workers",fmt(k.workers))+
            etKpi("Assignments",fmt(k.assignments))+
            etKpi("Farms",fmt(k.farms))+
            etKpi("Tasks",fmt(k.tasks))+
            etKpi("Active slots",fmt(k.active_slots))+
            etKpi("Awaiting approval",fmt(k.pending))+
            etKpi("Rejected",fmt(k.rejected),(k.rejected>0?"warn":""))+
            etKpi("Double-booked",fmt(k.conflict_workers)+(k.conflict_pairs?(" · "+fmt(k.conflict_pairs)+" clash"+(k.conflict_pairs>1?"es":"")):""),(k.conflict_workers>0?"bad":""))+
            '</div>';
        } else su.innerHTML="";
      }
      if(!rows.length){ box.innerHTML='<div class="empty">No assignments found for this search.</div>'; return; }
      // ---- group assignment rows by worker ----
      var byemp={}; var order=[];
      rows.forEach(function(r){ if(!byemp[r.employee]){ byemp[r.employee]=[]; order.push(r.employee); } byemp[r.employee].push(r); });
      // summary lookup for header stats
      var smap={}; summ.forEach(function(g){ smap[g.employee]=g; });
      var h='';
      order.forEach(function(emp,idx){
        var list=byemp[emp]; var g=smap[emp]||{};
        var nm=(list[0].employee_name||emp);
        var conflict=g.has_conflict?'<span class="et-ovtag">⚠ double-booked</span>':'';
        var b=etTimeSplit(list);
        h+='<div class="etw" data-w="'+idx+'">'+
             '<div class="etw-head" data-toggle="'+idx+'">'+
               '<div class="etw-name"><span class="etw-caret" id="etw-caret-'+idx+'">▸</span> '+esc(nm)+' '+conflict+'</div>'+
               '<div class="etw-mini">'+
                 '<span><b>'+fmt(list.length)+'</b> assignments</span>'+
                 '<span><b>'+fmt(b.active.length)+'</b> active</span>'+
                 '<span><b>'+fmt(b.upcoming.length)+'</b> upcoming</span>'+
                 '<span><b>'+fmt(b.past.length)+'</b> past</span>'+
                 '<span><b>'+fmt(g.farm_count||0)+'</b> farms</span>'+
                 '<span><b>'+fmt(g.task_count||0)+'</b> tasks</span>'+
                 '<a href="#" class="et-emplink" data-emp="'+esc(emp)+'">full detail ↗</a>'+
               '</div>'+
             '</div>'+
             '<div class="etw-body" id="etw-body-'+idx+'" style="display:none">'+
               (b.active.length?('<div class="et-tl"><div class="et-tl-h et-tl-active">Active now ('+b.active.length+')</div>'+etRowsHtml(b.active)+'</div>'):'')+
               (b.upcoming.length?('<div class="et-tl"><div class="et-tl-h et-tl-up">Upcoming ('+b.upcoming.length+')</div>'+etRowsHtml(b.upcoming)+'</div>'):'')+
               (b.past.length?('<div class="et-tl"><div class="et-tl-h et-tl-past">Past ('+b.past.length+')</div>'+etRowsHtml(b.past)+'</div>'):'')+
             '</div>'+
           '</div>';
      });
      box.innerHTML=h;
      // wire expand/collapse
      box.querySelectorAll(".etw-head").forEach(function(hd){
        hd.onclick=function(ev){
          if(ev.target && ev.target.classList && ev.target.classList.contains("et-emplink")) return;
          var i=hd.getAttribute("data-toggle");
          var bd=el("etw-body-"+i); var ca=el("etw-caret-"+i);
          if(!bd) return;
          var open=bd.style.display!=="none";
          bd.style.display=open?"none":"block";
          if(ca) ca.textContent=open?"▸":"▾";
        };
      });
      // wire plan jumps + worker links
      box.querySelectorAll(".et-planjump").forEach(function(sp){ sp.onclick=function(ev){ ev.stopPropagation(); openPlanModal(sp.getAttribute("data-plan"),"plan"); }; });
      box.querySelectorAll("tr[data-open]").forEach(function(tr){ tr.onclick=function(){ openPlanModal(tr.getAttribute("data-open"),"plan"); }; });
      box.querySelectorAll(".et-emplink").forEach(function(lnk){ lnk.onclick=function(ev){ ev.preventDefault(); ev.stopPropagation(); openEmpModal(lnk.getAttribute("data-emp")); }; });
      // auto-open the first worker for quick read
      if(order.length){ var fb=el("etw-body-0"), fc=el("etw-caret-0"); if(fb){ fb.style.display="block"; if(fc) fc.textContent="▾"; } }
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load tracker.</div>'; });
  }
  function wireTracker(){
    ["et-q","et-task"].forEach(function(id){ var e=el(id); if(e) e.oninput=debounce(loadTracker,350); });
    ["et-farm","et-state","et-from","et-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=loadTracker; });
    var clr=el("et-clear"); if(clr) clr.onclick=function(){ ["et-q","et-task","et-from","et-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); ["et-farm","et-state"].forEach(function(id){ var e=el(id); if(e) e.value=""; }); loadTracker(); };
  }

  // ===== COST CENTRE (block) =====
  var CC={};
  function ccState(){
    return {
      farm:(el("cc-farm")||{}).value||"",
      from_date:(el("cc-from")||{}).value||"",
      to_date:(el("cc-to")||{}).value||"",
      q:(el("cc-q")||{}).value||""
    };
  }
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
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Colour = cost per unit vs the median block: <span style="color:#0a7a43;font-weight:700">efficient</span> → <span style="color:#b45309;font-weight:700">costly</span> → <span style="color:#be123c;font-weight:700">most costly</span>. Box size = labour spend.</div>';
    } else if(mode==="farm"){
      var leg=''; Object.keys(CC_FARM_COLORS).forEach(function(f){ leg+='<span style="display:inline-block;margin-right:10px"><i style="display:inline-block;width:10px;height:10px;background:'+CC_FARM_COLORS[f]+';vertical-align:middle;margin-right:4px"></i>'+esc(f)+'</span>'; });
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Box size = labour spend. '+leg+'</div>';
    } else {
      h+='<div style="font-size:10px;color:var(--mute);margin-top:6px">Box size &amp; shade = labour spend (darker green = bigger running cost). Click any block to drill in.</div>';
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
    h+='<div class="wm-dsec">Tasks in this block ('+tasks.length+')</div>';
    if(tasks.length){
      h+='<div class="wm-dtscroll"><table class="wm-dtable"><thead><tr><th>Task</th><th class="n">Spend KES</th><th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Workers</th><th class="n">Worker-days</th></tr></thead><tbody>';
      tasks.forEach(function(t){ h+='<tr><td>'+esc(t.label)+'</td><td class="n">'+fmt(t.spend)+'</td><td class="n">'+fmt(t.qty)+'</td><td class="n">'+(t.cost_per_unit!=null?money(t.cost_per_unit):"—")+'</td><td class="n">'+fmt(t.workers)+'</td><td class="n">'+fmt(t.worker_days)+'</td></tr>'; });
      h+='</tbody></table></div>';
    } else { h+='<div class="wm-dload">No tasks.</div>'; }
    // workers table (+ cost/unit)
    h+='<div class="wm-dsec">Workers on this block ('+workers.length+')</div>';
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
    if(CCDATA.view==="farm"){
      var frows=CCDATA.farm_totals||[];
      if(!frows.length){ box.innerHTML='<div class="empty">No data.</div>'; return; }
      var maxF=0; frows.forEach(function(r){ if(r.labour>maxF) maxF=r.labour; });
      var fh='<table class="pex"><thead><tr><th>Farm</th><th class="n">Blocks</th><th class="n">Labour spend</th>'+(t.has_gl?'<th class="n">GL actuals</th>':'')+'<th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Worker-days</th><th>Share</th></tr></thead><tbody>';
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
    if(!rows.length){ box.innerHTML='<div class="empty">No block spend for this filter.</div>'; return; }
    var maxL=0; rows.forEach(function(r){ if(r.labour_spend>maxL) maxL=r.labour_spend; });
    var h='<table class="pex" data-cctable="1"><thead><tr>'+
      '<th>Block (cost centre)</th><th>Farm</th>'+
      '<th class="n">Labour spend</th>'+(t.has_gl?'<th class="n">GL actuals</th><th class="n">Labour %</th>':'')+
      '<th class="n">Qty</th><th class="n">Cost/unit</th><th class="n">Cost/day</th><th class="n">Avg crew</th><th class="n">Days</th><th class="n">Workers</th>'+
      '<th>Trend</th><th>Share</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var w=maxL>0?Math.round(r.labour_spend/maxL*100):0;
      var cpuCol=ccEffColor(r.cost_per_unit, med);
      var glCell = t.has_gl ? ('<td class="n m">'+(r.cost_center?money(r.gl_spend):'<span style="color:#bbb">—</span>')+'</td>'+
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
        tt.innerHTML='<div class="cb-tot-card"><span>Blocks</span><b>'+fmt(t.blocks)+'</b></div>'+
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
    ["cc-farm","cc-from","cc-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=loadCostCentre; });
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
        fsel.innerHTML='<option value="">All farms</option>';
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
    var h='<table><thead><tr><th>Event</th><th>Plan</th><th>Farm</th><th>Task</th><th>Worker left</th><th class="n">Last day</th><th>Worker joined</th><th class="n">Joined on</th><th class="n">Days done</th><th class="n">Qty done</th><th class="n">Pay earned</th></tr></thead><tbody>';
    rows.forEach(function(r){
      var kind=r.kind||(r.rep_name?"Swap":"Left");
      var kindTag=kind==="Joined"?'<span class="tag" style="background:rgba(10,122,67,.12);color:#0a7a43;border-color:transparent">Joined</span>'
        :kind==="Swap"?'<span class="tag" style="background:rgba(37,99,235,.10);color:#2563eb;border-color:transparent">Swap</span>'
        :'<span class="tag hot">Left</span>';
      var leftCell = r.left_emp
        ? '<a href="#" class="subs-emplink" data-emp="'+esc(r.left_emp)+'" style="text-decoration:line-through;color:#999">'+esc(r.left_name||r.left_emp)+'</a>'
        : '<span style="color:var(--mute)">— added to crew</span>';
      var repCell = r.rep_name
        ? (r.rep_emp
            ? '<a href="#" class="subs-emplink" data-emp="'+esc(r.rep_emp)+'" style="color:#0a7a43;font-weight:600">'+esc(r.rep_name)+'</a>'
            : '<span style="color:#0a7a43;font-weight:600">'+esc(r.rep_name)+'</span>')
        : '—';
      h+='<tr>'+
         '<td>'+kindTag+'</td>'+
         '<td>'+esc(r.plan)+'</td>'+
         '<td>'+esc(r.farm)+'</td>'+
         '<td>'+esc(r.task)+'</td>'+
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
        [["Ref"],["Farm"],["Block"],["Task"],["People/day",1],["Cost KES",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(lbl(r.block_section)||"—")+'</td><td>'+esc(r.task||"—")+'</td><td class="n m">'+fmt(r.people_per_day)+'</td><td class="n m">'+fmt(r.total_cost)+'</td>'; });
    } else if(QT.tab==="asg"){
      box.innerHTML=qTable(D.asg_pending||[],
        [["Ref"],["Farm"],["Task"],["Planned",1],["Assigned",1],["Variance",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(r.task||"—")+'</td><td class="n m">'+fmt(r.planned_people)+'</td><td class="n m">'+fmt(r.assigned_count)+'</td><td class="n m">'+fmt(r.variance)+'</td>'; });
    } else if(QT.tab==="act"){
      box.innerHTML=qTable(D.act_pending||[],
        [["Ref"],["Farm"],["Task"],["Stage"],["Pay KES",1]],
        function(r){ var st=r.workflow_state==="Pending GM"?'<span class="tag hot">GM</span>':'<span class="tag">HR</span>';
          return '<td>'+esc(r.name)+'</td><td>'+esc(r.farm||"—")+'</td><td>'+esc(r.task||"—")+'</td><td>'+st+'</td><td class="n m">'+fmt(r.total_payment)+'</td>'; });
    } else {
      box.innerHTML=qTable(D.pay_pending_list||[],
        [["Ref"],["Run"],["Workers",1],["Total KES",1]],
        function(r){ return '<td>'+esc(r.name)+'</td><td>'+esc(r.run_title||"—")+'</td><td class="n m">'+fmt(r.total_workers)+'</td><td class="n m">'+fmt(r.grand_total)+'</td>'; });
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

  function load(){
    el("wm-body").innerHTML=skeleton();
    call({action:"dash"}).then(function(D){
      if(D.error){ el("wm-body").innerHTML='<div class="err">Error: '+esc(D.error)+'</div>'; return; }
      render(D);
      wirePex();
      wireCost();
      wireCostCentre();
      wireTracker();
      loadSubs();
    }).catch(function(e){
      el("wm-body").innerHTML='<div class="err">Could not load dashboard: '+esc(e&&e.message?e.message:e)+' &mdash; <a href="#" onclick="location.reload();return false;">retry</a></div>';
    });
  }
  function boot(){
    var rb=el("wm-refresh"); if(rb) rb.onclick=function(){ load(); toast("Refreshed"); };
    load();
  }
  if(typeof frappe==="undefined"){ var b=el("wm-body"); if(b) b.innerHTML='<div class="err">Open inside Frappe (logged in).</div>'; }
  else { if(el("wm-body")) boot(); else document.addEventListener("DOMContentLoaded", boot); }
})();
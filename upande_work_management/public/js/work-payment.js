(function(){
  "use strict";
  var API = "/api/method/wm_payment";

  // ── shared state ──
  var ST = {
    workers: [],        // current payable list (from pay_workers)
    picked: {},         // employee -> row, selected for the run
    bulk: {},           // employee -> {status, amt, nm} ticked for bulk review/send
    farms: [],          // [{farm, workers, owed}] summary across window
    activeFarms: {},    // farm -> 1 (chip filter); empty = all
    isAccounts: false,
    accCount: 0
  };

  // ── tiny helpers ──
  function el(id){ return document.getElementById(id); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function money(n){ if(n==null||isNaN(n)) return "—"; return "KES "+fmt(n,2); }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function isTW(t){ return (t||"")==="Task Worker"; }

  function toast(msg, kind){
    var t=el("pay-toast"); if(!t) return;
    t.textContent=msg; t.className="toast show"+(kind?(" "+kind):"");
    clearTimeout(t._t); t._t=setTimeout(function(){ t.className="toast"; }, 2600);
  }

  // GET/POST to the single wm_payment endpoint. Writes go as POST with the CSRF token.
  function call(args, isWrite){
    var p=new URLSearchParams();
    for(var k in args){ if(args[k]!=null) p.append(k, args[k]); }
    var opt={ headers:{ "Accept":"application/json" }, credentials:"same-origin" };
    if(isWrite){
      opt.method="POST";
      opt.headers["Content-Type"]="application/x-www-form-urlencoded";
      opt.headers["X-Frappe-CSRF-Token"]=(window.frappe&&window.frappe.csrf_token)||"";
      opt.body=p.toString();
      var url=API;
    } else {
      opt.method="GET";
      var url=API+"?"+p.toString();
    }
    return fetch(url, opt)
      .then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
      .then(function(j){ return j.message||{}; });
  }

  // ── date range (defaults to the current month-to-date) ──
  function todayISO(){ var d=new Date(); return iso(d); }
  function iso(d){ return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0"); }
  function monthStartISO(){ var d=new Date(); return iso(new Date(d.getFullYear(), d.getMonth(), 1)); }
  function range(){
    return { from:(el("pf-from").value||""), to:(el("pf-to").value||"") };
  }

  // ════════════════════════════════════════════════
  //  TAB ROUTING
  // ════════════════════════════════════════════════
  function showTab(name){
    ["build","accounts","mine","audit","insights"].forEach(function(n){
      var p=el("p-"+n); if(p) p.classList.toggle("on", n===name);
    });
    document.querySelectorAll("#pay-tabs button").forEach(function(b){
      b.setAttribute("aria-selected", b.getAttribute("data-tab")===name);
    });
    if(name==="build")    loadPayable();
    if(name==="accounts") loadAccounts();
    if(name==="mine")     loadMine();
    if(name==="audit")    initAudit();
    if(name==="insights") initInsights();
  }

  // ════════════════════════════════════════════════
  //  INSIGHTS / KPIs — who works, who's owed, what the money feeds
  // ════════════════════════════════════════════════
  var INS={inited:false};
  function initInsights(){
    if(!INS.inited){
      INS.inited=true;
      el("ins-from").value=monthStartISO();
      el("ins-to").value=todayISO();
      call({action:"pay_roles"}).then(function(){});
      el("ins-apply").onclick=loadInsights;
    }
    loadInsights();
  }
  function loadInsights(){
    var b=el("ins-body"); b.className="loading"; b.innerHTML="Loading…";
    var args={action:"pay_insights", from_date:el("ins-from").value, to_date:el("ins-to").value};
    var fsel=el("ins-farm");
    if(fsel && fsel.value) args.farm=fsel.value;
    call(args).then(function(d){
      if(d.error){ b.className=""; b.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
      if(fsel && fsel.options.length<=1 && d.farms){
        d.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
        if(args.farm) fsel.value=args.farm;
      }
      var sc=el("ins-scope");
      if(sc) sc.textContent=((d.window&&d.window.farm)||"All farms")+" · "+((d.window&&d.window.from)||"")+" → "+((d.window&&d.window.to)||"");
      renderInsights(d, b);
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load: '+esc(e&&e.message?e.message:e)+'</div>'; });
  }
  function insKpi(k,v,u){ return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="u">'+(u||"")+'</div></div>'; }
  function renderInsights(d, b){
    INS.data=d;
    if(!INS.tab) INS.tab="owed";
    INS.q="";
    var k=d.kpi||{};
    var assigned=d.assigned_workers||0;
    var active=k.active_workers||0;
    var idleN=(d.idle_list||[]).length;
    var util=assigned>0?Math.round(active/assigned*100):null;
    var pool=d.pool_count||0;
    var avail=(d.available_list||[]).length;
    var h='<div class="sech">The workforce</div>';
    h+='<div class="kpis" style="grid-template-columns:repeat(5,1fr)">'+
      insKpi("Workforce", fmt(pool), "active task workers"+((d.window&&d.window.farm)?(" · "+esc(d.window.farm)):"")) +
      insKpi("Available", fmt(avail), "no live assignment — free to deploy")+
      insKpi("Assigned", fmt(assigned), "on live assignments now")+
      insKpi("Working", fmt(active), (util!=null&&util<=100)?(util+"% of assigned confirmed work"):"confirmed work in period")+
      insKpi("Not working", fmt(idleN), "assigned, nothing confirmed yet")+
      insKpi("Mandays", fmt(k.mandays), "confirmed work-days")+
      insKpi("Earned", money(k.earned), "confirmed in period")+
      insKpi("Paid out", money(k.paid_amt), fmt(k.paid_workers)+" people paid")+
      insKpi("Owed", money(k.unpaid_amt), fmt(k.unpaid_workers)+" people waiting")+
      insKpi("Avg / worker", active>0?money((k.earned||0)/active):"—", "earned per active person")+
    '</div>';
    if(util!=null && util>100){
      h+='<div class="note" style="margin:2px 0 6px">Working can exceed Assigned when the period includes confirmed work by people whose assignments have since ended.</div>';
    }
    h+='<div class="sech" style="margin-top:20px">The detail</div>';
    h+='<div id="ins-subtabs" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px"></div>';
    h+='<div style="display:flex;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap">'+
       '<input type="text" id="ins-q" placeholder="Filter by name, farm or activity…" style="max-width:320px">'+
       '<span id="ins-count" style="font-size:10px;color:var(--mute);letter-spacing:.06em;text-transform:uppercase;font-weight:600"></span></div>';
    h+='<div id="ins-tablewrap" style="max-height:460px;overflow:auto;border:1px solid var(--faint)"></div>';
    h+='<div id="ins-note" style="font-size:10.5px;color:var(--mute);margin-top:6px"></div>';
    b.className=""; b.innerHTML=h;
    var q=el("ins-q");
    if(q){ q.oninput=function(){ INS.q=(q.value||"").toLowerCase(); drawInsTab(); }; }
    drawInsTab();
  }
  // sub-tab definitions: key, label, dataset, columns, searchable fields, note
  function insDefs(){
    var d=INS.data||{};
    var k=d.kpi||{};
    return [
      {key:"avail", label:"Available", rows:d.available_list||[],
       note:"Active task workers with no live assignment — free to deploy today.",
       search:["nm","emp","farm","designation"], sort:{c:"nm",dir:1},
       cols:[["Worker","nm",0],["ID","emp",0],["Farm","farm",0],["Designation","designation",0]]},
      {key:"asgd", label:"Assigned", rows:(d.assigned_list||[]).map(function(r){ r.period=(r.latest_from||"")+(r.latest_to?(" → "+r.latest_to):""); return r; }),
       note:"Everyone on a live assignment and the tasks they are on — the deployed workforce right now.",
       search:["nm","emp","farm","task_list"], sort:{c:"assignments",dir:-1},
       cols:[["Worker","nm",0],["Farm","farm",0],["Assignments","assignments",1],["Tasks","task_count",1],["Task detail","task_list",0],["Latest period","period",0]]},
      {key:"owed", label:"Owed money", rows:d.unpaid_list||[],
       note:"Confirmed work not yet paid — build a run from the first tab to clear it. Sorted biggest first; click any column header to re-sort.",
       search:["nm","emp","farm"], sort:{c:"owed",dir:-1},
       cols:[["Worker","nm",0],["Farm","farm",0],["Days","days",1],["Owed (KES)","owed",1],["Earliest unpaid","oldest",0],["Latest","newest",0]]},
      {key:"idle", label:"Not working", rows:d.idle_list||[],
       note:"Assigned to live work but no confirmed output in this period — idle, on other duties, or their actuals are still in approval.",
       search:["nm","emp","farm"], sort:{c:"assignments",dir:-1},
       cols:[["Worker","nm",0],["Farm","farm",0],["Live assignments","assignments",1]]},
      {key:"tasks", label:"Activities", rows:(d.task_costs||[]).map(function(r){
          r.cpu=(r.qty>0)?(r.pay/r.qty):null; return r; }),
       note:"Confirmed labour spend per activity per farm. KES/unit is what each unit of output actually cost — the column that exposes expensive work even when the total looks small.",
       search:["label","farm"], sort:{c:"pay",dir:-1},
       cols:[["Activity","label",0],["Farm","farm",0],["Spend (KES)","pay",1],["Share","share",1],["KES/unit","cpu",1],["Units","qty",1],["People","workers",1],["Mandays","mandays",1]]},
      {key:"top", label:"Top earners", rows:d.top_workers||[],
       note:"Biggest confirmed earners in the period — recognition list and anomaly check in one.",
       search:["nm","emp","farm"], sort:{c:"pay",dir:-1},
       cols:[["Worker","nm",0],["Farm","farm",0],["Days","days",1],["Output","qty",1],["Earned (KES)","pay",1]]}
    ];
  }
  function drawInsTab(){
    var defs=insDefs();
    var def=null;
    defs.forEach(function(x){ if(x.key===INS.tab) def=x; });
    if(!def){ def=defs[0]; INS.tab=def.key; }
    if(!INS.sorts) INS.sorts={};
    if(!INS.sorts[def.key]) INS.sorts[def.key]={c:def.sort.c, dir:def.sort.dir};
    var srt=INS.sorts[def.key];
    // sub-tab bar with live counts
    var bar=el("ins-subtabs");
    if(bar){
      bar.innerHTML="";
      defs.forEach(function(x){
        var on=(x.key===INS.tab);
        var btn=document.createElement("button");
        btn.type="button";
        btn.innerHTML=esc(x.label)+' <span style="opacity:.7">('+fmt(x.rows.length)+')</span>';
        btn.style.cssText="font-family:inherit;font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:6px 13px;cursor:pointer;border-radius:999px;border:1px solid "+(on?"var(--ink)":"var(--line)")+";background:"+(on?"var(--ink)":"#fff")+";color:"+(on?"#fff":"var(--mute)");
        btn.onclick=function(){ INS.tab=x.key; drawInsTab(); };
        bar.appendChild(btn);
      });
    }
    // filter
    var rows=def.rows.slice();
    var qv=INS.q||"";
    if(qv){
      rows=rows.filter(function(r){
        var hit=false;
        def.search.forEach(function(f){ if(String(r[f]||"").toLowerCase().indexOf(qv)>=0) hit=true; });
        return hit;
      });
    }
    // computed share for activities (over the filtered view)
    if(def.key==="tasks"){
      var tot=0; rows.forEach(function(r){ tot+=(r.pay||0); });
      rows.forEach(function(r){ r.share=tot>0?(r.pay/tot*100):0; });
    }
    // sort
    rows.sort(function(a,b){
      var av=a[srt.c], bv=b[srt.c];
      if(av==null&&bv==null) return 0;
      if(av==null) return 1;
      if(bv==null) return -1;
      if(typeof av==="number"||typeof bv==="number") return (Number(av)-Number(bv))*srt.dir;
      return String(av).localeCompare(String(bv))*srt.dir;
    });
    // table
    var wrap=el("ins-tablewrap"); if(!wrap) return;
    if(!rows.length){
      wrap.innerHTML='<div class="empty" style="border:none">'+(qv?"Nothing matches that filter.":"Nothing here for this period — good news on this tab.")+'</div>';
    } else {
      var thStyle="position:sticky;top:0;background:#fff;z-index:1;cursor:pointer;user-select:none;box-shadow:0 1.5px 0 var(--ink)";
      var h='<table style="margin-top:0"><thead><tr>';
      def.cols.forEach(function(c){
        var arrow=(srt.c===c[1])?(srt.dir===1?" ▲":" ▼"):"";
        h+='<th data-sc="'+esc(c[1])+'"'+(c[2]?' class="n"':'')+' style="'+thStyle+'" title="click to sort">'+esc(c[0])+arrow+'</th>';
      });
      h+='</tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr>';
        def.cols.forEach(function(c){
          var v=r[c[1]];
          var txt;
          if(c[1]==="share") txt=(v!=null?Math.round(v)+"%":"—");
          else if(c[1]==="cpu") txt=(v!=null?fmt(v,2):"—");
          else if(c[2]) txt=fmt(v);
          else txt=esc(v==null?"—":v);
          var bold=(c[1]==="nm"||c[1]==="label"||c[1]==="owed"||c[1]==="pay");
          h+='<td'+(c[2]?' class="n m"':'')+'>'+(bold?'<b>'+txt+'</b>':txt)+'</td>';
        });
        h+='</tr>';
      });
      h+='</tbody></table>';
      wrap.innerHTML=h;
      wrap.querySelectorAll("th[data-sc]").forEach(function(th){
        th.onclick=function(){
          var c=th.getAttribute("data-sc");
          if(srt.c===c){ srt.dir=srt.dir*-1; } else { srt.c=c; srt.dir=-1; }
          drawInsTab();
        };
      });
      wrap.scrollTop=0;
    }
    var cnt=el("ins-count");
    if(cnt) cnt.textContent=fmt(rows.length)+" of "+fmt(def.rows.length)+" rows";
    var note=el("ins-note");
    if(note) note.textContent=def.note;
  }

  // ════════════════════════════════════════════════
  //  BUILD A RUN
  // ════════════════════════════════════════════════
  function farmsCSV(){
    var keys=Object.keys(ST.activeFarms);
    return keys.length ? keys.join(",") : "";
  }

  function loadPayable(){
    var r=range();
    var box=el("build-body");
    box.innerHTML='<div class="sk sk-row"></div><div class="sk sk-row"></div><div class="sk sk-row"></div><div class="sk sk-row"></div>';
    // include_all=1 so paid/submitted workers are shown (greyed), giving the clerk
    // a complete picture of the window rather than a list that empties as runs go out.
    call({ action:"pay_workers", farms:farmsCSV(), from_date:r.from, to_date:r.to, include_all:1 })
      .then(function(d){
        ST.workers = d.workers||[];
        ST.farms   = d.farms||[];
        renderFarmChips();
        renderPayable(d);
        renderBuildKpis(d);
      })
      .catch(function(e){
        box.innerHTML='<div class="err">Could not load payable workers: '+esc(e.message)+'. Check the <code>wm_payment</code> server script is enabled.</div>';
      });
  }

  function renderBuildKpis(d){
    var payable=0, toreview=0, reviewed=0, sent=0;
    ST.workers.forEach(function(w){
      if(w.pay_status==="Unpaid"){ toreview+=1; payable+=(w.unpaid_amt||w.owed||0); }
      else if(w.pay_status==="Reviewed"){ reviewed+=1; payable+=(w.unpaid_amt||w.owed||0); }
      else if(w.pay_status==="Sent to accounts"){ sent+=1; }
    });
    el("k-owed").textContent=fmt(payable);
    el("k-toreview").textContent=fmt(toreview);
    el("k-reviewed").textContent=fmt(reviewed);
    el("k-sent").textContent=fmt(sent);
  }

  function renderFarmChips(){
    var host=el("pay-farmchips");
    if(!ST.farms.length){ host.innerHTML=""; return; }
    var h='<div class="fchip allchip'+(Object.keys(ST.activeFarms).length?"":" on")+'" data-farm="">All farms</div>';
    ST.farms.forEach(function(f){
      var on=ST.activeFarms[f.farm]?" on":"";
      h+='<div class="fchip'+on+'" data-farm="'+esc(f.farm)+'">'+esc(f.farm)+
         ' <span class="fc-mini">'+fmt(f.workers)+'w &middot; '+money(f.owed)+'</span></div>';
    });
    host.innerHTML=h;
    host.querySelectorAll(".fchip").forEach(function(chip){
      chip.onclick=function(){
        var farm=chip.getAttribute("data-farm");
        if(farm===""){ ST.activeFarms={}; }
        else if(ST.activeFarms[farm]){ delete ST.activeFarms[farm]; }
        else { ST.activeFarms[farm]=1; }
        loadPayable();
      };
    });
  }

  function passesSearch(w){
    var q=(el("pf-search").value||"").trim().toLowerCase();
    if(!q) return true;
    return ((w.emp_name||"")+" "+(w.emp||"")).toLowerCase().indexOf(q)>=0;
  }

  function renderPayable(d){
    var box=el("build-body");
    var rows=(ST.workers||[]).filter(passesSearch);
    if(!rows.length){
      box.innerHTML='<div class="empty"><b>No workers here</b>No confirmed work matches this window and filter. Widen the dates or clear the farm filter.</div>';
      return;
    }
    var order={"Unpaid":0,"Reviewed":1,"Sent to accounts":2,"Paid":3};
    rows.sort(function(a,b){
      var oa=order[a.pay_status]!=null?order[a.pay_status]:0, ob=order[b.pay_status]!=null?order[b.pay_status]:0;
      if(oa!==ob) return oa-ob;
      return (b.unpaid_amt||b.owed||0)-(a.unpaid_amt||a.owed||0);
    });
    var h='<div class="filters" style="margin-bottom:10px;padding:8px 14px;gap:8px"><span class="hint" id="pw-count">'+
      fmt(rows.length)+' of '+fmt((ST.workers||[]).length)+' workers</span>'+
      '<span class="hint" id="bulk-info" style="font-weight:600;color:var(--ink)"></span><span style="flex:1"></span>'+
      '<button type="button" class="btn good sm" id="bulk-send" style="display:none">Review &amp; send to accounts</button>'+
      '<button type="button" class="btn sm" id="bulk-clear" style="display:none">Clear</button>'+
      '<span class="hint" id="bulk-hint">Tick workers to review &amp; send them to accounts in one go, or open each one for the full check.</span></div>';
    h+='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
      '<th class="c" style="width:34px"><input type="checkbox" id="bulk-all" title="Select every actionable worker shown"></th>'+
      '<th>Worker</th><th>ID</th><th>Farm</th><th>Period worked</th><th class="n">Tasks</th><th class="n">Days</th><th class="n">Qty</th>'+
      '<th class="n">Earned KES</th><th class="n">Paid KES</th><th class="n">Unpaid KES</th><th class="c">Status</th><th class="c">Actions</th></tr></thead><tbody>';
    var tq=0, te=0, tp=0, tu=0;
    rows.forEach(function(w){
      var unpaid=w.unpaid_amt!=null?w.unpaid_amt:w.owed;
      tq+=(w.qty||0); te+=(w.owed||0); tp+=(w.paid_amt||0); tu+=(unpaid||0);
      var acts='<button type="button" class="btn sm" data-review="'+esc(w.emp)+'">Review</button>';
      if(w.pay_status==="Reviewed"){
        acts+=' <button type="button" class="btn good sm" data-send="'+esc(w.emp)+'" data-nm="'+esc(w.emp_name||w.emp)+'" data-amt="'+(unpaid||0)+'">Send to accounts</button>';
      } else if(w.pay_status==="Unpaid"){
        acts+=' <button type="button" class="btn sm" disabled title="Review this worker first — approval unlocks after review" style="opacity:.45">Send to accounts</button>';
      }
      var actionable=(w.pay_status==="Unpaid"||w.pay_status==="Reviewed") && (unpaid||0)>0.001;
      var cb=actionable?
        '<input type="checkbox" class="bpick" data-emp="'+esc(w.emp)+'" data-status="'+esc(w.pay_status)+'" data-amt="'+(unpaid||0)+'" data-nm="'+esc(w.emp_name||w.emp)+'"'+(ST.bulk[w.emp]?" checked":"")+'>':'';
      var runRef=w.run_ref?('<div style="font-size:9px;color:var(--mute);margin-top:2px">'+esc(w.run_ref)+'</div>'):'';
      h+='<tr data-emp="'+esc(w.emp)+'" class="'+(w.pay_status==="Paid"?"notpay":"")+(ST.bulk[w.emp]?" picked":"")+'">'+
        '<td class="c">'+cb+'</td>'+
        '<td><span class="rowlink" data-review="'+esc(w.emp)+'">'+esc(w.emp_name||w.emp)+'</span>'+
        (w.disc_days?' <span class="rowlink" data-wrdisc="'+esc(w.emp)+'" title="'+w.disc_days+' day-row'+(w.disc_days>1?'s':'')+' recorded on marked-Absent days — open the Discrepancies tab" style="color:#b91c1c;font-weight:700;font-size:11px">&#9873;'+w.disc_days+'</span>':'')+
        '</td>'+
        '<td class="m">'+esc(w.emp)+'</td>'+
        '<td>'+esc(w.farm||"—")+'</td>'+
        '<td class="m">'+esc(dshort(w.wfrom))+' &rarr; '+esc(dshort(w.wto))+'</td>'+
        '<td class="n m">'+fmt(w.tasks)+'</td>'+
        '<td class="n m">'+fmt(w.days)+'</td>'+
        '<td class="n m">'+fmt(w.qty)+'</td>'+
        '<td class="n m">'+money(w.owed)+'</td>'+
        '<td class="n m">'+money(w.paid_amt)+'</td>'+
        '<td class="n m">'+money(unpaid)+'</td>'+
        '<td class="c">'+payTag(w.pay_status)+runRef+'</td>'+
        '<td class="c" style="white-space:nowrap">'+acts+'</td></tr>';
    });
    h+='</tbody><tfoot><tr><th colspan="7">TOTAL &middot; '+fmt(rows.length)+' workers</th>'+
       '<th class="n">'+fmt(tq)+'</th><th class="n">'+fmt(te,2)+'</th><th class="n">'+fmt(tp,2)+'</th><th class="n">'+fmt(tu,2)+'</th>'+
       '<th colspan="2"></th></tr></tfoot></table></div></div>';
    h+='<div class="note">Unpaid &rarr; review the worker &middot; Reviewed &rarr; send to accounts &middot; Sent &rarr; accounts releases &middot; Paid. Each send creates a single-worker payment reference automatically; unpaid day-rows can be corrected inside Review. Bulk: tick the workers and hit <b>Review &amp; send to accounts</b> &mdash; each worker still gets their own payment reference.</div>';
    box.innerHTML=h;
    box.querySelectorAll("[data-review]").forEach(function(a){
      a.onclick=function(){ openWorkerReview(a.getAttribute("data-review"), payWindow()); };
    });
    box.querySelectorAll("[data-send]").forEach(function(b){
      b.onclick=function(){
        approveWorker(b.getAttribute("data-send"), b.getAttribute("data-nm"),
          parseFloat(b.getAttribute("data-amt"))||0, payWindow());
      };
    });
    box.querySelectorAll("[data-wrdisc]").forEach(function(a){
      a.onclick=function(ev){ ev.stopPropagation(); openWorkerReview(a.getAttribute("data-wrdisc"), payWindow(), "wr-disc"); };
    });
    wireBulk(box);
  }

  // ── bulk review / send-to-accounts across ticked workers ──
  function wireBulk(box){
    // drop stale picks that no longer exist or stopped being actionable
    var live={};
    box.querySelectorAll("input.bpick").forEach(function(cb){
      var emp=cb.getAttribute("data-emp");
      live[emp]=1;
      if(ST.bulk[emp]){
        ST.bulk[emp]={status:cb.getAttribute("data-status"), amt:parseFloat(cb.getAttribute("data-amt"))||0, nm:cb.getAttribute("data-nm")};
      }
      cb.onchange=function(){
        var tr=cb.closest("tr");
        if(cb.checked){
          ST.bulk[emp]={status:cb.getAttribute("data-status"), amt:parseFloat(cb.getAttribute("data-amt"))||0, nm:cb.getAttribute("data-nm")};
          if(tr) tr.classList.add("picked");
        } else {
          delete ST.bulk[emp];
          if(tr) tr.classList.remove("picked");
        }
        syncBulkBar();
      };
    });
    Object.keys(ST.bulk).forEach(function(emp){ if(!live[emp]) delete ST.bulk[emp]; });
    var all=el("bulk-all");
    if(all){
      all.onchange=function(){
        box.querySelectorAll("input.bpick").forEach(function(cb){
          cb.checked=all.checked;
          cb.onchange();
        });
      };
    }
    var bc=el("bulk-clear");
    if(bc){ bc.onclick=function(){ ST.bulk={}; renderPayable(); }; }
    var bs=el("bulk-send");
    if(bs){ bs.onclick=bulkReviewSend; }
    syncBulkBar();
  }

  function bulkSets(){
    var toReview=[], all=[], amt=0;
    Object.keys(ST.bulk).forEach(function(emp){
      var p=ST.bulk[emp];
      if(p.status==="Unpaid") toReview.push(emp);
      all.push(emp); amt+=p.amt;
    });
    return {toReview:toReview, all:all, amt:amt};
  }

  function syncBulkBar(){
    var s=bulkSets(), n=s.all.length;
    var info=el("bulk-info"), bs=el("bulk-send"), bc=el("bulk-clear"), hint=el("bulk-hint");
    if(!info) return;
    if(!n){
      info.textContent="";
      if(bs) bs.style.display="none";
      if(bc) bc.style.display="none";
      if(hint) hint.style.display="";
      return;
    }
    if(hint) hint.style.display="none";
    info.textContent=fmt(n)+" selected · "+money(s.amt);
    if(bs){ bs.style.display=""; bs.textContent="Review & send "+fmt(n)+" to accounts · "+money(s.amt); }
    if(bc) bc.style.display="";
  }

  function chunkCalls(action, emps, win, done){
    // sequential batches so big selections never hit the request timeout
    var SIZE=25, i=0, agg={results:[], sent:0, sent_total:0, errors:0, workers_reviewed:0, rows_reviewed:0};
    function step(){
      if(i>=emps.length){ done(null, agg); return; }
      var batch=emps.slice(i, i+SIZE); i+=SIZE;
      call({ action:action, employees:batch.join(","), from_date:(win.from||""), to_date:(win.to||"") }, true)
        .then(function(d){
          if(d.error){ done(new Error(d.error), agg); return; }
          agg.results=agg.results.concat(d.results||[]);
          agg.sent+=(d.sent||0); agg.sent_total+=(d.sent_total||0); agg.errors+=(d.errors||0);
          agg.workers_reviewed+=(d.workers_reviewed||0); agg.rows_reviewed+=(d.rows_reviewed||0);
          step();
        })
        .catch(function(e){ done(e, agg); });
    }
    step();
  }

  function bulkReviewSend(){
    var s=bulkSets();
    if(!s.all.length){ toast("Tick at least one worker","bad"); return; }
    var win=payWindow();
    confirmModal(
      "Review & send "+fmt(s.all.length)+" workers to accounts",
      '<p style="margin:0 0 10px">Mark <b>'+fmt(s.all.length)+' workers</b> totalling <b>'+money(s.amt)+'</b> as reviewed and send them to accounts?</p>'+
      '<p class="note" style="margin:0">Your user and the time are stamped on every day-row as the reviewer, then each worker gets their own payment reference (exactly as when sent one at a time) and lands in <b>Awaiting accounts</b> as Pending Accounts.</p>',
      "Review & send all",
      function(){
        var bs=el("bulk-send"); if(bs){ bs.disabled=true; bs.textContent="Reviewing…"; }
        function submitAll(){
          if(bs) bs.textContent="Sending…";
          chunkCalls("pay_bulk_submit", s.all, win, function(err, agg){
            if(bs) bs.disabled=false;
            var errs=(agg.results||[]).filter(function(r){ return r.error; });
            if(err){ toast("Bulk send stopped: "+err.message,"bad"); }
            else if(errs.length){
              toast(fmt(agg.sent)+" sent ("+money(agg.sent_total)+") · "+fmt(errs.length)+" skipped: "+errs.slice(0,3).map(function(r){ return r.employee+" — "+r.error; }).join("; ")+(errs.length>3?"…":""),"bad");
            } else {
              toast(fmt(agg.sent)+" workers reviewed & sent to accounts · "+money(agg.sent_total),"good");
            }
            ST.bulk={};
            win.refresh();
          });
        }
        if(s.toReview.length){
          chunkCalls("pay_bulk_review", s.toReview, win, function(err, agg){
            if(err){ if(bs) bs.disabled=false; toast("Bulk review stopped: "+err.message,"bad"); win.refresh(); return; }
            submitAll();
          });
        } else {
          submitAll();
        }
      },
      "good"
    );
  }

  function payWindow(){
    var r=range();
    return { from:r.from, to:r.to, refresh:function(){ loadPayable(); refreshAccountsCount(); } };
  }

  function workerByEmp(emp){
    for(var i=0;i<ST.workers.length;i++){ if(ST.workers[i].emp===emp) return ST.workers[i]; }
    return null;
  }
  function setPick(emp, on){
    var w=workerByEmp(emp);
    if(!w || !w.payable) return;
    if(on) ST.picked[emp]=w; else delete ST.picked[emp];
  }
  function togglePick(emp, on){
    setPick(emp, on);
    var tr=document.querySelector('#build-body tr[data-emp="'+emp.replace(/"/g,'\\\"')+'"]');
    if(tr) tr.classList.toggle("picked", !!ST.picked[emp]);
    syncSelectionKpis();
  }

  function syncSelectionKpis(){ /* selection dock removed — workers are paid one at a time */ }

  function clearPicks(){
    ST.picked={};
    document.querySelectorAll("#build-body input.pick").forEach(function(cb){ cb.checked=false; });
    document.querySelectorAll("#build-body tr.picked").forEach(function(tr){ tr.classList.remove("picked"); });
    var pa=el("pick-all"); if(pa) pa.checked=false;
    syncSelectionKpis();
  }

  // ── create + submit the run ──
  function createRun(){
    var keys=Object.keys(ST.picked);
    if(!keys.length){ toast("Select at least one worker","bad"); return; }
    var r=range();
    var title=(el("dk-runtitle").value||"").trim();
    var total=0; keys.forEach(function(k){ total += (ST.picked[k].owed||0); });

    confirmModal(
      "Create payment run",
      '<p style="margin:0 0 10px">This creates a run for <b>'+keys.length+' worker'+(keys.length===1?"":"s")+'</b> totalling <b>'+money(total)+'</b> and submits it to Accounts for release.</p>'+
      '<p class="note" style="margin:0">Only confirmed, unpaid, payroll-counted work in the selected date window is included. Accounts marks it paid to stamp the worker rows.</p>',
      "Create & submit",
      function(){
        el("dk-create").disabled=true;
        call({
          action:"pay_submit",
          title:title,
          workers:keys.join(","),
          submit_now:1,
          from_date:r.from,
          to_date:r.to
        }, true).then(function(d){
          el("dk-create").disabled=false;
          if(d.error){ toast(d.error,"bad"); return; }
          toast("Run "+(d.name||"")+" submitted · "+money(d.grand_total),"good");
          ST.picked={};
          loadPayable();
          refreshAccountsCount();
        }).catch(function(e){
          el("dk-create").disabled=false;
          toast("Could not create run: "+e.message,"bad");
        });
      }
    );
  }

  // ════════════════════════════════════════════════
  //  WORKER DETAIL
  // ════════════════════════════════════════════════
  function openWorkerDetail(emp){
    var r=range();
    var m=el("pay-detail-modal");
    var card=m.querySelector(".modal-card");
    if(card) card.classList.remove("xl");
    ["pd-approve","pd-review"].forEach(function(id){ var x=el(id); if(x){ x.style.display="none"; x.onclick=null; } });
    el("pd-name").firstChild.textContent="Worker";
    el("pd-sub").textContent=emp;
    el("pd-body").innerHTML='<div class="loading">Loading jobs…</div>';
    m.classList.add("on");
    call({ action:"pay_worker_detail", employee:emp, from_date:r.from, to_date:r.to })
      .then(function(d){
        el("pd-name").firstChild.textContent=d.employee_name||emp;
        el("pd-sub").textContent=emp+" · "+fmt(d.total_days)+" day"+(d.total_days===1?"":"s")+" · "+money(d.total_owed);
        var jobs=d.jobs||[];
        if(!jobs.length){
          el("pd-body").innerHTML='<div class="empty">No unpaid confirmed jobs in this window.</div>';
          return;
        }
        var h='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
          '<th>Date</th><th>Task</th><th>Farm</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead><tbody>';
        jobs.forEach(function(j){
          h+='<tr><td>'+esc(j.wdate||"")+'</td><td>'+esc(j.task||"")+'</td><td>'+esc(lbl(j.farm)||"")+'</td>'+
             '<td class="n m">'+fmt(j.qty)+'</td><td class="n m">'+fmt(j.rate,2)+'</td><td class="n m">'+money(j.amount)+'</td></tr>';
        });
        h+='</tbody><tfoot><tr><td colspan="5">Total owed</td><td class="n m">'+money(d.total_owed)+'</td></tr></tfoot></table></div></div>';
        el("pd-body").innerHTML=h;
      })
      .catch(function(e){ el("pd-body").innerHTML='<div class="err">Could not load worker detail.</div>'; });
  }

  // ════════════════════════════════════════════════
  //  AWAITING ACCOUNTS
  // ════════════════════════════════════════════════
  function loadAccounts(){
    var box=el("accounts-body");
    box.innerHTML='<div class="sk sk-row"></div><div class="sk sk-row"></div>';
    call({ action:"pay_pending" }).then(function(d){
      var rows=d.pending||[];
      ST.accCount=rows.length;
      updateAccBadge();
      var bn=el("pay-acc-banner");
      if(!ST.isAccounts){
        bn.innerHTML='<div class="banner info"><b>View only.</b> You can see runs awaiting accounts, but only an Accounts user can mark them paid.</div>';
      } else {
        bn.innerHTML='';
      }
      if(!rows.length){
        box.innerHTML='<div class="empty"><b>Nothing awaiting accounts</b>Runs you submit from the Build tab will appear here for release.</div>';
        return;
      }
      var h='<div class="runlist">';
      rows.forEach(function(r){
        h+=runCard(r, ST.isAccounts);
      });
      h+='</div>';
      box.innerHTML=h;
      wireRunCards(box);
    }).catch(function(e){
      box.innerHTML='<div class="err">Could not load pending runs: '+esc(e.message)+'</div>';
    });
  }

  function runCard(r, canPay){
    var foot='';
    if(r.employee){
      foot+='<button type="button" class="btn sm" data-wreview="'+esc(r.employee)+'" data-from="'+esc(r.period_from||"")+'" data-to="'+esc(r.period_to||"")+'">Review worker</button>';
    }
    foot+='<button type="button" class="btn sm" data-view="'+esc(r.name)+'">View lines</button>';
    foot+='<button type="button" class="btn sm" data-withdraw="'+esc(r.name)+'" data-nm="'+esc(r.employee_name||r.run_title||r.name)+'" style="color:var(--warn);border-color:#fde68a">Return to unpaid</button>';
    if(canPay){
      foot+='<button type="button" class="btn good sm" data-paid="'+esc(r.name)+'">Mark paid</button>';
    }
    return '<div class="runcard">'+
      '<div class="rc-head">'+
        '<div><div class="rc-title">'+esc(r.run_title||r.name)+'</div>'+
        '<div class="rc-sub">'+esc(r.name)+' · prepared by '+esc(r.prepared_by||"—")+' · '+esc(r.run_date||"")+
        (r.period_from?' · work '+esc(dshort(r.period_from))+' → '+esc(dshort(r.period_to)):'')+'</div></div>'+
        '<span class="tag pending">Pending accounts</span>'+
      '</div>'+
      '<div class="rc-figs">'+
        '<div class="rc-fig"><div class="rf-k">Worker'+(r.total_workers===1?'':'s')+'</div><div class="rf-v">'+(r.total_workers===1?esc(r.employee_name||"1"):fmt(r.total_workers))+'</div></div>'+
        '<div class="rc-fig"><div class="rf-k">Grand total</div><div class="rf-v">'+money(r.grand_total)+'</div></div>'+
      '</div>'+
      '<div class="rc-foot">'+foot+'</div>'+
    '</div>';
  }

  function accountsWindow(r){
    return { from:r&&r.getAttribute?(r.getAttribute("data-from")||""):(r||{}).period_from||"",
             to:r&&r.getAttribute?(r.getAttribute("data-to")||""):(r||{}).period_to||"",
             refresh:function(){ loadAccounts(); refreshAccountsCount(); loadPayable(); } };
  }

  function wireRunCards(box){
    box.querySelectorAll("[data-view]").forEach(function(b){
      b.onclick=function(){ openRunDetail(b.getAttribute("data-view")); };
    });
    box.querySelectorAll("[data-paid]").forEach(function(b){
      b.onclick=function(){ markPaid(b.getAttribute("data-paid")); };
    });
    box.querySelectorAll("[data-wreview]").forEach(function(b){
      b.onclick=function(){ openWorkerReview(b.getAttribute("data-wreview"), accountsWindow(b)); };
    });
    box.querySelectorAll("[data-withdraw]").forEach(function(b){
      b.onclick=function(){ withdrawRun(b.getAttribute("data-withdraw"), b.getAttribute("data-nm")); };
    });
  }

  function withdrawRun(name, nm){
    confirmModal(
      "Return to unpaid",
      '<p style="margin:0 0 10px">Take <b>'+esc(nm)+'</b> ('+esc(name)+') out of the accounts queue?</p>'+
      '<p class="note" style="margin:0">The payment reference is removed, the worker goes back to <b>Unpaid</b> and their review is cleared — correct the days if needed, then review and send again.</p>',
      "Return to unpaid",
      function(){
        call({ action:"pay_run_withdraw", name:name }, true)
          .then(function(d){
            if(d.error){ toast(d.error,"bad"); return; }
            toast(esc(nm)+" returned to unpaid — redo review when ready","good");
            loadAccounts();
            refreshAccountsCount();
            loadPayable();
          })
          .catch(function(e){ toast("Could not return: "+e.message,"bad"); });
      }
    );
  }

  function markPaid(name){
    confirmModal(
      "Mark run paid",
      '<p style="margin:0 0 10px">Release <b>'+esc(name)+'</b> and stamp every included worker row as paid?</p>'+
      '<p class="note" style="margin:0">This finalises the run and can’t be undone from here. Worker earnings in the run’s window are marked paid.</p>',
      "Mark paid",
      function(){
        call({ action:"pay_mark_paid", name:name }, true).then(function(d){
          if(d.error){ toast(d.error,"bad"); return; }
          toast("Run "+esc(name)+" marked paid","good");
          loadAccounts();
        }).catch(function(e){ toast("Could not mark paid: "+e.message,"bad"); });
      },
      "good"
    );
  }

  // ════════════════════════════════════════════════
  //  MY RUNS
  // ════════════════════════════════════════════════
  function loadMine(){
    var box=el("mine-body");
    box.innerHTML='<div class="sk sk-row"></div><div class="sk sk-row"></div>';
    call({ action:"pay_my" }).then(function(d){
      var rows=d.runs||[];
      if(!rows.length){
        box.innerHTML='<div class="empty"><b>No runs yet</b>Create your first payment run from the Build tab.</div>';
        return;
      }
      var h='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
        '<th>Run</th><th>Title</th><th class="n">Workers</th><th class="n">Total</th><th class="c">Status</th><th>Date</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr><td><span class="rowlink" data-view="'+esc(r.name)+'">'+esc(r.name)+'</span></td>'+
           '<td>'+esc(r.run_title||"—")+'</td>'+
           '<td class="n m">'+fmt(r.total_workers)+'</td>'+
           '<td class="n m">'+money(r.grand_total)+'</td>'+
           '<td class="c">'+stateTag(r.workflow_state)+'</td>'+
           '<td>'+esc(r.run_date||"")+'</td></tr>';
      });
      h+='</tbody></table></div></div>';
      box.innerHTML=h;
      box.querySelectorAll("[data-view]").forEach(function(a){
        a.onclick=function(){ openRunDetail(a.getAttribute("data-view")); };
      });
    }).catch(function(e){
      box.innerHTML='<div class="err">Could not load your runs: '+esc(e.message)+'</div>';
    });
  }

  // ════════════════════════════════════════════════
  //  AUDIT  (confirmed actuals x assigner x payment)
  // ════════════════════════════════════════════════
  var AU = { view:"summary", summary:[], detail:[], totals:null, farms:{}, loaded:false, wired:false };

  function initAudit(){
    if(!AU.wired){
      // default range = current month-to-date
      if(!el("au-from").value) el("au-from").value = monthStartISO();
      if(!el("au-to").value) el("au-to").value = todayISO();
      el("au-apply").onclick = loadAudit;
      el("au-reset").onclick = function(){ el("au-from").value=monthStartISO(); el("au-to").value=todayISO(); AU.farms={}; loadAudit(); };
      el("au-print").onclick = printAudit;
      el("au-xlsx").onclick = exportAuditExcel;
      el("au-v-summary").onclick = function(){ setAuditView("summary"); };
      el("au-v-detail").onclick = function(){ setAuditView("detail"); };
      if(el("au-v-workers")) el("au-v-workers").onclick = function(){ setAuditView("workers"); };
      if(el("au-v-disc")) el("au-v-disc").onclick = function(){ setAuditView("disc"); };
      AU.wired = true;
    }
    setAuditViewButtons();
    if(!AU.loaded) loadAudit();
  }

  function setAuditView(v){ AU.view=v; setAuditViewButtons(); renderAudit(); }
  function setAuditViewButtons(){
    var s=el("au-v-summary"), d=el("au-v-detail"), w=el("au-v-workers"), x=el("au-v-disc");
    if(s) s.classList.toggle("pay", AU.view==="summary");
    if(d) d.classList.toggle("pay", AU.view==="detail");
    if(w) w.classList.toggle("pay", AU.view==="workers");
    if(x) x.classList.toggle("pay", AU.view==="disc");
  }

  function auFarmsCSV(){ var k=Object.keys(AU.farms); return k.length?k.join(","):""; }

  function loadAudit(){
    var box=el("audit-body");
    box.innerHTML='<div class="loading">Building audit&hellip;</div>';
    var r={from:el("au-from").value||"", to:el("au-to").value||""};
    call({action:"pay_audit", from_date:r.from, to_date:r.to, farms:auFarmsCSV()}).then(function(d){
      AU.summary=d.summary||[]; AU.detail=d.detail||[]; AU.totals=d.totals||null; AU.loaded=true;
      AU.disc=null;   // discrepancies reload with the new filters when that view opens
      // farm chip set from summary rows
      var fs={}; AU.summary.forEach(function(s){ if(s.farm) fs[s.farm]=1; });
      AU.allFarms=Object.keys(fs).sort();
      renderAuditKpis();
      renderAuditChips();
      renderAudit();
    }).catch(function(e){
      box.innerHTML='<div class="err">Could not build audit: '+esc(e.message)+'</div>';
    });
  }

  function renderAuditKpis(){
    var t=AU.totals; var wrap=el("au-kpis");
    if(!t){ wrap.style.display="none"; return; }
    wrap.style.display="";
    el("au-k-tasks").textContent=fmt(t.tasks);
    el("au-k-pay").textContent=fmt(t.total_pay);
    el("au-k-paid").textContent=fmt(t.paid);
    el("au-k-unpaid").textContent=fmt(t.unpaid);
  }

  function renderAuditChips(){
    var host=el("au-farmchips"); if(!host) return;
    var h='<div class="fchip allchip'+(Object.keys(AU.farms).length?"":" on")+'" data-farm="">All farms</div>';
    (AU.allFarms||[]).forEach(function(f){
      h+='<div class="fchip'+(AU.farms[f]?" on":"")+'" data-farm="'+esc(f)+'">'+esc(f)+'</div>';
    });
    host.innerHTML=h;
    host.querySelectorAll(".fchip").forEach(function(c){
      c.onclick=function(){
        var f=c.getAttribute("data-farm");
        if(f===""){ AU.farms={}; }
        else if(AU.farms[f]){ delete AU.farms[f]; }
        else { AU.farms[f]=1; }
        loadAudit();
      };
    });
  }

  function payTag(s){
    var m={"Paid":"paid","Part paid":"submitted","In run (awaiting accounts)":"submitted","Unpaid":"unpaid","Reviewed":"reviewed","Sent to accounts":"sent","Submitted":"sent"};
    var c=m[s]||"";
    return '<span class="tag '+c+'">'+esc(s||"")+'</span>';
  }

  function renderAudit(){
    var box=el("audit-body");
    if(!AU.loaded){ box.innerHTML='<div class="loading">Pick a date range and press Apply&hellip;</div>'; return; }
    if(AU.view==="summary") renderAuditSummary(box);
    else if(AU.view==="workers") renderAuditWorkers(box);
    else if(AU.view==="disc") renderAuditDisc(box);
    else renderAuditDetail(box);
  }

  // ════ AUDIT · DISCREPANCIES — every way money can leak, each row auditable ════
  function renderAuditDisc(box){
    if(!AU.disc){
      box.innerHTML='<div class="loading">Scanning for discrepancies&hellip;</div>';
      var r={from:el("au-from").value||"", to:el("au-to").value||""};
      call({action:"pay_discrepancies", from_date:r.from, to_date:r.to, farms:auFarmsCSV()}).then(function(d){
        if(d.error){ box.innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
        AU.disc=d;
        renderAuditDisc(box);
      }).catch(function(e){ box.innerHTML='<div class="err">Could not scan: '+esc(e.message)+'</div>'; });
      return;
    }
    var d=AU.disc, checks=d.checks||[], win=d.window||{};
    var totalIssues=0; checks.forEach(function(c){ totalIssues+=c.count||0; });
    var h='<div class="filters" style="margin-bottom:12px;padding:8px 14px"><span class="hint">'+
      'Window <b>'+esc(win.from||"")+' &rarr; '+esc(win.to||"")+'</b> · '+fmt(d.scanned_rows)+' confirmed worker-day rows checked · '+
      '<b style="color:'+(totalIssues?'var(--bad)':'var(--good)')+'">'+fmt(totalIssues)+' findings</b>'+
      '</span><span style="flex:1"></span><span class="hint">Presence key: <b style="color:#0a7a43">in 06:42</b> check-in time · <b style="color:#0a7a43">P</b> marked present (no scan) · <b style="color:#b91c1c">absent</b> marked Absent · <b style="color:#a06000">?</b> no record either way. Click a worker to open their review sheet.</span></div>';
    checks.forEach(function(c,ci){
      var open = AU.discOpen!=null ? (AU.discOpen===c.key) : (ci===0 && c.count>0);
      var sev = c.count ? (c.key==="off_paid" ? "var(--warn, #a06000)" : "var(--bad, #b91c1c)") : "var(--good, #0a7a43)";
      if(c.disabled) sev="var(--mute, #8a8780)";
      var sub="";
      if(c.key==="absent_paid" && c.count){
        var wsc=(c.rows||[]).filter(function(r){ return r.scan_in; }).length;
        sub='<span class="hint"><b style="color:#0a7a43">'+fmt(wsc)+'</b> have a scan — attendance likely wrong · <b style="color:#b91c1c">'+fmt(c.count-wsc)+'</b> no scan — scrutinise the entry</span>';
      }
      h+='<div style="border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden">'+
        '<div class="disc-head" data-disc="'+esc(c.key)+'" style="padding:12px 16px;background:var(--wash);display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;cursor:pointer">'+
          '<b style="font-size:13px">'+esc(c.title)+'</b>'+
          (c.disabled?'<span class="hint" style="color:var(--mute)">check turned off in Work Management Settings</span>':'<span class="m" style="font-weight:700;color:'+sev+'">'+fmt(c.count)+(c.count>=200?"+":"")+' row'+(c.count===1?"":"s")+'</span>')+
          (c.workers?'<span class="hint">'+fmt(c.workers)+' workers</span>':'')+
          (c.amount?'<span class="m" style="font-weight:600">'+money(c.amount)+(c.key==="no_pay"?" owed":"")+'</span>':'')+sub+
          '<span style="flex:1"></span><span class="hint">'+(open?"▾":"▸")+'</span>'+
        '</div>'+
        '<div style="padding:6px 16px 0;font-size:11px;color:var(--mute)">'+esc(c.about)+'</div>'+
        '<div class="disc-body" id="disc-'+esc(c.key)+'" style="display:'+(open?"block":"none")+';padding:10px 16px 14px">'+
        discTable(c)+'</div></div>';
    });
    box.innerHTML=h;
    box.querySelectorAll(".disc-head").forEach(function(hd){
      hd.onclick=function(){
        var k=hd.getAttribute("data-disc");
        AU.discOpen=(AU.discOpen===k)?"__none__":k;
        renderAuditDisc(box);
      };
    });
    box.querySelectorAll("[data-wraudit]").forEach(function(a){
      a.onclick=function(){ openWorkerReview(a.getAttribute("data-wraudit"), auditWindow()); };
    });
    var dd=el("disc-dedup");
    if(dd){
      dd.onclick=function(){
        confirmModal("Zero duplicate day entries",
          '<p style="margin:0 0 10px">For every worker-day recorded twice, keep the copy in the <b>earliest document</b> and zero the re-entered ones?</p>'+
          '<p class="note" style="margin:0">Quantities and pay of the duplicates go to 0, documents are re-summed, an audit comment names every zeroed day and where the kept copy lives. Duplicate groups that are already paid are skipped for manual review.</p>',
          "Zero duplicates",
          function(){
            dd.disabled=true; dd.textContent="Repairing…";
            var r={action:"pay_fix_duplicates", from_date:el("au-from").value||"", to_date:el("au-to").value||"", farms:auFarmsCSV()};
            function step(){
              call(r, true).then(function(d){
                if(d.error){ toast(d.error,"bad"); dd.disabled=false; return; }
                if(d.remaining_groups>0){ dd.textContent="Repairing… "+d.remaining_groups+" left"; step(); return; }
                toast("Duplicates zeroed · "+money(d.excess_total)+" excess removed"+(d.skipped_paid_groups?(" · "+d.skipped_paid_groups+" paid group(s) skipped"):""),"good");
                AU.disc=null; AU.loaded=false; loadAudit();
              }).catch(function(e){ toast("Repair failed: "+e.message,"bad"); dd.disabled=false; });
            }
            step();
          }, "good");
      };
    }
    var rv=el("disc-revalue");
    if(rv){
      rv.onclick=function(){
        confirmModal("Revalue zero-pay rows",
          '<p style="margin:0 0 10px">Set each of these rows to <b>qty × the document rate</b> and restore payroll counting?</p>'+
          '<p class="note" style="margin:0">Only unpaid rows on CONFIRMED documents are touched; every document gets an audit comment and the workers return to Unpaid for review.</p>',
          "Revalue now",
          function(){
            rv.disabled=true; rv.textContent="Revaluing…";
            call({action:"pay_fix_unvalued", rownames:rv.getAttribute("data-rows")}, true).then(function(d){
              if(d.error){ toast(d.error,"bad"); rv.disabled=false; return; }
              toast(fmt(d.fixed_count)+" rows revalued · "+money(d.fixed_total)+((d.errors&&d.errors.length)?(" · "+d.errors.length+" skipped"):""),"good");
              AU.disc=null; AU.loaded=false; loadAudit();
            }).catch(function(e){ toast("Could not revalue: "+e.message,"bad"); rv.disabled=false; });
          }, "good");
      };
    }
  }

  // presence cell: check-in time / absent / ? — see the key at the top of the view
  function discPres(r){
    if(r.scan_in) return '<span style="color:#0a7a43;font-weight:700" title="biometric check-in time">in '+esc(r.scan_in)+'</span>';
    if((r.att_status||"")==="Absent") return '<span style="color:#b91c1c;font-weight:700" title="attendance marked Absent, no scan">absent</span>';
    if(r.att_status) return '<span style="color:#0a7a43;font-weight:700" title="attendance: '+esc(r.att_status)+', no scan time">P</span>';
    return '<span style="color:#a06000;font-weight:700" title="no scan and no attendance record — presence unknown">?</span>';
  }

  function discTable(c){
    var rows=c.rows||[];
    if(!rows.length) return '<div class="empty" style="padding:16px">Nothing found — clean.</div>';
    function wlink(r){
      return r.employee ? '<span class="rowlink" data-wraudit="'+esc(r.employee)+'">'+esc(r.employee_name||r.employee)+'</span>' : '—';
    }
    var h='<div class="tablescroll" style="max-height:380px"><table style="margin-top:0"><thead><tr>';
    var body='';
    if(c.key==="multi_farm_day"){
      h+='<th>Worker</th><th>Day</th><th>Farms</th><th class="n">KES</th><th>Actuals docs</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.farms||"")+'</td>'+
          '<td class="n m">'+fmt(r.amount,2)+'</td><td class="m" style="font-size:10px">'+esc(r.actuals||"")+'</td></tr>';
      });
    } else if(c.key==="self_approved"){
      h+='<th>Actuals doc</th><th>Farm</th><th>Task</th><th>Entered by</th><th>HR appr.</th><th>GM appr.</th><th class="n">KES</th>';
      rows.forEach(function(r){
        body+='<tr><td class="m">'+esc(r.actuals)+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(r.task||"")+'</td>'+
          '<td>'+esc(shortUser(r.entered_by))+'</td><td>'+esc(shortUser(r.hr_approved_by)||"—")+'</td><td>'+esc(shortUser(r.gm_approved_by)||"—")+'</td>'+
          '<td class="n m">'+fmt(r.amount,2)+'</td></tr>';
      });
    } else if(c.key==="left_but_earning"){
      h+='<th>Worker</th><th>Day worked</th><th>Left on</th><th>Farm</th><th>Task</th><th class="n">KES</th><th>Doc</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td class="m" style="color:var(--bad)">'+esc(dshort(r.left_date))+'</td>'+
          '<td>'+esc(r.farm||"")+'</td><td>'+esc(r.task||"")+'</td><td class="n m">'+fmt(r.amount,2)+'</td><td class="m" style="font-size:10px">'+esc(r.actuals)+'</td></tr>';
      });
    } else if(c.key==="rate_mismatch"){
      h+='<th>Worker</th><th>Day</th><th>Task</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Expected</th><th class="n">Stored</th><th>Doc</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.task||"")+'</td>'+
          '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.rate,2)+'</td><td class="n m">'+fmt(r.expected)+'</td>'+
          '<td class="n m" style="color:var(--bad);font-weight:700">'+fmt(r.amount,2)+'</td><td class="m" style="font-size:10px">'+esc(r.actuals)+'</td></tr>';
      });
    } else if(c.key==="dup_day"){
      h+='<th>Worker</th><th>Day</th><th>Farm</th><th>Task</th><th class="n">Copies</th><th class="n">Total KES</th><th class="n">Excess KES</th><th>Docs</th><th>Entered by</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(r.task||"")+'</td>'+
          '<td class="n m" style="color:var(--bad);font-weight:700">'+fmt(r.copies)+'×</td>'+
          '<td class="n m">'+fmt(r.total_amt,2)+'</td>'+
          '<td class="n m" style="color:var(--bad);font-weight:700">'+fmt(r.amount,2)+'</td>'+
          '<td class="m" style="font-size:10px">'+esc(r.actuals||"")+'</td>'+
          '<td class="m" style="font-size:10px">'+esc(shortUser(r.entered_by||""))+'</td></tr>';
      });
    } else if(c.key==="no_pay"){
      h+='<th>Worker</th><th>Day</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">Rate</th><th class="n">Should be KES</th><th class="n">Stored</th><th>Doc</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(r.task||"")+'</td>'+
          '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.rate,2)+'</td>'+
          '<td class="n m" style="color:#0a7a43;font-weight:700">'+fmt(r.should_be,2)+'</td>'+
          '<td class="n m" style="color:var(--bad);font-weight:700">0</td>'+
          '<td class="m" style="font-size:10px">'+esc(r.actuals)+'</td></tr>';
      });
    } else {
      // presence-based checks: absent_paid / ghost_days / leave_paid / off_paid
      h+='<th>Worker</th><th>Day</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">KES</th><th class="c">Presence</th>'+(c.key==="leave_paid"?'<th>Leave</th>':'')+'<th class="c">Paid</th><th>Doc</th>';
      rows.forEach(function(r){
        body+='<tr><td>'+wlink(r)+'</td><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.farm||"")+'</td><td>'+esc(r.task||"")+'</td>'+
          '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.amount,2)+'</td>'+
          '<td class="c m">'+discPres(r)+'</td>'+
          (c.key==="leave_paid"?('<td>'+esc(r.leave_type||"")+'</td>'):'')+
          '<td class="c">'+payTag(r.paid?"Paid":"Unpaid")+'</td>'+
          '<td class="m" style="font-size:10px">'+esc(r.actuals)+'</td></tr>';
      });
    }
    h+='</tr></thead><tbody>'+body+'</tbody></table></div>';
    if(c.key==="dup_day" && rows.length){
      var texc=0; rows.forEach(function(r){ texc+=(r.amount||0); });
      h+='<div style="margin-top:10px"><button type="button" class="btn good sm" id="disc-dedup">Zero the duplicates · keep first copy · '+money(texc)+'</button>'+
         '<span class="hint" style="margin-left:10px">Keeps the copy in the earliest document, zeroes the re-entered ones (qty and pay), re-sums the documents and leaves audit comments. Groups with a paid copy are skipped.</span></div>';
    }
    if(c.key==="no_pay"){
      var rns=rows.map(function(r){ return r.rowname; }).filter(Boolean);
      if(rns.length){
        var totS=0; rows.forEach(function(r){ totS+=(r.should_be||0); });
        h+='<div style="margin-top:10px"><button type="button" class="btn good sm" id="disc-revalue" data-rows="'+esc(rns.join(","))+'">Revalue '+fmt(rns.length)+' row'+(rns.length>1?'s':'')+' at doc rate · '+money(totS)+'</button>'+
           '<span class="hint" style="margin-left:10px">Sets pay to qty × rate, restores payroll counting, re-sums the documents and leaves an audit comment. Workers go back to Unpaid for review.</span></div>';
      }
    }
    if(c.count>=200) h+='<div class="note">Showing the first 200 rows — narrow the date range or farm filter to see the rest.</div>';
    return h;
  }

  function renderAuditSummary(box){
    var rows=AU.summary||[];
    if(!rows.length){ box.innerHTML='<div class="empty">No confirmed actuals in this range.</div>'; return; }
    var h='<div class="tablewrap"><div class="tablescroll"><table id="au-table"><thead><tr>'+
      '<th>Farm</th><th>Task</th><th>Block</th><th>Assignment</th>'+
      '<th class="n">Planned</th><th class="n">Assigned</th><th class="n">Qty</th><th class="n">Workers</th>'+
      '<th class="n">Total KES</th><th class="n">Paid KES</th><th class="n">Unpaid KES</th>'+
      '<th class="c">Status</th><th>Run</th><th>Entered by</th></tr></thead><tbody>';
    rows.forEach(function(s){
      h+='<tr>'+
        '<td>'+esc(s.farm)+'</td><td>'+esc(s.task)+'</td><td>'+esc(s.block||"—")+'</td>'+
        '<td>'+esc(s.assignment||"—")+'</td>'+
        '<td class="n m">'+fmt(s.planned_people)+'</td><td class="n m">'+fmt(s.assigned_count)+'</td>'+
        '<td class="n m">'+fmt(s.actual_qty)+'</td><td class="n m">'+fmt(s.workers)+'</td>'+
        '<td class="n m">'+fmt(s.total_pay,2)+'</td><td class="n m">'+fmt(s.paid_pay,2)+'</td><td class="n m">'+fmt(s.unpaid_pay,2)+'</td>'+
        '<td class="c">'+payTag(s.pay_status)+'</td><td>'+esc(s.run_refs||"—")+'</td><td>'+esc(s.entered_by||"—")+'</td>'+
        '</tr>';
    });
    var t=AU.totals||{};
    h+='</tbody><tfoot><tr><th colspan="6">TOTAL &middot; '+fmt(t.tasks)+' tasks</th>'+
       '<th class="n">'+fmt(t.qty)+'</th><th></th>'+
       '<th class="n">'+fmt(t.total_pay)+'</th><th class="n">'+fmt(t.paid)+'</th><th class="n">'+fmt(t.unpaid)+'</th>'+
       '<th colspan="3"></th></tr></tfoot>';
    h+='</table></div></div>';
    box.innerHTML=h;
  }

  function renderAuditDetail(box){
    var rows=AU.detail||[];
    if(!rows.length){ box.innerHTML='<div class="empty">No confirmed worker rows in this range.</div>'; return; }
    var h='<div class="tablewrap"><div class="tablescroll"><table id="au-table"><thead><tr>'+
      '<th>Farm</th><th>Task</th><th>Assignment</th><th>Worker</th><th>ID</th><th>Type</th>'+
      '<th>Date</th><th class="n">Qty</th><th class="n">Amount KES</th><th class="c">Paid</th><th>Run</th></tr></thead><tbody>';
    rows.forEach(function(r){
      h+='<tr>'+
        '<td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td>'+esc(r.assignment||"—")+'</td>'+
        '<td>'+esc(r.emp_name||r.emp)+'</td><td>'+esc(r.emp)+'</td><td>'+esc(r.emp_type||"—")+'</td>'+
        '<td>'+esc(r.wdate||"")+'</td><td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.amount,2)+'</td>'+
        '<td class="c">'+payTag(r.pay_status)+'</td><td>'+esc(r.run_ref||"—")+'</td>'+
        '</tr>';
    });
    var t=AU.totals||{};
    h+='</tbody><tfoot><tr><th colspan="7">TOTAL &middot; '+fmt(t.worker_days)+' worker-days</th>'+
       '<th class="n">'+fmt(t.qty)+'</th><th class="n">'+fmt(t.total_pay)+'</th><th colspan="2"></th></tr></tfoot>';
    h+='</table></div></div>';
    box.innerHTML=h;
  }

  // ════════════════════════════════════════════════
  //  AUDIT · WORKERS  (one row per person — review & approve one at a time)
  // ════════════════════════════════════════════════
  function dshort(iso){
    if(!iso) return "";
    var dt=new Date(iso+"T00:00:00");
    if(isNaN(dt)) return iso;
    return dt.toLocaleDateString("en-GB",{weekday:"short",day:"2-digit",month:"short"});
  }
  function shortUser(u){
    if(!u) return "";
    return String(u).replace(/@.*$/,"");
  }

  function auditWorkerRollup(){
    var map={};
    (AU.detail||[]).forEach(function(r){
      var g=map[r.emp];
      if(!g){
        g={ emp:r.emp, nm:r.emp_name||r.emp, type:r.emp_type||"", farms:{}, tasks:{}, days:{},
            first:null, last:null, qty:0, amount:0, paid_amt:0, unpaid_amt:0, runs:{} };
        map[r.emp]=g;
      }
      if(r.farm) g.farms[r.farm]=1;
      if(r.task) g.tasks[r.task]=1;
      if(r.wdate){
        g.days[r.wdate]=1;
        if(!g.first||r.wdate<g.first) g.first=r.wdate;
        if(!g.last||r.wdate>g.last) g.last=r.wdate;
      }
      g.qty+=(r.qty||0);
      g.amount+=(r.amount||0);
      if(r.pay_status==="Paid"){ g.paid_amt+=(r.amount||0); }
      else if(r.in_payroll){ g.unpaid_amt+=(r.amount||0); if(!r.reviewed) g.unreviewed_amt=(g.unreviewed_amt||0)+(r.amount||0); }
      if(r.run_ref) g.runs[r.run_ref]=1;
    });
    var rows=Object.keys(map).map(function(k){
      var g=map[k];
      g.farm_list=Object.keys(g.farms).sort().join(", ");
      g.task_count=Object.keys(g.tasks).length;
      g.day_count=Object.keys(g.days).length;
      g.run_list=Object.keys(g.runs).sort().join(", ");
      if(g.amount>0 && g.paid_amt>=g.amount-0.001) g.status="Paid";
      else if(g.paid_amt>0) g.status="Part paid";
      else if((g.unreviewed_amt||0)<=0.001) g.status="Reviewed";
      else g.status="Unpaid";
      return g;
    });
    rows.sort(function(a,b){ return b.unpaid_amt-a.unpaid_amt || b.amount-a.amount; });
    return rows;
  }

  function renderAuditWorkers(box){
    var rows=auditWorkerRollup();
    if(!rows.length){ box.innerHTML='<div class="empty">No confirmed worker rows in this range.</div>'; return; }
    var h='<div class="filters" style="margin-bottom:10px">'+
      '<input type="text" id="auw-q" placeholder="Search worker, ID or task&hellip;" style="min-width:230px;flex:0 1 auto">'+
      '<span class="hint" id="auw-count"></span><span style="flex:1"></span>'+
      '<span class="hint">Review each person, then approve &amp; send their pay to accounts &mdash; one at a time.</span></div>'+
      '<div id="auw-body"></div>';
    box.innerHTML=h;
    var q=el("auw-q");
    function paint(){
      var vq=(q.value||"").trim().toLowerCase();
      var flt=rows.filter(function(g){
        if(!vq) return true;
        return (g.nm+" "+g.emp+" "+g.farm_list+" "+Object.keys(g.tasks).join(" ")).toLowerCase().indexOf(vq)>-1;
      });
      el("auw-count").textContent=flt.length+" of "+rows.length+" workers";
      var t='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
        '<th>Worker</th><th>ID</th><th>Farm</th><th>Period worked</th><th class="n">Tasks</th><th class="n">Days</th><th class="n">Qty</th>'+
        '<th class="n">Earned KES</th><th class="n">Paid KES</th><th class="n">Unpaid KES</th>'+
        '<th class="c">Status</th><th class="c">Actions</th></tr></thead><tbody>';
      var tq=0, te=0, tp=0, tu=0;
      flt.forEach(function(g){
        tq+=g.qty; te+=g.amount; tp+=g.paid_amt; tu+=g.unpaid_amt;
        var acts='<button type="button" class="btn sm" data-review="'+esc(g.emp)+'">Review</button>';
        if(g.unpaid_amt>0.001 && g.status==="Reviewed"){
          acts+=' <button type="button" class="btn good sm" data-approve="'+esc(g.emp)+'" data-nm="'+esc(g.nm)+'" data-amt="'+g.unpaid_amt+'">Send to accounts</button>';
        }
        t+='<tr><td><span class="rowlink" data-review="'+esc(g.emp)+'">'+esc(g.nm)+'</span></td>'+
          '<td class="m">'+esc(g.emp)+'</td><td>'+esc(g.farm_list)+'</td>'+
          '<td class="m">'+esc(dshort(g.first))+' &rarr; '+esc(dshort(g.last))+'</td>'+
          '<td class="n m">'+fmt(g.task_count)+'</td><td class="n m">'+fmt(g.day_count)+'</td><td class="n m">'+fmt(g.qty)+'</td>'+
          '<td class="n m">'+fmt(g.amount)+'</td><td class="n m">'+fmt(g.paid_amt)+'</td><td class="n m">'+fmt(g.unpaid_amt)+'</td>'+
          '<td class="c">'+payTag(g.status)+'</td><td class="c" style="white-space:nowrap">'+acts+'</td></tr>';
      });
      t+='</tbody><tfoot><tr><th colspan="6">TOTAL &middot; '+fmt(flt.length)+' workers</th>'+
         '<th class="n">'+fmt(tq)+'</th><th class="n">'+fmt(te,2)+'</th><th class="n">'+fmt(tp,2)+'</th><th class="n">'+fmt(tu,2)+'</th>'+
         '<th colspan="2"></th></tr></tfoot></table></div></div>';
      el("auw-body").innerHTML=t;
      el("auw-body").querySelectorAll("[data-review]").forEach(function(b){
        b.onclick=function(){ openWorkerAudit(b.getAttribute("data-review")); };
      });
      el("auw-body").querySelectorAll("[data-approve]").forEach(function(b){
        b.onclick=function(){
          approveWorker(b.getAttribute("data-approve"), b.getAttribute("data-nm"), parseFloat(b.getAttribute("data-amt"))||0, auditWindow());
        };
      });
    }
    q.oninput=paint;
    paint();
  }

  // ── one worker, in depth: every task, period, payment ──
  var WR={from:"",to:"",refresh:null};
  function auditWindow(){
    return { from:el("au-from").value||"", to:el("au-to").value||"",
             refresh:function(){ loadAudit(); refreshAccountsCount(); } };
  }
  function openWorkerAudit(emp){ openWorkerReview(emp, auditWindow()); }
  function openWorkerReview(emp, win, targetTab){
    WR=win||{from:"",to:"",refresh:null};
    WR.targetTab=targetTab||null;
    var m=el("pay-detail-modal");
    var card=m.querySelector(".modal-card");
    if(card) card.classList.add("xl");
    ["pd-approve","pd-review"].forEach(function(id){ var x=el(id); if(x){ x.style.display="none"; x.onclick=null; } });
    el("pd-name").firstChild.textContent="Worker review";
    el("pd-sub").textContent=emp;
    el("pd-body").innerHTML='<div class="loading">Building work history&hellip;</div>';
    m.classList.add("on");
    call({ action:"pay_worker_history", employee:emp, from_date:WR.from, to_date:WR.to })
      .then(function(d){
        if(d.error){ el("pd-body").innerHTML='<div class="err">'+esc(d.error)+'</div>'; return; }
        renderWorkerHistory(d);
      })
      .catch(function(e){ el("pd-body").innerHTML='<div class="err">Could not load worker history: '+esc(e.message)+'</div>'; });
  }

  function renderWorkerHistory(d){
    WR.data=d;
    var info=d.info||{}, k=d.kpi||{};
    el("pd-name").firstChild.textContent=info.employee_name||info.employee||"Worker";
    el("pd-sub").textContent=(info.employee||"")+" · "+(info.designation||info.employment_type||"")+
      (info.farm?" · "+lbl(info.farm):"");
    var tasks=d.tasks||[], daily=d.daily||[], runs=d.runs||[];
    // this worker's discrepancies, straight from the day-rows' evidence
    var ISS={absent:[],ghost:[],leave:[],off:[]};
    daily.forEach(function(r){
      if((r.att_status||"")==="Absent") ISS.absent.push(r);
      else if(!r.scan_in && !r.att_status) ISS.ghost.push(r);
      if(r.day_leave) ISS.leave.push(r);
      if(r.day_off) ISS.off.push(r);
    });
    var nIss=ISS.absent.length+ISS.ghost.length+ISS.leave.length+ISS.off.length;
    var byTask={};
    daily.forEach(function(r){
      var kk=(r.task||"")+"|"+(r.block||"")+"|"+(r.farm||"");
      if(!byTask[kk]) byTask[kk]=[];
      byTask[kk].push(r);
    });
    function peopleLine(t){
      var who=[];
      (t.assigned_by||[]).forEach(function(u){ who.push(["Assigned by",u]); });
      (t.fm_approved_by||[]).forEach(function(u){ who.push(["FM approved",u]); });
      (t.entered_by||[]).forEach(function(u){ who.push(["Captured by",u]); });
      (t.hr_approved_by||[]).forEach(function(u){ who.push(["HR approved",u]); });
      (t.gm_approved_by||[]).forEach(function(u){ who.push(["GM approved",u]); });
      return who;
    }

    // ── header: internal tabs ──
    var h='<div class="farmchips" id="wr-tabs" style="margin:0 0 16px">'+
      '<div class="fchip on" data-wrtab="wr-overview">Overview</div>'+
      '<div class="fchip" data-wrtab="wr-work">Work &amp; days</div>'+
      '<div class="fchip" data-wrtab="wr-pay">Payments</div>'+
      '<div class="fchip" data-wrtab="wr-disc">Discrepancies'+(nIss?'&nbsp;<b style="color:#b91c1c">&#9873; '+nIss+'</b>':'')+'</div>'+
      '<span style="flex:1"></span>'+
      '<div class="fchip" id="wr-excel" title="Download this review as an Excel workbook — one table per task with its day rows">&#8681; Download Excel</div>'+
    '</div>';

    // ════ TAB 1 · OVERVIEW ════
    h+='<div class="wr-sec" id="wr-overview">';
    h+='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px 22px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;background:var(--wash);margin-bottom:14px;font-size:12px">'+
      '<div><div style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Worker</div><b>'+esc(info.employee_name||"—")+'</b><div style="color:var(--mute)" class="m">'+esc(info.employee||"")+'</div></div>'+
      '<div><div style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Designation</div><b>'+esc(info.designation||"—")+'</b><div style="color:var(--mute)">'+esc(info.employment_type||"")+'</div></div>'+
      '<div><div style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Farm</div><b>'+esc(lbl(info.farm)||"—")+'</b><div style="color:var(--mute)">'+esc(info.status||"")+'</div></div>'+
      '<div><div style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Joined</div><b>'+esc(dshort(info.date_of_joining)||"—")+'</b></div>'+
      '<div><div style="font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600">Worked this window</div><b>'+esc(dshort(k.first_day))+' &rarr; '+esc(dshort(k.last_day))+'</b><div style="color:var(--mute)">'+fmt(k.days)+' days</div></div>'+
    '</div>';
    h+='<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">'+
      '<div class="kpi" style="--kc:var(--pay)"><div class="k">Earned</div><div class="v">'+fmt(k.earned,2)+'</div><div class="u">KES · window</div></div>'+
      '<div class="kpi" style="--kc:var(--good)"><div class="k">Paid</div><div class="v">'+fmt(k.paid_amt,2)+'</div><div class="u">KES</div></div>'+
      '<div class="kpi" style="--kc:var(--warn)"><div class="k">Unpaid</div><div class="v">'+fmt(k.unpaid_amt,2)+'</div><div class="u">KES · payable</div></div>'+
      '<div class="kpi" style="--kc:var(--blue)"><div class="k">Days</div><div class="v">'+fmt(k.days)+'</div><div class="u">worked</div></div>'+
      '<div class="kpi"><div class="k">Tasks</div><div class="v">'+fmt(tasks.length)+'</div><div class="u">'+fmt(k.qty)+' units total</div></div>'+
      '<div class="kpi"><div class="k">Avg / day</div><div class="v">'+fmt(k.avg_per_day)+'</div><div class="u">KES</div></div>'+
    '</div>';
    h+='<div class="sech" style="margin-top:16px">Tasks in this window <span class="hint">totals per task — open Work &amp; days for the day-by-day record</span></div>';
    if(!tasks.length){ h+='<div class="empty">No confirmed work in this window.</div>'; }
    else{
      h+='<div class="tablewrap"><table><thead><tr>'+
        '<th>Task</th><th>Block</th><th>Standard</th><th>Period worked</th><th class="n">Days</th><th class="n">Qty</th>'+
        '<th class="n">Rate</th><th class="n">Amount KES</th><th class="n">Unpaid</th><th class="c">Status</th></tr></thead><tbody>';
      tasks.forEach(function(t){
        h+='<tr><td><b>'+esc(t.task||"—")+'</b></td><td>'+esc(lbl(t.block)||"—")+'</td>'+
          '<td class="m">'+esc(t.standard||"—")+'</td>'+
          '<td class="m">'+esc(dshort(t.work_from))+' &rarr; '+esc(dshort(t.work_to))+'</td>'+
          '<td class="n m">'+fmt(t.days)+'</td><td class="n m">'+fmt(t.qty)+'</td><td class="n m">'+fmt(t.rate,2)+'</td>'+
          '<td class="n m">'+fmt(t.amount,2)+'</td><td class="n m">'+fmt(t.unpaid_amt,2)+'</td>'+
          '<td class="c">'+payTag(t.pay_status)+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><th colspan="4">TOTAL</th><th class="n">'+fmt(k.days)+'</th><th class="n">'+fmt(k.qty)+'</th><th></th>'+
         '<th class="n">'+fmt(k.earned,2)+'</th><th class="n">'+fmt(k.unpaid_amt,2)+'</th><th></th></tr></tfoot></table></div>';
    }
    // people involved (union)
    var seenWho={}, whoAll=[];
    tasks.forEach(function(t){
      peopleLine(t).forEach(function(w){
        var kk=w[0]+"|"+w[1];
        if(!seenWho[kk]){ seenWho[kk]=1; whoAll.push(w); }
      });
    });
    if(whoAll.length){
      h+='<div class="sech" style="margin-top:16px">Assigners &amp; approvers</div><div class="farmchips" style="margin-top:6px">';
      whoAll.forEach(function(w){
        h+='<div class="fchip" style="cursor:default"><span style="color:var(--mute)">'+esc(w[0])+':</span>&nbsp;'+esc(shortUser(w[1]))+'</div>';
      });
      h+='</div>';
    }
    h+='</div>';

    // ════ TAB 2 · WORK & DAYS ════
    h+='<div class="wr-sec" id="wr-work" style="display:none">';
    h+='<div class="hint" style="margin-bottom:12px">One card per task. Under it, every day this worker’s output was recorded in Actuals — a day-row means “this person did this quantity on this date”. Unpaid days can be corrected with <b>Edit</b>: pay recomputes at the row’s rate and the worker goes back to “Unpaid” for re-review.</div>';
    if(!tasks.length){ h+='<div class="empty">No confirmed work in this window.</div>'; }
    tasks.forEach(function(t){
      var kk=(t.task||"")+"|"+(t.block||"")+"|"+(t.farm||"");
      var rows=(byTask[kk]||[]).slice().sort(function(a,b){ return (a.wdate||"")<(b.wdate||"")?-1:1; });
      var cardFlagged=0;
      rows.forEach(function(r){ if((r.att_status||"")==="Absent"||(!r.scan_in&&!r.att_status)||r.day_leave||r.day_off) cardFlagged++; });
      var who=peopleLine(t).map(function(w){ return w[0]+" "+shortUser(w[1]); });
      h+='<div style="border:1px solid var(--line);border-radius:14px;margin-bottom:14px;overflow:hidden">'+
        '<div style="padding:12px 16px;background:var(--wash);display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline">'+
          '<div style="font-weight:600;font-size:13px">'+esc(t.task||"—")+' <span style="color:var(--mute);font-weight:500">· '+esc(lbl(t.block)||"—")+' · '+esc(lbl(t.farm)||"")+'</span>'+(cardFlagged?' <span title="'+cardFlagged+' flagged day'+(cardFlagged>1?'s':'')+' — see the Discrepancies tab" style="color:#b91c1c;font-weight:700;font-size:11px">&#9873;'+cardFlagged+'</span>':'')+'</div>'+
          '<span style="flex:1"></span>'+
          '<span class="m" style="font-weight:600">'+money(t.amount)+'</span>'+payTag(t.pay_status)+
        '</div>'+
        '<div style="padding:8px 16px;border-top:1px solid var(--faint);font-size:11px;color:var(--mute);display:flex;flex-wrap:wrap;gap:4px 18px">'+
          '<span><b style="color:var(--ink)">Task period:</b> '+esc(dshort(t.plan_from)||dshort(t.work_from))+' &rarr; '+esc(dshort(t.plan_to)||dshort(t.work_to))+'</span>'+
          '<span><b style="color:var(--ink)">Worked:</b> '+esc(dshort(t.work_from))+' &rarr; '+esc(dshort(t.work_to))+' ('+fmt(t.days)+' day'+(t.days===1?'':'s')+')</span>'+
          (t.standard?'<span><b style="color:var(--ink)">Standard:</b> '+esc(t.standard)+'</span>':'')+
          ((t.assignments&&t.assignments.length)?'<span><b style="color:var(--ink)">Assignment'+(t.assignments.length>1?'s':'')+':</b> '+esc(t.assignments.join(", "))+'</span>':'')+
          ((t.runs&&t.runs.length)?'<span><b style="color:var(--ink)">Run'+(t.runs.length>1?'s':'')+':</b> '+esc(t.runs.join(", "))+'</span>':'')+
        '</div>'+
        (who.length?'<div style="padding:0 16px 8px;font-size:11px;color:var(--mute)">'+esc(who.join("  ·  "))+'</div>':'')+
        '<div class="tablescroll" style="max-height:320px"><table style="margin-top:0"><thead><tr>'+
          '<th>Day worked</th><th class="c">Presence</th><th class="n">Qty done</th><th class="n">Rate</th><th class="n">Pay KES</th><th class="c">Paid</th><th>Run</th><th class="c">Edit</th></tr></thead><tbody>';
      rows.forEach(function(r){
        var rowFlag=((r.att_status||"")==="Absent"||(!r.scan_in&&!r.att_status)||r.day_leave||r.day_off);
        h+='<tr'+(rowFlag?' style="background:rgba(185,28,28,.045)"':'')+'><td class="m">'+esc(dshort(r.wdate))+(r.day_leave?' <span style="color:#7c3aed;font-size:9px;font-weight:700" title="approved leave this day">'+esc(r.day_leave)+'</span>':'')+(r.day_off?' <span style="color:#a06000;font-size:9px;font-weight:700" title="weekly off / holiday">off day</span>':'')+'</td>'+
          '<td class="c">'+presenceTag(r)+'</td>'+
          '<td class="n m" data-qcell>'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.rate,2)+'</td><td class="n m">'+fmt(r.amount,2)+'</td>'+
          '<td class="c">'+(r.in_payroll? payTag(r.paid?"Paid":"Unpaid") : '<span class="tag">Not in payroll</span>')+'</td>'+
          '<td class="m">'+esc(r.run_ref||"—")+'</td>'+
          '<td class="c">'+(r.editable?'<span style="white-space:nowrap"><button type="button" class="btn sm" data-editday data-row="'+esc(r.rowname||"")+'" data-qty="'+(r.qty||0)+'">Edit</button></span>':"")+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><th>'+fmt(t.days)+' days</th><th></th>'+
         '<th class="n">'+fmt(t.qty)+'</th><th class="n">'+fmt(t.rate,2)+' avg</th><th class="n">'+fmt(t.amount,2)+'</th>'+
         '<th class="c" colspan="3">'+(t.unpaid_amt>0.001? fmt(t.unpaid_amt,2)+' unpaid':'fully paid')+'</th></tr></tfoot></table></div>'+
      '</div>';
    });
    h+='</div>';

    // ════ TAB 3 · PAYMENTS ════
    h+='<div class="wr-sec" id="wr-pay" style="display:none">';
    h+='<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">'+
      '<div class="kpi" style="--kc:var(--warn)"><div class="k">Payable now</div><div class="v">'+fmt(k.unpaid_amt,2)+'</div><div class="u">KES · confirmed, unpaid</div></div>'+
      '<div class="kpi" style="--kc:var(--good)"><div class="k">Paid to date</div><div class="v">'+fmt(k.paid_amt,2)+'</div><div class="u">KES · this window</div></div>'+
      '<div class="kpi"><div class="k">Runs</div><div class="v">'+fmt(runs.length)+'</div><div class="u">payment runs</div></div>'+
    '</div>';
    if(k.unpaid_amt>0.001){
      h+='<div class="banner info" style="margin-top:14px"><b>Ready to pay.</b> “Approve &amp; send to accounts” below creates a payment run for this worker alone ('+money(k.unpaid_amt)+') and hands it to accounts for release.</div>';
    }
    h+='<div class="sech" style="margin-top:16px">Payment runs including this worker</div>';
    if(!runs.length){ h+='<div class="empty">Not included in any payment run yet.</div>'; }
    else{
      h+='<div class="tablewrap"><table><thead><tr>'+
        '<th>Run</th><th>Title</th><th>Date</th><th class="n">Days</th><th class="n">Amount</th><th class="c">Status</th></tr></thead><tbody>';
      runs.forEach(function(r){
        h+='<tr><td><span class="rowlink" data-run="'+esc(r.run)+'">'+esc(r.run)+'</span></td>'+
          '<td>'+esc(r.title||"—")+'</td><td class="m">'+esc(dshort(r.date))+'</td>'+
          '<td class="n m">'+fmt(r.days)+'</td><td class="n m">'+fmt(r.amount,2)+'</td>'+
          '<td class="c">'+stateTag(r.state)+'</td></tr>';
      });
      h+='</tbody></table></div>';
    }
    h+='</div>';

    // ════ TAB 4 · DISCREPANCIES ════
    h+='<div class="wr-sec" id="wr-disc" style="display:none">';
    if(!nIss){
      h+='<div class="empty"><b>Clean.</b> No attendance conflicts on any of this worker\'s day-rows in this window.</div>';
    } else {
      h+='<div class="hint" style="margin-bottom:12px">Day-rows whose pay conflicts with this worker\'s attendance evidence. Presence key: <b style="color:#0a7a43">in 06:42</b> check-in time · <b style="color:#0a7a43">P</b> marked present (no scan) · <b style="color:#b91c1c">absent</b> marked Absent · <b style="color:#a06000">?</b> no record either way. Fix the day with <b>Edit</b> in Work &amp; days, or override knowingly — every send to accounts is logged.</div>';
      var wsc2=ISS.absent.filter(function(r){ return r.scan_in; }).length;
      var groups=[
        {k:"absent", title:"Recorded on marked-Absent days", about:"Submitted attendance says Absent, yet work is recorded. "+(wsc2?wsc2+" of these days HAVE a scan — the attendance record itself is probably wrong; ask HR to correct it.":"No scans on these days — scrutinise the entries."), rows:ISS.absent},
        {k:"ghost", title:"No presence evidence at all", about:"No scan and no attendance record of any kind on the day.", rows:ISS.ghost},
        {k:"leave", title:"Earning while on approved leave", about:"The day falls inside an approved leave application — possible double payment.", rows:ISS.leave},
        {k:"off", title:"Work on off days / holidays", about:"The day is on this worker\'s holiday list. Fine if deliberate overtime.", rows:ISS.off}
      ];
      groups.forEach(function(g){
        if(!g.rows.length) return;
        var gamt=0; g.rows.forEach(function(r){ gamt+=(r.amount||0); });
        h+='<div style="border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden">'+
          '<div style="padding:11px 16px;background:var(--wash);display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline">'+
            '<b style="font-size:12.5px;color:#b91c1c">&#9873; '+esc(g.title)+'</b>'+
            '<span class="m" style="font-weight:700">'+fmt(g.rows.length)+' day-row'+(g.rows.length>1?'s':'')+'</span>'+
            '<span class="m" style="font-weight:600">'+money(gamt)+'</span></div>'+
          '<div style="padding:6px 16px 0;font-size:11px;color:var(--mute)">'+esc(g.about)+'</div>'+
          '<div class="tablescroll" style="max-height:260px;padding:8px 16px 12px"><table style="margin-top:0"><thead><tr>'+
          '<th>Day</th><th>Task</th><th class="n">Qty</th><th class="n">Pay KES</th><th class="c">Presence</th>'+(g.k==="leave"?'<th>Leave</th>':'')+'<th class="c">Paid</th><th>Doc</th></tr></thead><tbody>';
        g.rows.forEach(function(r){
          h+='<tr><td class="m">'+esc(dshort(r.wdate))+'</td><td>'+esc(r.task||"")+'</td>'+
            '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.amount,2)+'</td>'+
            '<td class="c m">'+discPres(r)+'</td>'+
            (g.k==="leave"?('<td>'+esc(r.day_leave||"")+'</td>'):'')+
            '<td class="c">'+payTag(r.paid?"Paid":"Unpaid")+'</td>'+
            '<td class="m" style="font-size:10px">'+esc(r.actuals||"")+'</td></tr>';
        });
        h+='</tbody></table></div></div>';
      });
    }
    h+='</div>';

    el("pd-body").innerHTML=h;
    // tab wiring
    var tabs=el("wr-tabs");
    tabs.querySelectorAll(".fchip").forEach(function(c){
      c.onclick=function(){
        tabs.querySelectorAll(".fchip").forEach(function(x){ x.classList.remove("on"); });
        c.classList.add("on");
        var target=c.getAttribute("data-wrtab");
        el("pd-body").querySelectorAll(".wr-sec").forEach(function(sec){
          sec.style.display=(sec.id===target)?"":"none";
        });
      };
    });
    el("pd-body").querySelectorAll("[data-run]").forEach(function(a){
      a.onclick=function(){ openRunDetail(a.getAttribute("data-run")); };
    });
    var xb=el("wr-excel");
    if(xb){ xb.onclick=function(){ exportWorkerExcel(xb); }; }
    if(WR.targetTab){
      var tt=tabs.querySelector('.fchip[data-wrtab="'+WR.targetTab+'"]');
      if(tt) tt.onclick ? tt.onclick() : tt.click();
      WR.targetTab=null;
    }
    wireDayEdits(el("pd-body"), info);
    // footer: review first, then approve — one worker at a time
    var ap=el("pd-approve"), rv=el("pd-review");
    var unpaid=k.unpaid_amt||0, unreviewed=k.unreviewed_amt||0;
    if(rv){
      if(unpaid>0.001 && unreviewed>0.001){
        rv.style.display="";
        rv.textContent="Mark reviewed · "+money(unpaid);
        rv.onclick=function(){
          rv.disabled=true;
          call({ action:"pay_worker_review", employee:info.employee, from_date:WR.from, to_date:WR.to }, true)
            .then(function(d){
              rv.disabled=false;
              if(d.error){ toast(d.error,"bad"); return; }
              toast((info.employee_name||info.employee)+" marked reviewed — now approve & send to accounts","good");
              openWorkerReview(info.employee, WR);
              if(WR.refresh) WR.refresh();
            })
            .catch(function(e){ rv.disabled=false; toast("Could not mark reviewed: "+e.message,"bad"); });
        };
      } else {
        rv.style.display="none"; rv.onclick=null;
      }
    }
    if(ap){
      if(unpaid>0.001 && unreviewed<=0.001){
        ap.style.display="";
        ap.textContent="Approve & send "+money(unpaid)+" to accounts";
        ap.onclick=function(){
          approveWorker(info.employee, info.employee_name||info.employee, unpaid, WR);
        };
      } else {
        ap.style.display="none"; ap.onclick=null;
      }
    }
  }

  // presence evidence for one day-row: P (scan/manual), A (marked Absent —
  // yet work is recorded, worth a second look), ? (no record either way)
  function presenceTag(r){
    if(r.scan_in) return '<span style="color:#0a7a43;font-weight:700" title="scanned in at '+esc(r.scan_in)+'">P · '+esc(r.scan_in)+'</span>';
    if((r.att_status||"")==="Absent") return '<span style="color:#b91c1c;font-weight:700" title="marked Absent this day — yet work is recorded; review before paying">A · absent</span>';
    if(r.att_status) return '<span style="color:#0a7a43;font-weight:700" title="attendance: '+esc(r.att_status)+'">P</span>';
    return '<span style="color:#a06000;font-weight:700" title="no scan and no attendance record — presence unknown">?</span>';
  }

  function wireDayEdits(scope, info){
    scope.querySelectorAll("[data-editday]").forEach(function(b){
      b.onclick=function(){
        var tr=b.closest("tr");
        if(!tr||tr.classList.contains("editing")) return;
        tr.classList.add("editing");
        var qtyCell=tr.querySelector("[data-qcell]");
        var oldHtml=qtyCell.innerHTML;
        var cur=parseFloat(b.getAttribute("data-qty"))||0;
        qtyCell.innerHTML='<input type="number" step="any" min="0" value="'+cur+'" style="width:92px;font-family:inherit;font-size:12px;border:1px solid var(--line);border-radius:8px;padding:5px 8px;text-align:right">';
        var inp=qtyCell.querySelector("input"); inp.focus(); inp.select();
        b.style.display="none";
        var host=b.parentElement;
        var sv=document.createElement("button"); sv.type="button"; sv.className="btn good sm"; sv.textContent="Save";
        var cx=document.createElement("button"); cx.type="button"; cx.className="btn sm"; cx.textContent="Cancel"; cx.style.marginLeft="4px";
        host.appendChild(sv); host.appendChild(cx);
        function done(){ tr.classList.remove("editing"); sv.remove(); cx.remove(); b.style.display=""; }
        cx.onclick=function(){ qtyCell.innerHTML=oldHtml; done(); };
        inp.onkeydown=function(ev){ if(ev.key==="Enter") sv.click(); if(ev.key==="Escape") cx.click(); };
        sv.onclick=function(){
          var nq=parseFloat(inp.value);
          if(isNaN(nq)||nq<0){ toast("Enter a valid quantity","bad"); return; }
          sv.disabled=true;
          call({ action:"pay_worker_edit_day", employee:info.employee,
                 rowname:b.getAttribute("data-row"), qty:nq }, true)
            .then(function(d){
              if(d.error){ toast(d.error,"bad"); sv.disabled=false; return; }
              toast("Corrected: "+fmt(nq)+" × "+fmt(d.rate,2)+" = "+money(d.amount),"good");
              openWorkerReview(info.employee, WR);
              if(WR.refresh) WR.refresh();
            })
            .catch(function(e){ toast("Could not save: "+e.message,"bad"); sv.disabled=false; });
        };
      };
    });
  }

  function approveWorker(emp, nm, amount, win){
    win=win||auditWindow();
    confirmModal(
      "Approve & send to accounts",
      '<p style="margin:0 0 10px">Send <b>'+esc(nm)+'</b>&rsquo;s unpaid confirmed earnings of <b>'+money(amount)+'</b> to accounts?</p>'+
      '<p class="note" style="margin:0">Work window '+esc(win.from||"start")+' &rarr; '+esc(win.to||"today")+
      '. A payment reference is created for this worker alone and handed to accounts as <b>Pending Accounts</b>; when accounts releases it the worker&rsquo;s rows are stamped paid.</p>',
      "Approve & send",
      function(){
        call({ action:"pay_worker_submit", employee:emp, from_date:win.from||"", to_date:win.to||"" }, true)
          .then(function(d){
            if(d.error){ toast(d.error,"bad"); return; }
            toast((d.employee_name||emp)+" · "+money(d.amount)+" sent to accounts ("+d.name+")","good");
            var m=el("pay-detail-modal"); if(m) m.classList.remove("on");
            if(win.refresh) win.refresh();
          })
          .catch(function(e){ toast("Could not submit: "+e.message,"bad"); });
      },
      "good"
    );
  }

  // ── print: opens a clean, self-contained window with both sheets ──
  function printAudit(){
    var r={from:el("au-from").value||"(start)", to:el("au-to").value||"(today)"};
    var farms=Object.keys(AU.farms).length?Object.keys(AU.farms).join(", "):"All farms";
    var t=AU.totals||{};
    function tbl(headers, bodyRows){
      var h='<table><thead><tr>';
      headers.forEach(function(x){ h+='<th>'+x+'</th>'; }); h+='</tr></thead><tbody>';
      bodyRows.forEach(function(cells){ h+='<tr>'; cells.forEach(function(c,i){ h+='<td'+(i>=cells._n?' class="n"':'')+'>'+c+'</td>'; }); h+='</tr>'; });
      return h+'</tbody></table>';
    }
    var sumRows=(AU.summary||[]).map(function(s){
      var a=[esc(s.farm),esc(s.task),esc(s.block||""),esc(s.assignment||""),fmt(s.planned_people),fmt(s.assigned_count),fmt(s.actual_qty),fmt(s.workers),fmt(s.total_pay,2),fmt(s.paid_pay,2),fmt(s.unpaid_pay,2),esc(s.pay_status),esc(s.run_refs||""),esc(s.entered_by||"")];
      a._n=4; return a;
    });
    var detRows=(AU.detail||[]).map(function(d){
      var a=[esc(d.farm),esc(d.task),esc(d.assignment||""),esc(d.emp_name||d.emp),esc(d.emp),esc(d.emp_type||""),esc(d.wdate||""),fmt(d.qty),fmt(d.amount,2),esc(d.pay_status),esc(d.run_ref||"")];
      a._n=7; return a;
    });
    var win=window.open("","_blank");
    if(!win){ alert("Please allow pop-ups to print the audit."); return; }
    var css='body{font-family:Arial,Helvetica,sans-serif;color:#111;margin:24px;font-size:11px}'+
      'h1{font-size:18px;margin:0 0 2px}h2{font-size:13px;margin:22px 0 6px;border-bottom:2px solid #111;padding-bottom:3px}'+
      '.meta{color:#555;font-size:11px;margin-bottom:6px}'+
      'table{border-collapse:collapse;width:100%;margin-bottom:10px}'+
      'th,td{border:1px solid #ccc;padding:4px 6px;text-align:left}'+
      'th{background:#f0f0f0;font-size:9px;text-transform:uppercase;letter-spacing:.04em}'+
      'td.n,th.n{text-align:right}'+
      'tfoot td{font-weight:bold;background:#fafafa}'+
      '@media print{@page{size:landscape;margin:10mm}}';
    var head='<h1>Kaitet — Payroll Audit</h1><div class="meta">Confirmed actuals &middot; work done '+esc(r.from)+' to '+esc(r.to)+' &middot; '+esc(farms)+
      ' &middot; generated '+esc(todayISO())+'</div>'+
      '<div class="meta">Totals: '+fmt(t.tasks)+' tasks &middot; '+fmt(t.worker_days)+' worker-days &middot; KES '+fmt(t.total_pay)+' total ('+fmt(t.paid)+' paid, '+fmt(t.unpaid)+' unpaid)</div>';
    var body='<h2>Summary — by task</h2>'+
      tbl(["Farm","Task","Block","Assignment","Planned","Assigned","Qty","Workers","Total KES","Paid KES","Unpaid KES","Status","Run","Entered by"], sumRows)+
      '<h2>Detail — by worker &amp; day</h2>'+
      tbl(["Farm","Task","Assignment","Worker","ID","Type","Date","Qty","Amount KES","Paid","Run"], detRows);
    win.document.write('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Kaitet Payroll Audit</title><style>'+css+'</style></head><body>'+head+body+
      '<script>window.onload=function(){setTimeout(function(){window.print();},250);};<\/script></body></html>');
    win.document.close();
  }

  // ── worker review sheet → Excel: one table per task with its day rows ──
  function exportWorkerExcel(btn){
    var d=WR.data;
    if(!d){ toast("Nothing loaded to export","bad"); return; }
    var old=btn.textContent; btn.textContent="Preparing…"; btn.style.pointerEvents="none";
    ensureXLSX(function(ok){
      btn.textContent=old; btn.style.pointerEvents="";
      if(!(ok && window.XLSX)){ exportWorkerCSV(d); return; }
      try{ buildWorkerXLSX(d); }
      catch(e){ exportWorkerCSV(d); }
    });
  }

  function workerPeople(t){
    var who=[];
    (t.assigned_by||[]).forEach(function(u){ who.push("Assigned by "+shortUser(u)); });
    (t.fm_approved_by||[]).forEach(function(u){ who.push("FM approved "+shortUser(u)); });
    (t.entered_by||[]).forEach(function(u){ who.push("Captured by "+shortUser(u)); });
    (t.hr_approved_by||[]).forEach(function(u){ who.push("HR approved "+shortUser(u)); });
    (t.gm_approved_by||[]).forEach(function(u){ who.push("GM approved "+shortUser(u)); });
    return who.join(" · ");
  }

  function workerFileBase(d){
    var info=(d&&d.info)||{};
    var nm=(info.employee_name||"worker").replace(/[^A-Za-z0-9]+/g,"_");
    return "Worker_review_"+(info.employee||"")+"_"+nm+"_"+(WR.from||"start")+"_to_"+(WR.to||"today");
  }

  function buildWorkerXLSX(d){
    var info=d.info||{}, k=d.kpi||{}, tasks=d.tasks||[], daily=d.daily||[];
    var byTask={};
    daily.forEach(function(r){
      var kk=(r.task||"")+"|"+(r.block||"")+"|"+(r.farm||"");
      (byTask[kk]=byTask[kk]||[]).push(r);
    });
    // ── sheet 1: worker + window summary ──
    var s1=[
      ["Worker payment review"],
      [],
      ["Worker", info.employee_name||"", "ID", info.employee||""],
      ["Designation", info.designation||"", "Type", info.employment_type||""],
      ["Farm", info.farm||"", "Joined", info.date_of_joining||""],
      ["Window", (WR.from||"start")+" → "+(WR.to||"today"), "Worked", (k.first_day||"")+" → "+(k.last_day||"")],
      [],
      ["Earned KES", k.earned||0, "Paid KES", k.paid_amt||0],
      ["Unpaid KES", k.unpaid_amt||0, "Days worked", k.days||0],
      ["Tasks", tasks.length, "Total qty", k.qty||0],
      [],
      ["Task","Block","Standard","Farm","Worked from","Worked to","Days","Qty","Rate","Amount KES","Unpaid KES","Status"]
    ];
    tasks.forEach(function(t){
      s1.push([t.task||"", t.block||"", t.standard||"", t.farm||"", t.work_from||"", t.work_to||"", t.days||0, t.qty||0,
               Math.round((t.rate||0)*100)/100, t.amount||0, t.unpaid_amt||0, t.pay_status||""]);
    });
    s1.push(["TOTAL","","","","", k.days||0, k.qty||0, "", k.earned||0, k.unpaid_amt||0, ""]);
    // ── sheet 2: one table per task, day rows underneath — the Work & days view ──
    var s2=[];
    tasks.forEach(function(t){
      var kk=(t.task||"")+"|"+(t.block||"")+"|"+(t.farm||"");
      var rows=(byTask[kk]||[]).slice().sort(function(a,b){ return (a.wdate||"")<(b.wdate||"")?-1:1; });
      s2.push([(t.task||"—")+" · "+(t.block||"—")+" · "+(t.farm||""), "", "", "KES "+fmt(t.amount,2), t.pay_status||""]);
      s2.push(["Task period", (t.plan_from||t.work_from||"")+" → "+(t.plan_to||t.work_to||""),
               "Worked", (t.work_from||"")+" → "+(t.work_to||"")+" ("+(t.days||0)+" days)"+(t.standard?(" · standard "+t.standard):"")]);
      if(t.assignments&&t.assignments.length) s2.push(["Assignments", t.assignments.join(", ")]);
      var who=workerPeople(t);
      if(who) s2.push(["Sign-offs", who]);
      s2.push(["Day worked","Presence","Qty done","Rate","Pay KES","Paid","Run"]);
      rows.forEach(function(r){
        var pres = r.scan_in ? ("P (in "+r.scan_in+")") : ((r.att_status||"")==="Absent" ? "A — marked Absent" : (r.att_status ? "P ("+r.att_status+")" : "? no record"));
        s2.push([r.wdate||"", pres, r.qty||0, Math.round((r.rate||0)*100)/100, r.amount||0,
                 r.in_payroll?(r.paid?"Paid":"Unpaid"):"Not in payroll", r.run_ref||""]);
      });
      s2.push([(t.days||0)+" days", t.qty||0, Math.round((t.rate||0)*100)/100+" avg", t.amount||0,
               (t.unpaid_amt>0.001? fmt(t.unpaid_amt,2)+" unpaid":"fully paid"), ""]);
      s2.push([]);
    });
    if(!s2.length) s2.push(["No confirmed work in this window"]);
    var wb=window.XLSX.utils.book_new();
    var ws1=window.XLSX.utils.aoa_to_sheet(s1);
    var ws2=window.XLSX.utils.aoa_to_sheet(s2);
    ws1["!cols"]=[{wch:22},{wch:26},{wch:14},{wch:16},{wch:12},{wch:8},{wch:10},{wch:10},{wch:12},{wch:12},{wch:12}];
    ws2["!cols"]=[{wch:34},{wch:30},{wch:14},{wch:26},{wch:16},{wch:16}];
    window.XLSX.utils.book_append_sheet(wb, ws1, "Summary");
    window.XLSX.utils.book_append_sheet(wb, ws2, "Tasks & days");
    window.XLSX.writeFile(wb, workerFileBase(d)+".xlsx");
  }

  function exportWorkerCSV(d){
    var daily=(d.daily||[]).map(function(r){ return {
      Date:r.wdate||"", Task:r.task||"", Block:r.block||"", Farm:r.farm||"",
      Qty:r.qty||0, Rate:Math.round((r.rate||0)*100)/100, "Pay KES":r.amount||0,
      Status:(r.in_payroll?(r.paid?"Paid":"Unpaid"):"Not in payroll"), Run:r.run_ref||""
    }; });
    if(!daily.length){ toast("No day rows to export","bad"); return; }
    var keys=Object.keys(daily[0]);
    function cell(v){ v=(v==null?"":String(v)); if(/[",\r\n]/.test(v)){ v='"'+v.replace(/"/g,'""')+'"'; } return v; }
    var lines=[keys.join(",")];
    daily.forEach(function(r){ lines.push(keys.map(function(kk){ return cell(r[kk]); }).join(",")); });
    dl(workerFileBase(d)+".csv", lines.join("\r\n"));
    toast("Excel library couldn't load — exported the day log as CSV instead","bad");
  }

  // ── Excel export: real two-sheet .xlsx via SheetJS (lazy CDN load), CSV fallback ──
  function exportAuditExcel(){
    var btn=el("au-xlsx"); var old=btn.textContent; btn.textContent="Preparing…"; btn.disabled=true;
    ensureXLSX(function(ok){
      if(ok && window.XLSX){
        try{ buildXLSX(); }
        catch(e){ exportAuditCSV(); }
      } else {
        exportAuditCSV();
      }
      btn.textContent=old; btn.disabled=false;
    });
  }

  function ensureXLSX(cb){
    if(window.XLSX){ cb(true); return; }
    var s=document.createElement("script");
    s.src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
    s.onload=function(){ cb(true); };
    s.onerror=function(){ cb(false); };
    document.head.appendChild(s);
  }

  function auditFileBase(){
    var f=(el("au-from").value||"start"), t=(el("au-to").value||"today");
    return "Kaitet_Payroll_Audit_"+f+"_to_"+t;
  }

  function buildXLSX(){
    var sum=(AU.summary||[]).map(function(s){ return {
      Farm:s.farm, Task:s.task, Block:s.block||"", Assignment:s.assignment||"",
      "Planner":s.planner_request||"", "From":s.from_date||"", "To":s.to_date||"",
      "Planned people":s.planned_people, "Assigned":s.assigned_count, "Variance":s.variance,
      "Actual qty":s.actual_qty, "Workers":s.workers, "Worker-days":s.worker_days,
      "Total KES":s.total_pay, "Paid KES":s.paid_pay, "Unpaid KES":s.unpaid_pay,
      "Status":s.pay_status, "Run(s)":s.run_refs||"", "Entered by":s.entered_by||"", "Entry date":s.entry_date||""
    }; });
    var det=(AU.detail||[]).map(function(d){ return {
      Farm:d.farm, Task:d.task, Block:d.block||"", Assignment:d.assignment||"",
      Worker:d.emp_name||d.emp, "ID":d.emp, "Type":d.emp_type||"", "Date":d.wdate||"",
      "Qty":d.qty, "Amount KES":d.amount, "In payroll":d.in_payroll, "Paid":d.pay_status, "Run":d.run_ref||""
    }; });
    var wb=window.XLSX.utils.book_new();
    var ws1=window.XLSX.utils.json_to_sheet(sum);
    var ws2=window.XLSX.utils.json_to_sheet(det);
    window.XLSX.utils.book_append_sheet(wb, ws1, "Summary");
    window.XLSX.utils.book_append_sheet(wb, ws2, "Detail");
    window.XLSX.writeFile(wb, auditFileBase()+".xlsx");
  }

  // CSV fallback (two files) if the Excel library can't load on this network
  function exportAuditCSV(){
    function toCSV(rows){
      if(!rows.length) return "";
      var keys=Object.keys(rows[0]);
      var lines=[keys.map(csvCell).join(",")];
      rows.forEach(function(r){ lines.push(keys.map(function(k){ return csvCell(r[k]); }).join(",")); });
      return lines.join("\r\n");
    }
    function csvCell(v){ v=(v==null?"":String(v)); if(/[",\r\n]/.test(v)){ v='"'+v.replace(/"/g,'""')+'"'; } return v; }
    var sum=(AU.summary||[]).map(function(s){ return {
      Farm:s.farm,Task:s.task,Block:s.block||"",Assignment:s.assignment||"",Planner:s.planner_request||"",
      From:s.from_date||"",To:s.to_date||"","Planned people":s.planned_people,Assigned:s.assigned_count,Variance:s.variance,
      "Actual qty":s.actual_qty,Workers:s.workers,"Worker-days":s.worker_days,"Total KES":s.total_pay,
      "Paid KES":s.paid_pay,"Unpaid KES":s.unpaid_pay,Status:s.pay_status,"Run(s)":s.run_refs||"","Entered by":s.entered_by||"","Entry date":s.entry_date||""
    }; });
    var det=(AU.detail||[]).map(function(d){ return {
      Farm:d.farm,Task:d.task,Block:d.block||"",Assignment:d.assignment||"",Worker:d.emp_name||d.emp,ID:d.emp,
      Type:d.emp_type||"",Date:d.wdate||"",Qty:d.qty,"Amount KES":d.amount,"In payroll":d.in_payroll,Paid:d.pay_status,Run:d.run_ref||""
    }; });
    dl(auditFileBase()+"_summary.csv", toCSV(sum));
    dl(auditFileBase()+"_detail.csv", toCSV(det));
    alert("Excel library couldn't load on this network, so the audit was exported as two CSV files (summary + detail). They open directly in Excel.");
  }

  function dl(name, text){
    var blob=new Blob(["﻿"+text], {type:"text/csv;charset=utf-8;"});
    var url=URL.createObjectURL(blob);
    var a=document.createElement("a"); a.href=url; a.download=name; document.body.appendChild(a); a.click();
    setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 400);
  }

  function stateTag(s){
    s=s||"Draft";
    var cls="unpaid";
    if(s==="Paid") cls="paid";
    else if(s==="Pending Accounts") cls="pending";
    else if(s==="Rejected") cls="submitted";
    var label = s==="Pending Accounts" ? "Pending accounts" : s;
    return '<span class="tag '+cls+'">'+esc(label)+'</span>';
  }

  // ════════════════════════════════════════════════
  //  RUN DETAIL (shared, read-only lines) — via wm_dashboard.payment_detail
  //  wm_payment has no line-detail action; the dashboard endpoint does.
  // ════════════════════════════════════════════════
  function openRunDetail(name){
    var m=el("pay-run-modal");
    el("pr-title").firstChild.textContent="Payment run";
    el("pr-sub").textContent=name;
    el("pr-body").innerHTML='<div class="loading">Loading lines…</div>';
    el("pr-foot").innerHTML='<button type="button" class="btn" id="pr-dismiss">Close</button>';
    el("pr-dismiss").onclick=function(){ m.classList.remove("on"); };
    m.classList.add("on");
    fetch("/api/method/wm_dashboard?action=payment_detail&payment="+encodeURIComponent(name),
      { headers:{ "Accept":"application/json" }, credentials:"same-origin" })
      .then(function(r){ return r.json(); })
      .then(function(j){
        var d=j.message||{};
        var p=d.payment||{}; var lines=d.lines||[];
        el("pr-title").firstChild.textContent=p.run_title||name;
        el("pr-sub").textContent=name+" · "+stateText(p.workflow_state);
        var h='';
        h+='<div class="rc-figs" style="padding:0 0 14px;border-bottom:1px solid var(--faint);margin-bottom:14px">'+
           '<div class="rc-fig"><div class="rf-k">Workers</div><div class="rf-v">'+fmt(p.total_workers)+'</div></div>'+
           '<div class="rc-fig"><div class="rf-k">Grand total</div><div class="rf-v">'+money(p.grand_total)+'</div></div>'+
           '<div class="rc-fig"><div class="rf-k">Period</div><div class="rf-v" style="font-size:13px">'+esc(p.period_from||"?")+' → '+esc(p.period_to||"?")+'</div></div>'+
           '</div>';
        if(!lines.length){
          h+='<div class="empty">No payment lines recorded on this run.</div>';
        } else {
          h+='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
             '<th>Worker</th><th>Farm</th><th class="n">Days</th><th class="n">Qty</th><th class="n">Amount</th></tr></thead><tbody>';
          lines.forEach(function(ln){
            h+='<tr><td>'+esc(ln.employee_name||ln.employee||"")+'</td><td>'+esc(lbl(ln.farm)||"")+'</td>'+
               '<td class="n m">'+fmt(ln.days)+'</td><td class="n m">'+fmt(ln.qty)+'</td><td class="n m">'+money(ln.amount)+'</td></tr>';
          });
          h+='</tbody><tfoot><tr><td colspan="4">Grand total</td><td class="n m">'+money(p.grand_total)+'</td></tr></tfoot></table></div></div>';
        }
        el("pr-body").innerHTML=h;
        // if this run is pending and the user is accounts, offer mark-paid from the modal too
        if(p.workflow_state==="Pending Accounts" && ST.isAccounts){
          var foot=el("pr-foot");
          foot.innerHTML='<button type="button" class="btn" id="pr-dismiss">Close</button>'+
                         '<button type="button" class="btn good" id="pr-paid">Mark paid</button>';
          el("pr-dismiss").onclick=function(){ m.classList.remove("on"); };
          el("pr-paid").onclick=function(){ m.classList.remove("on"); markPaid(name); };
        }
      })
      .catch(function(){ el("pr-body").innerHTML='<div class="err">Could not load run lines.</div>'; });
  }
  function stateText(s){ return s==="Pending Accounts"?"Pending accounts":(s||"Draft"); }

  // ════════════════════════════════════════════════
  //  CONFIRM MODAL (generic)
  // ════════════════════════════════════════════════
  function confirmModal(title, bodyHtml, goLabel, onConfirm, goKind){
    var m=el("pay-confirm-modal");
    el("pc-title").textContent=title;
    el("pc-body").innerHTML=bodyHtml;
    var go=el("pc-go");
    go.textContent=goLabel||"Confirm";
    go.className="btn "+(goKind==="good"?"good":"pay");
    go.onclick=function(){ m.classList.remove("on"); onConfirm&&onConfirm(); };
    el("pc-cancel").onclick=function(){ m.classList.remove("on"); };
    el("pc-x").onclick=function(){ m.classList.remove("on"); };
    m.classList.add("on");
  }

  // ── accounts badge on the tab ──
  function updateAccBadge(){
    var b=el("tab-acc-cnt");
    if(!b) return;
    if(ST.accCount>0){ b.textContent=ST.accCount; b.style.display="inline-block"; }
    else { b.style.display="none"; }
  }
  function refreshAccountsCount(){
    call({ action:"pay_pending" }).then(function(d){
      ST.accCount=(d.pending||[]).length; updateAccBadge();
    }).catch(function(){});
  }

  // ════════════════════════════════════════════════
  //  INIT
  // ════════════════════════════════════════════════
  function wireModalsBackdrop(){
    ["pay-detail-modal","pay-run-modal","pay-confirm-modal"].forEach(function(id){
      var m=el(id);
      m.addEventListener("click", function(e){ if(e.target===m) m.classList.remove("on"); });
    });
    el("pd-close").onclick=function(){ el("pay-detail-modal").classList.remove("on"); };
    el("pd-dismiss").onclick=function(){ el("pay-detail-modal").classList.remove("on"); };
    el("pr-close").onclick=function(){ el("pay-run-modal").classList.remove("on"); };
    document.addEventListener("keydown", function(e){
      if(e.key==="Escape"){
        ["pay-detail-modal","pay-run-modal","pay-confirm-modal"].forEach(function(id){ el(id).classList.remove("on"); });
      }
    });
  }

  function init(){
    // date defaults: month-to-date
    el("pf-from").value=monthStartISO();
    el("pf-to").value=todayISO();

    // tabs
    document.querySelectorAll("#pay-tabs button").forEach(function(b){
      b.onclick=function(){ showTab(b.getAttribute("data-tab")); };
    });

    // build filters
    el("pf-apply").onclick=loadPayable;
    el("pf-reset").onclick=function(){
      el("pf-from").value=monthStartISO();
      el("pf-to").value=todayISO();
      el("pf-search").value="";
      ST.activeFarms={};
      loadPayable();
    };
    el("pf-search").addEventListener("input", function(){ if(ST.workers.length) renderPayable({}); });

    // dock
    if(el("dk-clear")) el("dk-clear").onclick=clearPicks;
    if(el("dk-create")) el("dk-create").onclick=createRun;

    wireModalsBackdrop();

    // roles (gate mark-paid) then first load
    call({ action:"pay_roles" }).then(function(d){
      ST.isAccounts=!!d.is_accounts;
      el("pay-who").textContent=(d.user||"")+(d.is_accounts?" · accounts":"");
    }).catch(function(){}).then(function(){
      refreshAccountsCount();
      showTab("build");
    });
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
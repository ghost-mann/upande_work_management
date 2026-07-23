(function(){
  "use strict";
  var API = "/api/method/wm_payment";

  // ── shared state ──
  var ST = {
    workers: [],        // current payable list (from pay_workers)
    picked: {},         // employee -> row, selected for the run
    farms: [],          // [{farm, workers, owed}] summary across window
    activeFarms: {},    // farm -> 1 (chip filter); empty = all
    isAccounts: false,
    accCount: 0
  };

  // ── tiny helpers ──
  function el(id){ return document.getElementById(id); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function money(n){ if(n==null||isNaN(n)) return "—"; return "KES "+fmt(n); }
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
    var h='<div class="tablewrap"><div class="tablescroll"><table><thead><tr>'+
      '<th>Worker</th><th>ID</th><th>Farm</th><th>Period worked</th><th class="n">Days</th><th class="n">Qty</th>'+
      '<th class="n">Earned KES</th><th class="n">Unpaid KES</th><th class="c">Status</th><th class="c">Actions</th></tr></thead><tbody>';
    rows.forEach(function(w){
      var unpaid=w.unpaid_amt!=null?w.unpaid_amt:w.owed;
      var acts='<button type="button" class="btn sm" data-review="'+esc(w.emp)+'">Review</button>';
      if(w.pay_status==="Reviewed"){
        acts+=' <button type="button" class="btn good sm" data-send="'+esc(w.emp)+'" data-nm="'+esc(w.emp_name||w.emp)+'" data-amt="'+(unpaid||0)+'">Send to accounts</button>';
      } else if(w.pay_status==="Unpaid"){
        acts+=' <button type="button" class="btn sm" disabled title="Review this worker first — approval unlocks after review" style="opacity:.45">Send to accounts</button>';
      }
      var runRef=w.run_ref?('<div style="font-size:9px;color:var(--mute);margin-top:2px">'+esc(w.run_ref)+'</div>'):'';
      h+='<tr class="'+(w.pay_status==="Paid"?"notpay":"")+'">'+
        '<td><span class="rowlink" data-review="'+esc(w.emp)+'">'+esc(w.emp_name||w.emp)+'</span></td>'+
        '<td class="m">'+esc(w.emp)+'</td>'+
        '<td>'+esc(w.farm||"—")+'</td>'+
        '<td class="m">'+esc(dshort(w.wfrom))+' &rarr; '+esc(dshort(w.wto))+'</td>'+
        '<td class="n m">'+fmt(w.days)+'</td>'+
        '<td class="n m">'+fmt(w.qty)+'</td>'+
        '<td class="n m">'+money(w.owed)+'</td>'+
        '<td class="n m">'+money(unpaid)+'</td>'+
        '<td class="c">'+payTag(w.pay_status)+runRef+'</td>'+
        '<td class="c" style="white-space:nowrap">'+acts+'</td></tr>';
    });
    h+='</tbody></table></div></div>';
    h+='<div class="note">Unpaid &rarr; review the worker &middot; Reviewed &rarr; send to accounts &middot; Sent &rarr; accounts releases &middot; Paid. Each send creates a single-worker payment reference automatically.</div>';
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
    var foot='<button type="button" class="btn sm" data-view="'+esc(r.name)+'">View lines</button>';
    if(canPay){
      foot+='<button type="button" class="btn good sm" data-paid="'+esc(r.name)+'">Mark paid</button>';
    }
    return '<div class="runcard">'+
      '<div class="rc-head">'+
        '<div><div class="rc-title">'+esc(r.run_title||r.name)+'</div>'+
        '<div class="rc-sub">'+esc(r.name)+' · prepared by '+esc(r.prepared_by||"—")+' · '+esc(r.run_date||"")+'</div></div>'+
        '<span class="tag pending">Pending accounts</span>'+
      '</div>'+
      '<div class="rc-figs">'+
        '<div class="rc-fig"><div class="rf-k">Workers</div><div class="rf-v">'+fmt(r.total_workers)+'</div></div>'+
        '<div class="rc-fig"><div class="rf-k">Grand total</div><div class="rf-v">'+money(r.grand_total)+'</div></div>'+
      '</div>'+
      '<div class="rc-foot">'+foot+'</div>'+
    '</div>';
  }

  function wireRunCards(box){
    box.querySelectorAll("[data-view]").forEach(function(b){
      b.onclick=function(){ openRunDetail(b.getAttribute("data-view")); };
    });
    box.querySelectorAll("[data-paid]").forEach(function(b){
      b.onclick=function(){ markPaid(b.getAttribute("data-paid")); };
    });
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
      AU.wired = true;
    }
    setAuditViewButtons();
    if(!AU.loaded) loadAudit();
  }

  function setAuditView(v){ AU.view=v; setAuditViewButtons(); renderAudit(); }
  function setAuditViewButtons(){
    var s=el("au-v-summary"), d=el("au-v-detail"), w=el("au-v-workers");
    if(s) s.classList.toggle("pay", AU.view==="summary");
    if(d) d.classList.toggle("pay", AU.view==="detail");
    if(w) w.classList.toggle("pay", AU.view==="workers");
  }

  function auFarmsCSV(){ var k=Object.keys(AU.farms); return k.length?k.join(","):""; }

  function loadAudit(){
    var box=el("audit-body");
    box.innerHTML='<div class="loading">Building audit&hellip;</div>';
    var r={from:el("au-from").value||"", to:el("au-to").value||""};
    call({action:"pay_audit", from_date:r.from, to_date:r.to, farms:auFarmsCSV()}).then(function(d){
      AU.summary=d.summary||[]; AU.detail=d.detail||[]; AU.totals=d.totals||null; AU.loaded=true;
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
    else renderAuditDetail(box);
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
        '<td class="n m">'+fmt(s.total_pay)+'</td><td class="n m">'+fmt(s.paid_pay)+'</td><td class="n m">'+fmt(s.unpaid_pay)+'</td>'+
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
        '<td>'+esc(r.wdate||"")+'</td><td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.amount)+'</td>'+
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
         '<th class="n">'+fmt(tq)+'</th><th class="n">'+fmt(te)+'</th><th class="n">'+fmt(tp)+'</th><th class="n">'+fmt(tu)+'</th>'+
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
  function openWorkerReview(emp, win){
    WR=win||{from:"",to:"",refresh:null};
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
    var info=d.info||{}, k=d.kpi||{};
    el("pd-name").firstChild.textContent=info.employee_name||info.employee||"Worker";
    el("pd-sub").textContent=(info.employee||"")+" · "+(info.designation||info.employment_type||"")+
      (info.farm?" · "+lbl(info.farm):"");
    var tasks=d.tasks||[], daily=d.daily||[], runs=d.runs||[];
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
      '<div class="kpi" style="--kc:var(--pay)"><div class="k">Earned</div><div class="v">'+fmt(k.earned)+'</div><div class="u">KES · window</div></div>'+
      '<div class="kpi" style="--kc:var(--good)"><div class="k">Paid</div><div class="v">'+fmt(k.paid_amt)+'</div><div class="u">KES</div></div>'+
      '<div class="kpi" style="--kc:var(--warn)"><div class="k">Unpaid</div><div class="v">'+fmt(k.unpaid_amt)+'</div><div class="u">KES · payable</div></div>'+
      '<div class="kpi" style="--kc:var(--blue)"><div class="k">Days</div><div class="v">'+fmt(k.days)+'</div><div class="u">worked</div></div>'+
      '<div class="kpi"><div class="k">Tasks</div><div class="v">'+fmt(tasks.length)+'</div><div class="u">'+fmt(k.qty)+' units total</div></div>'+
      '<div class="kpi"><div class="k">Avg / day</div><div class="v">'+fmt(k.avg_per_day)+'</div><div class="u">KES</div></div>'+
    '</div>';
    h+='<div class="sech" style="margin-top:16px">Tasks in this window <span class="hint">totals per task — open Work &amp; days for the day-by-day record</span></div>';
    if(!tasks.length){ h+='<div class="empty">No confirmed work in this window.</div>'; }
    else{
      h+='<div class="tablewrap"><table><thead><tr>'+
        '<th>Task</th><th>Block</th><th>Period worked</th><th class="n">Days</th><th class="n">Qty</th>'+
        '<th class="n">Rate</th><th class="n">Amount KES</th><th class="n">Unpaid</th><th class="c">Status</th></tr></thead><tbody>';
      tasks.forEach(function(t){
        h+='<tr><td><b>'+esc(t.task||"—")+'</b></td><td>'+esc(lbl(t.block)||"—")+'</td>'+
          '<td class="m">'+esc(dshort(t.work_from))+' &rarr; '+esc(dshort(t.work_to))+'</td>'+
          '<td class="n m">'+fmt(t.days)+'</td><td class="n m">'+fmt(t.qty)+'</td><td class="n m">'+fmt(t.rate,2)+'</td>'+
          '<td class="n m">'+fmt(t.amount)+'</td><td class="n m">'+fmt(t.unpaid_amt)+'</td>'+
          '<td class="c">'+payTag(t.pay_status)+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><th colspan="3">TOTAL</th><th class="n">'+fmt(k.days)+'</th><th class="n">'+fmt(k.qty)+'</th><th></th>'+
         '<th class="n">'+fmt(k.earned)+'</th><th class="n">'+fmt(k.unpaid_amt)+'</th><th></th></tr></tfoot></table></div>';
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
    h+='<div class="hint" style="margin-bottom:12px">One card per task. Under it, every day this worker’s output was recorded in Actuals — a day-row means “this person did this quantity on this date”.</div>';
    if(!tasks.length){ h+='<div class="empty">No confirmed work in this window.</div>'; }
    tasks.forEach(function(t){
      var kk=(t.task||"")+"|"+(t.block||"")+"|"+(t.farm||"");
      var rows=(byTask[kk]||[]).slice().sort(function(a,b){ return (a.wdate||"")<(b.wdate||"")?-1:1; });
      var who=peopleLine(t).map(function(w){ return w[0]+" "+shortUser(w[1]); });
      h+='<div style="border:1px solid var(--line);border-radius:14px;margin-bottom:14px;overflow:hidden">'+
        '<div style="padding:12px 16px;background:var(--wash);display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline">'+
          '<div style="font-weight:600;font-size:13px">'+esc(t.task||"—")+' <span style="color:var(--mute);font-weight:500">· '+esc(lbl(t.block)||"—")+' · '+esc(lbl(t.farm)||"")+'</span></div>'+
          '<span style="flex:1"></span>'+
          '<span class="m" style="font-weight:600">'+money(t.amount)+'</span>'+payTag(t.pay_status)+
        '</div>'+
        '<div style="padding:8px 16px;border-top:1px solid var(--faint);font-size:11px;color:var(--mute);display:flex;flex-wrap:wrap;gap:4px 18px">'+
          '<span><b style="color:var(--ink)">Task period:</b> '+esc(dshort(t.plan_from)||dshort(t.work_from))+' &rarr; '+esc(dshort(t.plan_to)||dshort(t.work_to))+'</span>'+
          '<span><b style="color:var(--ink)">Worked:</b> '+esc(dshort(t.work_from))+' &rarr; '+esc(dshort(t.work_to))+' ('+fmt(t.days)+' day'+(t.days===1?'':'s')+')</span>'+
          ((t.assignments&&t.assignments.length)?'<span><b style="color:var(--ink)">Assignment'+(t.assignments.length>1?'s':'')+':</b> '+esc(t.assignments.join(", "))+'</span>':'')+
          ((t.runs&&t.runs.length)?'<span><b style="color:var(--ink)">Run'+(t.runs.length>1?'s':'')+':</b> '+esc(t.runs.join(", "))+'</span>':'')+
        '</div>'+
        (who.length?'<div style="padding:0 16px 8px;font-size:11px;color:var(--mute)">'+esc(who.join("  ·  "))+'</div>':'')+
        '<div class="tablescroll" style="max-height:320px"><table style="margin-top:0"><thead><tr>'+
          '<th>Day worked</th><th class="n">Qty done</th><th class="n">Rate</th><th class="n">Pay KES</th><th class="c">Paid</th><th>Run</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr><td class="m">'+esc(dshort(r.wdate))+'</td>'+
          '<td class="n m">'+fmt(r.qty)+'</td><td class="n m">'+fmt(r.rate,2)+'</td><td class="n m">'+fmt(r.amount)+'</td>'+
          '<td class="c">'+(r.in_payroll? payTag(r.paid?"Paid":"Unpaid") : '<span class="tag">Not in payroll</span>')+'</td>'+
          '<td class="m">'+esc(r.run_ref||"—")+'</td></tr>';
      });
      h+='</tbody><tfoot><tr><th>'+fmt(t.days)+' days</th>'+
         '<th class="n">'+fmt(t.qty)+'</th><th class="n">'+fmt(t.rate,2)+' avg</th><th class="n">'+fmt(t.amount)+'</th>'+
         '<th class="c" colspan="2">'+(t.unpaid_amt>0.001? fmt(t.unpaid_amt)+' unpaid':'fully paid')+'</th></tr></tfoot></table></div>'+
      '</div>';
    });
    h+='</div>';

    // ════ TAB 3 · PAYMENTS ════
    h+='<div class="wr-sec" id="wr-pay" style="display:none">';
    h+='<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">'+
      '<div class="kpi" style="--kc:var(--warn)"><div class="k">Payable now</div><div class="v">'+fmt(k.unpaid_amt)+'</div><div class="u">KES · confirmed, unpaid</div></div>'+
      '<div class="kpi" style="--kc:var(--good)"><div class="k">Paid to date</div><div class="v">'+fmt(k.paid_amt)+'</div><div class="u">KES · this window</div></div>'+
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
          '<td class="n m">'+fmt(r.days)+'</td><td class="n m">'+fmt(r.amount)+'</td>'+
          '<td class="c">'+stateTag(r.state)+'</td></tr>';
      });
      h+='</tbody></table></div>';
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
              toast((info.employee_name||info.employee)+" marked reviewed","good");
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
      var a=[esc(s.farm),esc(s.task),esc(s.block||""),esc(s.assignment||""),fmt(s.planned_people),fmt(s.assigned_count),fmt(s.actual_qty),fmt(s.workers),fmt(s.total_pay),fmt(s.paid_pay),fmt(s.unpaid_pay),esc(s.pay_status),esc(s.run_refs||""),esc(s.entered_by||"")];
      a._n=4; return a;
    });
    var detRows=(AU.detail||[]).map(function(d){
      var a=[esc(d.farm),esc(d.task),esc(d.assignment||""),esc(d.emp_name||d.emp),esc(d.emp),esc(d.emp_type||""),esc(d.wdate||""),fmt(d.qty),fmt(d.amount),esc(d.pay_status),esc(d.run_ref||"")];
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
(function(){
  var ST = { plan:null, planDetail:null, employees:[], picked:{}, roles:null, planList:[] };

  function call(args){
    var writes = {a_submit:1, a_fm_approve:1, a_hr_approve:1, a_gm_approve:1, a_reject:1, a_substitute:1};
    var isWrite = writes[args.action] === 1;
    var p = new URLSearchParams();
    for(var k in args){ if(args[k]!==undefined && args[k]!==null) p.append(k, args[k]); }
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    if(!isWrite){
      return fetch("/api/method/wm_assigner?" + p.toString(), { method:"GET", headers:{ "Accept":"application/json" }, credentials:"same-origin" })
        .then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){ return j.message || {}; });
    }
    return fetch("/api/method/wm_assigner", {
      method:"POST",
      headers:{ "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body:p.toString(),
      credentials:"same-origin"
    }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){ return j.message || {}; });
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function blocksLbl(obj){ var a=(obj&&obj.blocks)||null; if(a&&a.length){ var o=[]; for(var i=0;i<a.length;i++){ o.push(lbl(a[i])); } return o.join(", "); } return lbl(obj&&obj.block_section); }
  function el(id){ return document.getElementById(id); }
  function isoTodayA(){ var d=new Date(); function p(n){ return (n<10?"0":"")+n; } return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate()); }
  function toast(m){ var t=el("wa-toast"); t.textContent=m; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2200); }
  function nPicked(){ var n=0; for(var k in ST.picked){ if(ST.picked[k]) n++; } return n; }

  // ── plan close (shared) ─────────────────────────────────
  // The close workflow lives in the wm_actuals script (single source of truth),
  // so we POST there directly rather than duplicating the logic here. GM closes
  // instantly; Farm Manager / Section Head sends a request for the GM to confirm.
  function closeCall(action, assignment, reason){
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    var p=new URLSearchParams();
    p.append("action", action); p.append("assignment", assignment); p.append("reason", reason);
    return fetch("/api/method/wm_actuals", {
      method:"POST",
      headers:{ "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body:p.toString(), credentials:"same-origin"
    }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){ return j.message||{}; });
  }
  function openCloseDialog(assignment, planName, onDone){
    var isGm = ST.roles && ST.roles.is_gm;
    var dlg=el("wa-subdialog");
    var title = isGm ? "Close plan now" : "Request close";
    var desc = isGm
      ? "This finalises any open draft actuals to Confirmed and caps the plan (target kept for reporting). A reason is required."
      : "This sends a close request to the GM. Entry stays open until they confirm. A reason is required.";
    dlg.innerHTML =
      '<div style="background:#fff;max-width:440px;width:92%;border:2px solid var(--ink)">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--faint)">'+
          '<div style="font-size:13px;font-weight:700">'+title+'</div>'+
          '<button type="button" id="wac-x" style="border:none;background:none;font-size:20px;line-height:1;color:var(--mute);cursor:pointer">&times;</button>'+
        '</div>'+
        '<div style="padding:16px 18px">'+
          '<div style="font-size:12px;color:#444;margin-bottom:10px">'+esc(desc)+(planName?(' <span style="color:#777">Plan <b>'+esc(planName)+'</b>.</span>'):'')+'</div>'+
          '<label style="display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600;margin-bottom:5px">Reason (required)</label>'+
          '<textarea id="wac-reason" rows="3" style="font-family:inherit;font-size:13px;border:1px solid var(--line);padding:8px 10px;width:100%;background:#fff;color:var(--ink);resize:vertical" placeholder="e.g. crop finished early, block cleared ahead of target"></textarea>'+
        '</div>'+
        '<div style="display:flex;justify-content:flex-end;gap:10px;padding:14px 18px;border-top:1px solid var(--faint)">'+
          '<button type="button" class="btn" id="wac-cancel">Cancel</button>'+
          '<button type="button" class="btn solid" id="wac-go" disabled>'+(isGm?"Close now":"Send request")+'</button>'+
        '</div>'+
      '</div>';
    dlg.style.display="flex";
    var ta=el("wac-reason"), go=el("wac-go");
    ta.oninput=function(){ go.disabled=!ta.value.trim(); };
    function shut(){ dlg.style.display="none"; dlg.innerHTML=""; }
    el("wac-x").onclick=shut; el("wac-cancel").onclick=shut;
    dlg.onclick=function(ev){ if(ev.target===dlg) shut(); };
    go.onclick=function(){
      var reason=(ta.value||"").trim();
      if(!reason){ toast("A reason is required"); return; }
      go.disabled=true;
      closeCall(isGm?"act_close_confirm":"act_close_request", assignment, reason).then(function(d){
        if(d.error){ toast("Error: "+d.error); go.disabled=false; return; }
        shut();
        toast(isGm ? "Plan closed" : "Close request sent to GM");
        if(typeof onDone==="function") onDone();
      }).catch(function(e){ toast("Close failed"); go.disabled=false; });
    };
  }

  function buildTabs(){
    var tabs=[["assign","Assign"],["amine","My Assignments"],["arej","Rejected"],["aappr","Approvals"]];
    var nav=el("wa-tabs"); nav.innerHTML="";
    tabs.forEach(function(t){
      var b=document.createElement("button");
      b.textContent=t[1]; b.setAttribute("data-tab",t[0]);
      b.onclick=function(){ showTab(t[0]); };
      nav.appendChild(b);
    });
    showTab("assign");
  }
  function showTab(name){
    ["assign","amine","arej","aappr"].forEach(function(n){ var p=el("p-"+n); if(p) p.classList.toggle("on", n===name); });
    document.querySelectorAll("#wa-tabs button").forEach(function(b){ b.setAttribute("aria-selected", b.getAttribute("data-tab")===name); });
    if(name==="amine") loadMine();
    if(name==="arej") loadRejected();
    if(name==="aappr") renderApprovals();
  }
  function apprQueues(){
    return [
      {key:"fm",label:"Farm Manager",stage:"Pending Farm Manager",action:"a_fm_approve"},
      {key:"hr",label:"HR Head",stage:"Pending HR Head",action:"a_hr_approve"},
      {key:"gm",label:"GM",stage:"Pending GM",action:"a_gm_approve"}
    ];
  }
  function renderApprovals(){
    var queues=apprQueues();
    var ok=false, i;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) ok=true; }
    if(!ok) ST._apprKey=queues[0].key;
    var bar=el("wa-appr-subtabs");
    if(bar){
      var h="";
      queues.forEach(function(q){ h+='<button type="button" class="subtab'+(q.key===ST._apprKey?" on":"")+'" data-sub="'+q.key+'">'+q.label+'</button>'; });
      bar.innerHTML=h;
      bar.querySelectorAll("[data-sub]").forEach(function(b){ b.onclick=function(){ ST._apprKey=b.getAttribute("data-sub"); renderApprovals(); }; });
    }
    var q=null;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) q=queues[i]; }
    if(q) loadStage("aappr-body", q.stage, q.action);
  }
  // ---- shared list filter bar (search / farm / status / date range) ----
  function fbar(rows, opts){
    var farms={}; rows.forEach(function(r){ if(r.farm) farms[r.farm]=1; });
    var h='<div class="lfb">'+
      '<input type="text" data-f="q" placeholder="'+esc(opts.ph||"Search…")+'">'+
      '<select data-f="farm"><option value="">All farms</option>'+Object.keys(farms).sort().map(function(f){ return '<option>'+esc(f)+'</option>'; }).join("")+'</select>';
    if(opts.statuses && opts.statuses.length){
      h+='<select data-f="st"><option value="">All statuses</option>'+opts.statuses.map(function(s){ return '<option>'+esc(s)+'</option>'; }).join("")+'</select>';
    }
    if(opts.dates){ h+='<label>From</label><input type="date" data-f="from"><label>To</label><input type="date" data-f="to">'; }
    h+='<button type="button" class="lfb-clear" data-f="clear">Clear</button><span class="lfb-count" data-f="count"></span></div><div class="lfb-body"></div>';
    return h;
  }
  function fwire(box, rows, get, draw){
    var q=box.querySelector('[data-f="q"]'), farm=box.querySelector('[data-f="farm"]'), st=box.querySelector('[data-f="st"]'),
        from=box.querySelector('[data-f="from"]'), to=box.querySelector('[data-f="to"]'),
        clr=box.querySelector('[data-f="clear"]'), cnt=box.querySelector('[data-f="count"]'),
        body=box.querySelector('.lfb-body');
    function apply(){
      var vq=((q&&q.value)||"").trim().toLowerCase(), vf=(farm&&farm.value)||"", vs=(st&&st.value)||"",
          vfrom=(from&&from.value)||"", vto=(to&&to.value)||"";
      var out=rows.filter(function(r){
        var g=get(r);
        if(vf && g.farm!==vf) return false;
        if(vs && g.status!==vs) return false;
        if(vfrom && g.date && g.date<vfrom) return false;
        if(vto && g.date && g.date>vto) return false;
        if(vq && g.hay.indexOf(vq)<0) return false;
        return true;
      });
      if(cnt) cnt.textContent=out.length+" of "+rows.length;
      draw(body, out);
    }
    [q,farm,st,from,to].forEach(function(e){ if(!e) return; if(e.tagName==="INPUT" && e.type==="text"){ e.oninput=apply; } else { e.onchange=apply; } });
    if(clr) clr.onclick=function(){ [q,farm,st,from,to].forEach(function(e){ if(e) e.value=""; }); apply(); };
    apply();
  }
  function isodate(v){ return v?String(v).slice(0,10):""; }
  // ---- inline row expansion: click any row for full assignment detail ----
  function wireExpandAsg(body, colspan){
    body.querySelectorAll("tr[data-xa]").forEach(function(tr){
      tr.style.cursor="pointer";
      tr.onclick=function(ev){
        var t=ev.target;
        while(t && t!==tr){ if(t.tagName==="BUTTON"||t.tagName==="A"||t.tagName==="INPUT"||t.tagName==="SELECT") return; t=t.parentNode; }
        var nx=tr.nextElementSibling;
        var open=nx && nx.classList.contains("xd");
        body.querySelectorAll("tr.xd").forEach(function(x){ x.parentNode.removeChild(x); });
        if(open) return;
        var d=document.createElement("tr"); d.className="xd";
        d.innerHTML='<td colspan="'+colspan+'" style="white-space:normal;background:var(--wash);padding:12px 14px;font-size:11px;color:var(--mute)">Loading detail…</td>';
        tr.parentNode.insertBefore(d, tr.nextSibling);
        var name=tr.getAttribute("data-xa");
        call({action:"a_detail", assignment:name}).then(function(res){
          var a=res.detail;
          if(!a){ d.firstChild.textContent="Could not load."; return; }
          var uom=a.uom||"";
          var figs='<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px">';
          [["Plan",a.planner_request],["Period",(a.from_date||"")+" → "+(a.to_date||"")],["Planned/day",fmt(a.planned_people)],["Active crew",fmt(a.active_count)],["Target",fmt(a.target_qty)+" "+uom],["Done",fmt(a.fulfilled_qty)],["Remaining",(a.remaining_qty<0?"0":fmt(a.remaining_qty))],["Rate","KES "+fmt(a.rate,2)+"/"+(uom||"unit")]].forEach(function(p){
            if(p[1]==null||p[1]==="") return;
            figs+='<div style="border:1px solid var(--line);border-radius:10px;padding:7px 11px;background:#fff;min-width:90px"><div style="font-size:8.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);font-weight:600">'+p[0]+'</div><div style="font-size:12.5px;font-weight:700">'+p[1]+'</div></div>';
          });
          figs+='</div>';
          var roster="";
          var ws=a.workers||[];
          if(ws.length){
            roster='<div style="max-height:200px;overflow:auto;border:1px solid var(--line);border-radius:8px;background:#fff"><table style="margin:0;font-size:11px"><thead><tr><th>Worker</th><th>Status</th><th class="n">Days</th><th class="n">Done ('+uom+')</th><th class="n">Pay KES</th></tr></thead><tbody>';
            ws.forEach(function(w){
              var st=(w.status||"Active");
              roster+='<tr><td>'+esc(w.employee_name||w.employee)+'</td><td>'+(st==="Left"?('<span class="tag rej">left '+esc(w.left_date||"")+'</span>'):(w.start_date?('<span class="tag assigned">from '+esc(w.start_date)+'</span>'):'<span class="tag">active</span>'))+'</td><td class="n">'+fmt(w.days_worked)+'</td><td class="n">'+fmt(w.qty_done)+'</td><td class="n">'+fmt(w.pay_to_date)+'</td></tr>';
            });
            roster+='</tbody></table></div>';
          }
          d.innerHTML='<td colspan="'+colspan+'" style="white-space:normal;background:var(--wash);padding:12px 14px">'+
            '<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:2px"><b style="font-size:12.5px">'+esc(a.name)+'</b><span style="font-size:10.5px;color:var(--mute)">'+esc(a.farm||"")+' · '+esc(a.task||"")+' · '+esc(blocksLbl(a))+'</span>'+
            '<a style="margin-left:auto;font-size:10px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#2563eb;text-decoration:none;border:1px solid #bfdbfe;background:#eff6ff;padding:4px 10px;border-radius:999px" target="_blank" href="/app/work-management-assigner/'+encodeURIComponent(a.name)+'">Open in Desk ↗</a></div>'+
            figs+roster+'</td>';
        }).catch(function(e){ d.firstChild.textContent="Could not load detail."; });
      };
    });
  }

  function initAssign(){
    el("a-plan").onchange=onPlan;
    ["a-f-farm","a-f-task","a-f-from","a-f-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=renderPlanList; });
    ["a-f-block","a-f-q"].forEach(function(id){ var e=el(id); if(e) e.oninput=renderPlanList; });
    var clr=el("a-f-clear");
    if(clr) clr.onclick=function(){
      ["a-f-farm","a-f-task","a-f-from","a-f-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; });
      ["a-f-block","a-f-q"].forEach(function(id){ var e=el(id); if(e) e.value=""; });
      renderPlanList();
    };
    el("a-emfilter").oninput=renderEmployees;
    el("b-adraft").onclick=function(){ doSubmit(0); };
    el("b-asubmit").onclick=function(){ doSubmit(1); };
    loadPlans();
  }

  function loadPlans(){
    call({action:"a_approved_planners"}).then(function(d){
      ST.planList = (d.planners||[]);
      // hidden select keeps canonical value (existing call sites read/set it)
      var sel=el("a-plan");
      if(sel){
        sel.innerHTML='<option value="">— select approved plan —</option>';
        ST.planList.forEach(function(p){
          var o=document.createElement("option"); o.value=p.name; o.textContent=p.name;
          if(p.already_assigned) o.disabled=true;
          sel.appendChild(o);
        });
      }
      buildPlanFilters();
      renderPlanList();
    });
  }
  function buildPlanFilters(){
    var farms={}, tasks={};
    (ST.planList||[]).forEach(function(p){
      if(p.farm) farms[p.farm]=1;
      if(p.task) tasks[p.task]=1;
    });
    var fsel=el("a-f-farm");
    if(fsel){
      var fkeep=fsel.value;
      fsel.innerHTML='<option value="">All farms</option>';
      Object.keys(farms).sort().forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
      fsel.value=fkeep||"";
    }
    var tsel=el("a-f-task");
    if(tsel){
      var tkeep=tsel.value;
      tsel.innerHTML='<option value="">All tasks</option>';
      Object.keys(tasks).sort().forEach(function(t){ var o=document.createElement("option"); o.value=t; o.textContent=t; tsel.appendChild(o); });
      tsel.value=tkeep||"";
    }
  }
  function renderPlanList(){
    var box=el("a-plan-list"); if(!box) return;
    var list=ST.planList||[];
    var ffarm=(el("a-f-farm")&&el("a-f-farm").value)||"";
    var ftask=(el("a-f-task")&&el("a-f-task").value)||"";
    var fblock=((el("a-f-block")&&el("a-f-block").value)||"").trim().toLowerCase();
    var fq=((el("a-f-q")&&el("a-f-q").value)||"").trim().toLowerCase();
    var ffrom=(el("a-f-from")&&el("a-f-from").value)||"";
    var fto=(el("a-f-to")&&el("a-f-to").value)||"";
    var shown=0, h="";
    list.forEach(function(p){
      if(ffarm && p.farm!==ffarm) return;
      if(ftask && p.task!==ftask) return;
      if(fblock && (lbl(p.block_section)||"").toLowerCase().indexOf(fblock)<0) return;
      if(ffrom && p.to_date && p.to_date<ffrom) return;
      if(fto && p.from_date && p.from_date>fto) return;
      if(fq){
        var hay=((p.name||"")+" "+(p.farm||"")+" "+(p.block_section||"")+" "+(p.task||"")).toLowerCase();
        if(hay.indexOf(fq)<0) return;
      }
      shown++;
      var taken = p.already_assigned?true:false;
      var sel = (ST.plan===p.name) ? " sel" : "";
      var takenCls = taken ? " taken" : "";
      var meta='<div class="pl-task">'+esc(p.task)+(taken?'<span class="pl-tk">assigned</span>':'')+'</div>'+
               '<div class="pl-sub">'+fmt(p.people_per_day)+'/day · KES '+fmt(p.total_cost)+' · '+esc(p.from_date)+' → '+esc(p.to_date)+'</div>';
      h+='<div class="pl-row'+sel+takenCls+'" data-plan="'+esc(p.name)+'" data-taken="'+(taken?1:0)+'">'+
           '<div class="pl-main"><span class="pl-farm">'+esc(p.farm)+'</span> · '+esc(blocksLbl(p))+meta+'</div>'+
           '<div class="pl-ref">'+esc(p.name)+'</div></div>';
    });
    if(!shown){ h='<div class="empty" style="margin:0">No plans match these filters.</div>'; }
    box.innerHTML=h;
    var cnt=el("a-plan-count"); if(cnt) cnt.textContent=shown+" of "+list.length;
    box.querySelectorAll(".pl-row").forEach(function(row){
      if(row.getAttribute("data-taken")==="1") return;  // already assigned -> not selectable
      row.onclick=function(){
        var name=row.getAttribute("data-plan");
        var sel=el("a-plan"); if(sel) sel.value=name;
        onPlan.call({value:name});
        box.querySelectorAll(".pl-row").forEach(function(r){ r.classList.remove("sel"); });
        row.classList.add("sel");
      };
    });
  }

  function onPlan(){
    ST.plan=this.value; ST.picked={}; ST.employees=[]; ST.planDetail=null;
    el("a-empicker").innerHTML='<div class="empty">Loading workers…</div>';
    el("a-emfilter").disabled=true; el("a-emfilter").value="";
    if(!ST.plan){ el("a-detail").style.display="none"; refreshCounts(); return; }
    call({action:"a_planner_detail",planner:ST.plan}).then(function(d){
      var p=d.planner||{}; ST.planDetail=p;
      el("a-detail").style.display="block";
      el("a-detail").innerHTML=
        '<div class="dl"><span class="k">Farm</span><span class="v">'+esc(p.farm)+'</span></div>'+
        '<div class="dl"><span class="k">Block</span><span class="v">'+esc(blocksLbl(p))+'</span></div>'+
        '<div class="dl"><span class="k">Task</span><span class="v">'+esc(p.task)+'</span></div>'+
        '<div class="dl"><span class="k">Standard</span><span class="v">'+esc(p.task_kpi||"—")+'</span></div>'+
        '<div class="dl"><span class="k">Period</span><span class="v">'+esc(p.from_date)+' → '+esc(p.to_date)+'</span></div>'+
        '<div class="dl"><span class="k">Planned people/day</span><span class="v big">'+fmt(p.people_per_day)+'</span></div>'+
        '<div class="dl"><span class="k">Planned cost</span><span class="v big">KES '+fmt(p.total_cost)+'</span></div>';
      el("a-farmlabel").textContent="· "+p.farm;
      el("o-plan").textContent=fmt(p.people_per_day);
      loadEmployees(p.farm);
      refreshCounts();
    });
  }

  function loadEmployees(farm){
    var pd=ST.planDetail||{};
    call({action:"a_employees",farm:farm,from_date:pd.from_date,to_date:pd.to_date,exclude_assignment:(ST.editingAsg||"")}).then(function(d){
      ST.employees=d.employees||[];
      el("a-emfilter").disabled=false;
      renderEmployees();
    });
  }

  function renderEmployees(){
    var q=(el("a-emfilter").value||"").toLowerCase();
    var box=el("a-empicker");
    var list=ST.employees.filter(function(e){
      if(!q) return true;
      return ((e.employee_name||"")+" "+(e.designation||"")+" "+(e.name||"")).toLowerCase().indexOf(q)>=0;
    });
    if(!list.length){ box.innerHTML='<div class="empty">No matching workers.</div>'; return; }
    var h="";
    list.forEach(function(e){
      var on=ST.picked[e.name]?" on":"";
      var offbadge = (e.off_days>0) ? ' <span class="offb">'+e.off_days+' off</span>' : '';
      var busy = e.allocated_elsewhere?true:false;
      if(busy){
        var tag = ' <span class="allocb">assigned elsewhere'+(e.allocated_farm?(" · "+esc(e.allocated_farm)):"")+'</span>';
        h+='<div class="emrow busy" data-emp="'+esc(e.name)+'" title="Already on '+esc(e.allocated_asg||"")+' ('+esc(e.allocated_task||"")+') for an overlapping period">'+
           '<input type="checkbox" disabled>'+
           '<span class="en">'+esc(e.employee_name||e.name)+tag+'</span>'+
           '<span class="ed">'+esc(e.designation||"")+' · '+esc(e.employment_type||"")+'</span></div>';
      } else {
        h+='<div class="emrow'+on+'" data-emp="'+esc(e.name)+'">'+
           '<input type="checkbox" '+(ST.picked[e.name]?"checked":"")+'>'+
           '<span class="en">'+esc(e.employee_name||e.name)+offbadge+'</span>'+
           '<span class="ed">'+esc(e.designation||"")+' · '+esc(e.employment_type||"")+'</span></div>';
      }
    });
    box.innerHTML=h;
    box.querySelectorAll(".emrow").forEach(function(row){
      if(row.classList.contains("busy")) return;   // non-selectable: allocated elsewhere
      row.onclick=function(){
        var id=row.getAttribute("data-emp");
        ST.picked[id]=!ST.picked[id];
        row.classList.toggle("on", ST.picked[id]);
        var cb=row.querySelector("input"); if(cb) cb.checked=ST.picked[id];
        refreshCounts();
      };
    });
  }

  function refreshCounts(){
    var n=nPicked();
    var planned = ST.planDetail ? (ST.planDetail.people_per_day||0) : 0;
    el("o-assigned").textContent=n;
    var v=n-planned;
    el("o-var").textContent=(ST.planDetail?(v>0?"+"+v:v):"—");
    var over = planned>0 && n>planned;
    el("o-varbox").classList.toggle("warn", ST.planDetail && v!==0);
    var note = "";
    if(n){
      note = "<b>"+n+"</b> worker"+(n>1?"s":"")+" selected";
      if(planned) note += " · plan calls for <b>"+planned+"</b>";
      if(over) note += ' · <span style="color:#a00;font-weight:700">exceeds plan by '+(n-planned)+' — remove '+(n-planned)+' to submit</span>';
    }
    // off-day warning for selected workers
    var offWorkers=[];
    (ST.employees||[]).forEach(function(e){
      if(ST.picked[e.name] && e.off_days>0){ offWorkers.push((e.employee_name||e.name)+" ("+e.off_days+")"); }
    });
    if(offWorkers.length){
      note += '<div style="margin-top:6px;font-size:11px;color:#a06000">⚠ '+offWorkers.length+' selected worker'+(offWorkers.length>1?"s have":" has")+' rest days in this period — those days will be closed in Actuals (they won’t be paid for them): '+offWorkers.slice(0,6).map(esc).join(", ")+(offWorkers.length>6?"…":"")+'</div>';
    }
    el("a-picked").innerHTML = note;
    var ready = ST.plan && n>0 && !over;   // HARD CAP: cannot submit when over planned
    el("b-adraft").disabled=!ready;
    el("b-asubmit").disabled=!ready;
  }

  function doSubmit(submitNow){
    var ids=[]; for(var k in ST.picked){ if(ST.picked[k]) ids.push(k); }
    var args={ action:"a_submit", planner:ST.plan, employees:ids.join(",") };
    if(submitNow) args.submit_now=1;
    if(ST.editingAsg) args.assignment=ST.editingAsg;   // update the existing draft
    el("b-adraft").disabled=true; el("b-asubmit").disabled=true;
    call(args).then(function(d){
      if(d.error){ toast("Error: "+d.error); refreshCounts(); return; }
      var verb = d.editing ? (submitNow?"Updated & submitted ":"Draft updated ") : (submitNow?"Submitted ":"Draft saved ");
      toast(verb+d.name+" · "+d.workflow_state);
      clearEdit();
      ST.plan=null; ST.picked={}; ST.planDetail=null; ST.employees=[];
      el("a-plan").value=""; el("a-detail").style.display="none";
      el("a-empicker").innerHTML='<div class="empty">Pick a plan to load that farm’s workers.</div>';
      el("a-emfilter").value=""; el("a-emfilter").disabled=true; el("a-farmlabel").textContent="";
      el("o-plan").textContent="—";
      refreshCounts(); loadPlans();
    }).catch(function(e){ toast("Failed to save"); refreshCounts(); });
  }

  function clearEdit(){
    ST.editingAsg=null;
    var b=el("a-editbanner"); if(b){ b.style.display="none"; b.innerHTML=""; }
    var sb=el("b-asubmit"); if(sb) sb.textContent="Submit for Approval";
    var db=el("b-adraft"); if(db) db.textContent="Save Draft";
  }

  function openAsgForEdit(name){
    call({action:"a_detail", assignment:name}).then(function(d){
      var a=d.detail;
      if(!a){ toast("Could not load"); return; }
      if(!a.editable){ toast("This assignment can no longer be edited ("+a.workflow_state+")"); return; }
      showTab("assign");
      ST.editingAsg=a.name;
      ST.plan=a.planner_request;
      el("a-plan").value=a.planner_request;
      renderPlanList();
      // load plan detail + employees, then pre-tick the roster
      call({action:"a_planner_detail",planner:a.planner_request}).then(function(pd){
        var p=pd.planner||{}; ST.planDetail=p;
        el("a-detail").style.display="block";
        el("a-detail").innerHTML=
          '<div class="dl"><span class="k">Farm</span><span class="v">'+esc(p.farm)+'</span></div>'+
          '<div class="dl"><span class="k">Block</span><span class="v">'+esc(blocksLbl(p))+'</span></div>'+
          '<div class="dl"><span class="k">Task</span><span class="v">'+esc(p.task)+'</span></div>'+
          '<div class="dl"><span class="k">Standard</span><span class="v">'+esc(p.task_kpi||"—")+'</span></div>'+
          '<div class="dl"><span class="k">Period</span><span class="v">'+esc(p.from_date)+' → '+esc(p.to_date)+'</span></div>'+
          '<div class="dl"><span class="k">Planned people/day</span><span class="v big">'+fmt(p.people_per_day)+'</span></div>'+
          '<div class="dl"><span class="k">Planned cost</span><span class="v big">KES '+fmt(p.total_cost)+'</span></div>';
        el("a-farmlabel").textContent="· "+p.farm;
        el("o-plan").textContent=fmt(p.people_per_day);
        call({action:"a_employees",farm:p.farm}).then(function(ed){
          ST.employees=ed.employees||[];
          el("a-emfilter").disabled=false;
          ST.picked={};
          (a.workers||[]).forEach(function(w){ if((w.status||"Active")==="Active") ST.picked[w.employee]=true; });
          renderEmployees();
          refreshCounts();
        });
      });
      var b=el("a-editbanner");
      if(b){ b.style.display="block"; b.innerHTML="Editing <b>"+esc(a.name)+"</b> ("+esc(a.workflow_state)+") — changes update this assignment. <a href='#' id='a-cancel-edit'>Cancel edit</a>";
        var c=document.getElementById("a-cancel-edit"); if(c) c.onclick=function(ev){ ev.preventDefault(); clearEdit(); onPlan.call({value:""}); toast("Edit cancelled"); }; }
      el("b-asubmit").textContent="Update & Submit";
      el("b-adraft").textContent="Update Draft";
    }).catch(function(e){ toast("Could not load"); });
  }

  function stateTag(s){
    var c="pend", t=s||"Draft";
    if(s==="Assigned") c="assigned"; else if(s==="Pending HR Head") c="pend"; else if(s==="Rejected") c="rej"; else c="";
    return '<span class="tag '+c+'">'+esc(t)+'</span>';
  }
  function varTag(v){
    if(v===0||v==null) return '<span class="tag">on plan</span>';
    return '<span class="tag var">'+(v>0?"+"+v:v)+'</span>';
  }

  function loadMine(){
    var b=el("amine-body"); b.className="loading"; b.innerHTML="Loading…";
    call({action:"a_my_assignments"}).then(function(d){
      var rows=d.assignments||[];
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">No assignments yet.</div>'; return; }
      var sts={}; rows.forEach(function(r){ if(r.workflow_state) sts[r.workflow_state]=1; });
      var hasDates=false; rows.forEach(function(r){ if(r.from_date) hasDates=true; });
      b.className="";
      b.innerHTML='<div class="note" style="margin-bottom:8px">Draft/Rejected → click <b>Edit</b>. Approved (Assigned) → click <b>Manage crew</b> to swap a worker mid-period or release workers who’ve finished so they can be assigned elsewhere.</div>'
        + fbar(rows,{dates:hasDates,statuses:Object.keys(sts).sort(),ph:"Search ref, plan, farm, block, task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:r.workflow_state||"", date:isodate(r.from_date),
                hay:((r.name||"")+" "+(r.planner_request||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Plan</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Var</th><th>Status</th><th></th></tr></thead><tbody>';
        list.forEach(function(r){
          var editable = (r.workflow_state==="Draft"||r.workflow_state==="Rejected"||r.workflow_state==="Pending HR Head");
          var canSub = (r.workflow_state==="Assigned");
          var actionBtn = editable ? '<button class="btn" data-edit="'+esc(r.name)+'">Edit</button>' : (canSub ? '<button class="btn solid" data-sub="'+esc(r.name)+'">Manage crew</button>' : '');
          h+='<tr data-xa="'+esc(r.name)+'"><td>'+esc(r.name)+'</td><td>'+esc(r.planner_request)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+varTag(r.variance)+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+actionBtn+'</td></tr>';
        });
        body.innerHTML=h+'</tbody></table>';
        body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ openAsgForEdit(btn.getAttribute("data-edit")); }; });
        body.querySelectorAll("[data-sub]").forEach(function(btn){ btn.onclick=function(){ openSubstitute(btn.getAttribute("data-sub")); }; });
        wireExpandAsg(body, 10);
      });
    });
  }

  function loadRejected(){
    var b=el("arej-body"); if(!b) return; b.className="loading"; b.innerHTML="Loading…";
    call({action:"a_my_assignments"}).then(function(d){
      ST._arejRows=(d.assignments||[]).filter(function(r){ return r.workflow_state==="Rejected"; });
      renderArej();
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load.</div>'; });
  }
  function renderArej(){
    var b=el("arej-body"); if(!b) return;
    var all=ST._arejRows||[];
    if(!all.length){ b.className=""; b.innerHTML='<div class="empty">Nothing rejected — you’re all clear.</div>'; return; }
    var isGm=ST.roles&&ST.roles.is_gm;
    var closeLabel=isGm?"Close plan":"Request close";
    b.className="";
    b.innerHTML='<div class="note" style="margin-bottom:8px">These assignments were rejected. Click <b>Edit</b> to adjust the roster and resubmit — or <b>'+closeLabel+'</b> if the underlying plan should be stopped.</div>'
      + fbar(all,{dates:true,ph:"Search ref, plan, farm, block, task…"});
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.planner_request||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Ref</th><th>Plan</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Status</th><th></th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr data-xa="'+esc(r.name)+'"><td>'+esc(r.name)+'</td><td>'+esc(r.planner_request)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+stateTag(r.workflow_state)+'</td>'+
          '<td><div class="ib"><button class="btn solid" data-edit="'+esc(r.name)+'">Edit &amp; resubmit</button><button class="btn" data-close="'+esc(r.name)+'" data-plan="'+esc(r.planner_request||"")+'">'+closeLabel+'</button></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireExpandAsg(body, 9);
      body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ openAsgForEdit(btn.getAttribute("data-edit")); }; });
      body.querySelectorAll("[data-close]").forEach(function(btn){
        btn.onclick=function(){ openCloseDialog(btn.getAttribute("data-close"), btn.getAttribute("data-plan"), loadRejected); };
      });
    });
  }

  // ---- Substitution dialog ----
  function openSubstitute(name){
    call({action:"a_detail", assignment:name}).then(function(d){
      var a=d.detail;
      if(!a || !a.can_substitute){ toast("Substitution only on an approved plan"); return; }
      // active workers = candidates to be substituted OUT
      var actives=(a.workers||[]).filter(function(w){ return (w.status||"Active")==="Active"; });
      call({action:"a_sub_candidates", assignment:name}).then(function(cd){
        var cands=cd.candidates||[];
        showSubDialog(a, actives, cands);
      });
    });
  }
  function showSubDialog(a, actives, cands){
    var ov=el("wa-subdialog");
    var uom=a.uom||"";
    var pct = a.target_qty>0 ? (a.fulfilled_qty/a.target_qty*100) : 0;
    var barPct=Math.min(pct,100);
    var left =
      '<div class="sub-col sub-left">'+
        '<div class="sub-h">Plan &amp; task</div>'+
        '<div class="dl"><span class="k">Assignment</span><span class="v">'+esc(a.name)+'</span></div>'+
        '<div class="dl"><span class="k">Plan</span><span class="v">'+esc(a.planner_request)+'</span></div>'+
        '<div class="dl"><span class="k">Farm</span><span class="v">'+esc(a.farm)+'</span></div>'+
        '<div class="dl"><span class="k">Block</span><span class="v">'+esc(blocksLbl(a))+'</span></div>'+
        '<div class="dl"><span class="k">Task</span><span class="v">'+esc(a.task)+'</span></div>'+
        '<div class="dl"><span class="k">Standard</span><span class="v">'+esc(a.task_kpi||"—")+'</span></div>'+
        '<div class="dl"><span class="k">Rate</span><span class="v">KES '+fmt(a.rate,2)+' / '+esc(uom||"unit")+'</span></div>'+
        '<div class="dl"><span class="k">Period</span><span class="v">'+esc(a.from_date)+' → '+esc(a.to_date)+'</span></div>'+
        '<div class="dl"><span class="k">Planned/day</span><span class="v big">'+fmt(a.planned_people)+'</span></div>'+
        '<div class="sub-h" style="margin-top:16px">Burn-down</div>'+
        '<div class="dl"><span class="k">Target</span><span class="v big">'+fmt(a.target_qty)+' '+esc(uom)+'</span></div>'+
        '<div class="dl"><span class="k">Done</span><span class="v big">'+fmt(a.fulfilled_qty)+' '+esc(uom)+'</span></div>'+
        '<div class="dl"><span class="k">Remaining</span><span class="v big">'+(a.remaining_qty<0?"0":fmt(a.remaining_qty))+' '+esc(uom)+'</span></div>'+
        '<div style="height:10px;background:#eee;border:1px solid #cfcfcf;margin-top:8px;overflow:hidden"><div style="height:100%;width:'+barPct+'%;background:#0a0a0a"></div></div>'+
        '<div style="font-size:10px;color:#777;margin-top:4px;text-align:right">'+fmt(pct,0)+'% fulfilled</div>'+
      '</div>';
    var canRelease = ST.roles && (ST.roles.is_farm_manager || ST.roles.is_hr_head || ST.roles.is_gm);
    var relDefault = a.to_date; // clamp today into [from_date, to_date] for the "last day" field
    (function(){ var t=isoTodayA(); if(t < a.from_date) relDefault=a.from_date; else if(t > a.to_date) relDefault=a.to_date; else relDefault=t; })();
    var rosterRows=(a.workers||[]).map(function(w){
      var st=(w.status||"Active");
      var badge = st==="Left" ? '<span class="rb left">left '+esc(w.left_date||"")+'</span>' : (w.start_date?'<span class="rb repl">from '+esc(w.start_date)+'</span>':'<span class="rb act">active</span>');
      var chkCell = canRelease
        ? '<td class="c">'+(st==="Left" ? '' : '<input type="checkbox" class="rel-chk" value="'+esc(w.employee)+'">')+'</td>'
        : '';
      return '<tr class="'+(st==="Left"?"isleft":"")+'">'+chkCell+'<td><div class="rn">'+esc(w.employee_name||w.employee)+'</div>'+badge+'</td>'+
             '<td class="n">'+fmt(w.days_worked)+'</td>'+
             '<td class="n">'+fmt(w.qty_done)+'</td>'+
             '<td class="n">'+fmt(w.pay_to_date)+'</td></tr>';
    }).join("");
    var relHeadCell = canRelease ? '<th class="c"><input type="checkbox" id="rel-all" title="Select all active"></th>' : '';
    var relColspan = canRelease ? 5 : 4;
    var releasePanel = canRelease ? (
      '<div class="rel-box">'+
        '<div class="sub-h" style="margin-top:14px">Release finished workers</div>'+
        '<div class="rel-note">Tick workers above who have finished, then release them so they can be assigned to other tasks. Their recorded days and pay stay exactly as they are — releasing only frees them for the remaining days.</div>'+
        '<label>Last day worked (release date)</label>'+
        '<input type="date" id="rel-date" min="'+esc(a.from_date)+'" max="'+esc(a.to_date)+'" value="'+esc(relDefault)+'">'+
        '<div class="rel-actions"><span id="rel-count" class="rel-count">0 selected</span><button class="btn solid" id="rel-confirm" disabled>Release selected</button></div>'+
      '</div>'
    ) : '';
    var mid =
      '<div class="sub-col sub-mid">'+
        '<div class="sub-h">Current roster · '+a.active_count+' active</div>'+
        '<table class="rtab"><thead><tr>'+relHeadCell+'<th>Worker</th><th class="n">Days</th><th class="n">Done ('+esc(uom)+')</th><th class="n">Pay KES</th></tr></thead><tbody>'+
        (rosterRows||'<tr><td colspan="'+relColspan+'" class="empty">No workers.</td></tr>')+
        '</tbody></table>'+
        '<div class="sub-note">Left workers keep pay for days already worked. Substitution keeps headcount the same (1 out → 1 in).</div>'+
        releasePanel+
      '</div>';
    var outOpts=actives.map(function(w){ return '<option value="'+esc(w.employee)+'">'+esc(w.employee_name||w.employee)+' · '+fmt(w.days_worked)+'d, KES '+fmt(w.pay_to_date)+'</option>'; }).join("");
    var repOpts=cands.map(function(c){ return '<option value="'+esc(c.name)+'">'+esc(c.employee_name||c.name)+'</option>'; }).join("");
    var right =
      '<div class="sub-col sub-right">'+
        '<div class="sub-h">Substitute a worker</div>'+
        '<label>Worker leaving</label>'+
        '<select id="sub-out">'+(outOpts||'<option value="">— none active —</option>')+'</select>'+
        '<label>Their last day worked</label>'+
        '<input type="date" id="sub-leftdate" min="'+esc(a.from_date)+'" max="'+esc(a.to_date)+'" value="'+esc(a.from_date)+'">'+
        '<label>Replacement (Task Worker, not on plan)</label>'+
        '<select id="sub-rep">'+(repOpts||'<option value="">— none available —</option>')+'</select>'+
        '<label>Replacement starts on</label>'+
        '<input type="date" id="sub-startdate" min="'+esc(a.from_date)+'" max="'+esc(a.to_date)+'" value="'+esc(a.from_date)+'">'+
        '<div class="sub-actions"><button class="btn" id="sub-cancel">Cancel</button><button class="btn solid" id="sub-confirm">Confirm substitution</button></div>'+
        '<div class="sub-note">The replacement inherits the remaining target and starts their tally at zero.</div>'+
      '</div>';
    ov.innerHTML=
      '<div class="sub-full">'+
        '<div class="sub-bar"><div class="sub-title">Manage crew — '+esc(a.name)+'</div><button class="sub-x" id="sub-close">✕</button></div>'+
        '<div class="sub-grid">'+left+mid+right+'</div>'+
      '</div>';
    ov.classList.add("open");
    ov.style.display="block";
    document.body.style.overflow="hidden";
    var close=function(){ ov.classList.remove("open"); ov.style.display="none"; ov.innerHTML=""; document.body.style.overflow=""; };
    el("sub-close").onclick=close;
    el("sub-cancel").onclick=close;
    el("sub-confirm").onclick=function(){
      var outgoing=el("sub-out").value, replacement=el("sub-rep").value;
      var leftd=el("sub-leftdate").value, startd=el("sub-startdate").value;
      if(!outgoing||!replacement){ toast("Pick both workers"); return; }
      if(!leftd||!startd){ toast("Pick both dates"); return; }
      el("sub-confirm").disabled=true;
      call({action:"a_substitute", assignment:a.name, outgoing:outgoing, replacement:replacement, left_date:leftd, start_date:startd}).then(function(r){
        if(r.error){ toast("Error: "+r.error); el("sub-confirm").disabled=false; return; }
        toast("Substituted · "+r.active_count+" active");
        close(); loadMine();
      }).catch(function(e){ toast("Substitution failed"); el("sub-confirm").disabled=false; });
    };
    // ---- release-workers wiring (FM/HR/GM only; controls exist only when canRelease) ----
    var relAll=el("rel-all"), relBtn=el("rel-confirm");
    if(relBtn){
      var chks=function(){ return Array.prototype.slice.call(ov.querySelectorAll(".rel-chk")); };
      var refreshRel=function(){
        var sel=chks().filter(function(c){ return c.checked; });
        el("rel-count").textContent = sel.length+" selected";
        relBtn.disabled = sel.length===0;
        if(relAll){ var all=chks(); relAll.checked = all.length>0 && sel.length===all.length; }
      };
      chks().forEach(function(c){ c.onchange=refreshRel; });
      if(relAll){ relAll.onchange=function(){ chks().forEach(function(c){ c.checked=relAll.checked; }); refreshRel(); }; }
      relBtn.onclick=function(){
        var sel=chks().filter(function(c){ return c.checked; }).map(function(c){ return c.value; });
        if(!sel.length){ toast("Tick at least one worker to release"); return; }
        var reld=el("rel-date").value;
        if(!reld){ toast("Pick the last day worked"); return; }
        var msg = sel.length===1 ? "Release this worker so they can be assigned elsewhere? Their recorded pay stays untouched."
                                  : ("Release these "+sel.length+" workers so they can be assigned elsewhere? Their recorded pay stays untouched.");
        if(!window.confirm(msg)) return;
        relBtn.disabled=true;
        call({action:"a_release", assignment:a.name, employees:sel.join(","), release_date:reld}).then(function(r){
          if(r.error){ toast("Error: "+r.error); relBtn.disabled=false; return; }
          toast("Released "+r.released_count+" · "+r.active_count+" still active");
          close(); loadMine();
        }).catch(function(e){ toast("Release failed"); relBtn.disabled=false; });
      };
    }
  }

  function loadStage(bodyId, stage, approveAction){
    var b=el(bodyId); b.className="loading"; b.innerHTML="Loading…";
    call({action:"a_pending", stage:stage}).then(function(d){
      var rows=d.pending||[];
      // stash for client-side farm filtering, keyed by the body element id
      ST._stageCache=ST._stageCache||{};
      ST._stageCache[bodyId]={rows:rows, stage:stage, approveAction:approveAction, farm:(ST._stageCache[bodyId]&&ST._stageCache[bodyId].farm)||""};
      renderStage(bodyId);
    });
  }
  function renderStage(bodyId){
    var b=el(bodyId); if(!b) return;
    var c=ST._stageCache[bodyId]; if(!c) return;
    var all=c.rows||[];
    if(!all.length){ b.className=""; b.innerHTML='<div class="empty">Nothing at this stage.</div>'; return; }
    b.className="";
    b.innerHTML=fbar(all,{dates:true,ph:"Search ref, farm, block, task, assigned by…"});
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.assigned_by||"")).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Ref</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Var</th><th class="n">Cost</th><th>By</th><th>Action</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr data-xa="'+esc(r.name)+'"><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+varTag(r.variance)+'</td><td class="n">'+fmt(r.planned_cost)+'</td><td>'+esc(r.assigned_by)+'</td><td><div class="ib"><button class="btn" data-edit="'+esc(r.name)+'">Edit</button><button class="btn solid" data-app="'+esc(r.name)+'">Approve</button><button class="btn" data-rej="'+esc(r.name)+'">Reject</button></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireExpandAsg(body, 10);
      body.querySelectorAll("[data-app]").forEach(function(btn){ btn.onclick=function(){ act(c.approveAction, btn.getAttribute("data-app"), bodyId, c.stage, c.approveAction); }; });
      body.querySelectorAll("[data-rej]").forEach(function(btn){ btn.onclick=function(){ act("a_reject", btn.getAttribute("data-rej"), bodyId, c.stage, c.approveAction); }; });
      body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ openAsgForEdit(btn.getAttribute("data-edit")); }; });
    });
  }
  function act(which,name,bodyId,stage,approveAction){
    call({action:which,name:name}).then(function(d){
      if(d.error){ toast("Error: "+d.error); return; }
      toast(name+" → "+d.workflow_state);
      if(bodyId){ loadStage(bodyId, stage, approveAction); }
    }).catch(function(e){ toast("Action failed"); });
  }

  function boot(){
    call({action:"a_roles"}).then(function(roles){
      ST.roles=roles;
      el("wa-who").textContent=(roles.user||"")+(roles.is_hr_head?" · HR Head":(roles.is_clerk?" · HR":""));
      initAssign();
      buildTabs();
    }).catch(function(e){ el("wa-who").textContent="Could not load."; });
  }

  if(typeof frappe==="undefined"){
    var w=document.getElementById("wa-who"); if(w) w.textContent="Open inside Frappe (logged in).";
  } else {
    if(document.getElementById("a-plan")) boot();
    else document.addEventListener("DOMContentLoaded", boot);
  }
})();
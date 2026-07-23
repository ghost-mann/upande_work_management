(function(){
  var API = "/api/method/wm_planner";
  var ST = { farm:null, picked:{}, task:null, taskInfo:null, tasks:[], blocks:[], roles:null };

  function call(args){
    var writes = {submit:1, approve:1, reject:1};
    var isWrite = writes[args.action] === 1;
    var p = new URLSearchParams();
    for(var k in args){ if(args[k]!==undefined && args[k]!==null) p.append(k, args[k]); }
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    if(!isWrite){
      return fetch("/api/method/wm_planner?" + p.toString(), {
        method: "GET", headers: { "Accept": "application/json" }, credentials: "same-origin"
      }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
        .then(function(j){ return j.message || {}; });
    }
    return fetch("/api/method/wm_planner", {
      method: "POST",
      headers: { "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body: p.toString(), credentials: "same-origin"
    }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
      .then(function(j){ return j.message || {}; });
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function el(id){ return document.getElementById(id); }
  function toast(msg){ var t=el("wp-toast"); t.textContent=msg; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2200); }
  function today(){ return new Date().toISOString().slice(0,10); }
  function addDays(d,n){ var x=new Date(d); x.setDate(x.getDate()+n); return x.toISOString().slice(0,10); }
  function dayDiff(a,b){ return Math.round((new Date(b)-new Date(a))/86400000); }
  function nBlocks(){ var n=0; for(var k in ST.picked){ if(ST.picked[k]) n++; } return n; }
  function pickedList(){ var a=[]; for(var k in ST.picked){ if(ST.picked[k]) a.push(k); } return a; }
  function blockLabel(name){ for(var i=0;i<ST.blocks.length;i++){ if(ST.blocks[i].name===name) return ST.blocks[i].label; } return lbl(name); }
  function blockArea(){ var t=0; for(var i=0;i<ST.blocks.length;i++){ var b=ST.blocks[i]; if(ST.picked[b.name]){ t+=(b.area||0); } } return t; }
  function shortUser(u){ return (u||"").split("@")[0]; }
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

  // ── plan close (shared) ───────────────────────────────────────────
  // Close workflow lives in the wm_actuals script (single source of truth), so we
  // POST there directly with the plan name. GM closes instantly; Farm Manager /
  // Section Head sends a request for the GM to confirm.
  function closeCall(action, plan, reason){
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    var p=new URLSearchParams();
    p.append("action", action); p.append("plan", plan); p.append("reason", reason);
    return fetch("/api/method/wm_actuals", {
      method:"POST",
      headers:{ "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body:p.toString(), credentials:"same-origin"
    }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){ return j.message||{}; });
  }
  function openCloseDialog(plan, onDone){
    var isGm = ST.roles && ST.roles.is_gm;
    var dlg=el("wp-closedialog");
    var title = isGm ? "Close plan now" : "Request close";
    var desc = isGm
      ? "This finalises any open draft actuals to Confirmed and caps the plan (target kept for reporting). A reason is required."
      : "This sends a close request to the GM. Entry stays open until they confirm. A reason is required.";
    dlg.innerHTML =
      '<div style="background:#fff;max-width:440px;width:92%;border:2px solid var(--ink)">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--faint)">'+
          '<div style="font-size:13px;font-weight:700">'+title+'</div>'+
          '<button type="button" id="wpc-x" style="border:none;background:none;font-size:20px;line-height:1;color:var(--mute);cursor:pointer">&times;</button>'+
        '</div>'+
        '<div style="padding:16px 18px">'+
          '<div style="font-size:12px;color:#444;margin-bottom:10px">'+esc(desc)+' <span style="color:#777">Plan <b>'+esc(plan)+'</b>.</span></div>'+
          '<label style="display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600;margin-bottom:5px">Reason (required)</label>'+
          '<textarea id="wpc-reason" rows="3" style="font-family:inherit;font-size:13px;border:1px solid var(--line);padding:8px 10px;width:100%;background:#fff;color:var(--ink);resize:vertical" placeholder="e.g. crop finished early, block cleared ahead of target"></textarea>'+
        '</div>'+
        '<div style="display:flex;justify-content:flex-end;gap:10px;padding:14px 18px;border-top:1px solid var(--faint)">'+
          '<button type="button" class="btn" id="wpc-cancel">Cancel</button>'+
          '<button type="button" class="btn solid" id="wpc-go" disabled>'+(isGm?"Close now":"Send request")+'</button>'+
        '</div>'+
      '</div>';
    dlg.style.display="flex";
    var ta=el("wpc-reason"), go=el("wpc-go");
    ta.oninput=function(){ go.disabled=!ta.value.trim(); };
    function shut(){ dlg.style.display="none"; dlg.innerHTML=""; }
    el("wpc-x").onclick=shut; el("wpc-cancel").onclick=shut;
    dlg.onclick=function(ev){ if(ev.target===dlg) shut(); };
    go.onclick=function(){
      var reason=(ta.value||"").trim();
      if(!reason){ toast("A reason is required"); return; }
      go.disabled=true;
      closeCall(isGm?"act_close_confirm":"act_close_request", plan, reason).then(function(d){
        if(d.error){ toast("Error: "+d.error); go.disabled=false; return; }
        shut();
        toast(isGm ? "Plan closed" : "Close request sent to GM");
        if(typeof onDone==="function") onDone();
      }).catch(function(e){ toast("Close failed"); go.disabled=false; });
    };
  }

  function buildTabs(){
    var tabs=[["new","New Request"],["mine","My Requests"],["rej","Rejected"]];
    if(ST.roles && ST.roles.is_approver) tabs.push(["appr","Approvals"]);
    var nav=el("wp-tabs"); nav.innerHTML="";
    tabs.forEach(function(t){
      var b=document.createElement("button");
      b.textContent=t[1]; b.setAttribute("data-tab",t[0]);
      b.onclick=function(){ showTab(t[0]); };
      nav.appendChild(b);
    });
    showTab("new");
  }
  function showTab(name){
    ["new","mine","rej","appr"].forEach(function(n){ var p=el("p-"+n); if(p) p.classList.toggle("on", n===name); });
    document.querySelectorAll("#wp-tabs button").forEach(function(b){ b.setAttribute("aria-selected", b.getAttribute("data-tab")===name); });
    if(name==="mine") loadMine();
    if(name==="rej") loadRejected();
    if(name==="appr") loadAppr();
  }

  function initNew(meta){
    var fs=el("f-farm");
    fs.innerHTML='<option value="">— select farm —</option>';
    meta.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); });
    fs.onchange=onFarm;
    el("f-block").onchange=function(){ if(this.value){ ST.picked[this.value]=true; this.value=''; } syncBlockGrid(); recalc(); };
    el("f-task").onchange=onTask;
    el("f-qty").oninput=recalc;
    el("f-from").onchange=function(){ syncSlider(); recalc(); };
    el("f-to").onchange=function(){ syncSlider(); recalc(); };
    el("f-slider").oninput=onSlider;
    el("f-from").value=today();
    el("f-to").value=addDays(today(),6);
    el("b-draft").onclick=function(){ doSubmit(0); };
    el("b-submit").onclick=function(){ doSubmit(1); };
    syncSlider();
  }

  function onFarm(){
    ST.farm=this.value; ST.picked={}; ST.task=null; ST.taskInfo=null;
    el("f-block").innerHTML='<option value="">— loading —</option>';
    el("f-task").innerHTML='<option value="">— loading —</option>';
    el("f-blockgrid").innerHTML=""; el("f-kpi").textContent=""; el("f-picked").textContent="";
    if(!ST.farm){ recalc(); return; }
    call({action:"blocks",farm:ST.farm}).then(function(d){
      ST.blocks=d.blocks||[];
      var sel=el("f-block");
      sel.innerHTML='<option value="">— add a block —</option>';
      ST.blocks.forEach(function(b){ var o=document.createElement("option"); o.value=b.name; o.textContent=b.label; sel.appendChild(o); });
      syncBlockGrid();
    });
    call({action:"tasks",farm:ST.farm}).then(function(d){
      ST.tasks=d.tasks||[];
      var sel=el("f-task");
      sel.innerHTML='<option value="">— select task —</option>';
      ST.tasks.forEach(function(t){ var o=document.createElement("option"); o.value=t.name; o.textContent=t.subject; sel.appendChild(o); });
    });
    recalc();
  }

  function syncBlockGrid(){
    var g=el("f-blockgrid"); g.innerHTML="";
    ST.blocks.forEach(function(b){
      var d=document.createElement("div");
      d.className="bk"+(ST.picked[b.name]?" on":"");
      d.textContent=b.label;
      d.onclick=function(){ ST.picked[b.name]=!ST.picked[b.name]; syncBlockGrid(); recalc(); };
      g.appendChild(d);
    });
    var n=nBlocks();
    el("f-picked").innerHTML = n ? ("<b>"+n+"</b> block"+(n>1?"s":"")+" selected: "+pickedList().map(blockLabel).map(esc).join(", ")) : "";
  }

  function onTask(){
    ST.task=this.value; ST.taskInfo=null;
    for(var i=0;i<ST.tasks.length;i++){ if(ST.tasks[i].name===ST.task){ ST.taskInfo=ST.tasks[i]; break; } }
    if(ST.taskInfo){
      el("f-kpi").innerHTML="Standard: <b>"+fmt(ST.taskInfo.daily_target)+" "+esc(ST.taskInfo.uom||"")+"/day</b> @ KES "+fmt(ST.taskInfo.rate,2)+" per "+esc(ST.taskInfo.uom||"unit");
    } else { el("f-kpi").textContent=""; }
    loadCompare();
    recalc();
  }

  function periodHours(){
    var f=el("f-from").value, t=el("f-to").value;
    if(!f||!t) return 0;
    var d=new Date(f+"T00:00:00"), e=new Date(t+"T00:00:00");
    if(isNaN(d)||isNaN(e)||e<d) return 0;
    var total=0, guard=0;
    while(d<=e && guard<400){
      var wd=d.getDay();
      if(wd===6) total+=6; else total+=8;
      d.setDate(d.getDate()+1); guard++;
    }
    return total;
  }
  function workingDays(){
    var f=el("f-from").value, t=el("f-to").value;
    if(!f||!t) return 0;
    var d=dayDiff(f,t)+1;
    return d>0?d:0;
  }
  function syncSlider(){
    var wd=workingDays(); var s=el("f-slider");
    if(wd>0){ if(wd>parseInt(s.max)) s.max=wd; s.value=wd; }
    el("f-wdlabel").textContent=wd;
  }
  function onSlider(){
    var wd=parseInt(this.value);
    el("f-wdlabel").textContent=wd;
    el("f-to").value=addDays(el("f-from").value||today(), wd-1);
    recalc();
  }

  function recalc(){
    var qty=parseFloat(el("f-qty").value)||0;
    var wd=workingDays();
    var info=ST.taskInfo;
    var tgt=info?info.daily_target:0;
    var rate=info?info.rate:0;
    var ppd=0;
    if(tgt>0 && wd>0){ ppd=Math.ceil(qty/tgt/wd); }
    var cost=qty*rate;
    el("o-ppl").textContent = ppd>0?fmt(ppd):"—";
    el("o-ppl-u").textContent = (info?fmt(tgt)+" "+(info.uom||"")+"/day":"crew size");
    el("o-pd").textContent = ppd>0?fmt(ppd*wd):"—";
    var th=periodHours();
    var hb=el("o-hrs"); if(hb) hb.textContent = th>0?fmt(th):"—";
    var ba=blockArea();
    var ab=el("o-area"); if(ab) ab.textContent = ba>0?(fmt(ba,2)):"—";
    el("o-cost").textContent = cost>0?fmt(cost):"—";
    var ready = ST.farm && nBlocks()>0 && ST.task && qty>0 && wd>0;
    el("b-draft").disabled=!ready;
    el("b-submit").disabled=!ready;
    var missing=[];
    if(!ST.farm) missing.push("select a farm");
    if(nBlocks()===0) missing.push("tap at least one block");
    if(!ST.task) missing.push("select a task");
    if(qty<=0) missing.push("enter a quantity");
    if(wd<=0) missing.push("set a valid date range");
    var hint=el("f-submit-hint");
    if(hint){
      if(missing.length){ hint.style.display="block"; hint.innerHTML="To submit: "+missing.join(" · "); }
      else { hint.style.display="none"; hint.innerHTML=""; }
    }
  }

  function loadCompare(){
    var box=el("o-compare");
    if(!(ST.farm && nBlocks()>0 && ST.task)){ return; }
    var firstBlock=pickedList()[0];
    call({action:"compare",farm:ST.farm,block:firstBlock,task:ST.task}).then(function(d){
      if(d.last){
        var L=d.last;
        box.innerHTML="Last approved for "+esc(blockLabel(firstBlock))+" + this task: <b>"+fmt(L.quantity)+"</b> units, <b>"+fmt(L.people_per_day)+"</b> ppl/day, <b>KES "+fmt(L.total_cost)+"</b> ("+esc(L.from_date)+" → "+esc(L.to_date)+").";
      } else {
        box.innerHTML="No prior approved request for this block + task — this will be the baseline.";
      }
    });
  }

  function doSubmit(submitNow){
    var args={ action:"submit", farm:ST.farm, blocks:pickedList().join(","), task:ST.task,
      quantity:parseFloat(el("f-qty").value)||0,
      from_date:el("f-from").value, to_date:el("f-to").value };
    if(submitNow) args.submit_now=1;
    if(ST.editingPlan) args.plan=ST.editingPlan;
    el("b-draft").disabled=true; el("b-submit").disabled=true;
    call(args).then(function(d){
      if(d.error){ toast("Error: "+d.error); recalc(); return; }
      var nb=(d.blocks||[]).length;
      var verb = d.editing ? (submitNow?"Updated & submitted ":"Draft updated ") : (submitNow?"Submitted ":"Draft saved ");
      toast(verb+d.name+" · "+d.workflow_state+(nb>1?" ("+nb+" blocks)":""));
      clearEdit();
      el("f-qty").value=""; ST.task=null; ST.taskInfo=null; ST.picked={}; el("f-task").value=""; el("f-kpi").textContent=""; syncBlockGrid();
      recalc();
      if(submitNow){ }
    }).catch(function(e){ toast("Failed to save"); recalc(); });
  }

  function clearEdit(){
    ST.editingPlan=null;
    var b=el("f-editbanner"); if(b){ b.style.display="none"; b.innerHTML=""; }
    var sb=el("b-submit"); if(sb) sb.textContent="Submit for Approval";
    var db=el("b-draft"); if(db) db.textContent="Save Draft";
  }

  function openPlanForEdit(name){
    call({action:"plan_detail", plan:name}).then(function(d){
      var p=d.plan;
      if(!p){ toast("Could not load plan"); return; }
      if(!p.editable){ toast("You can’t edit this plan ("+p.workflow_state+")"); return; }
      showTab("new");
      ST.editingPlan=p.name;
      var fs=el("f-farm"); fs.value=p.farm; ST.farm=p.farm;
      ST.picked={}; ST.task=null; ST.taskInfo=null;
      el("f-blockgrid").innerHTML="<div class='note'>Loading blocks…</div>";
      var pending=2;
      var done=function(){ pending--; if(pending>0) return;
        (p.blocks||[]).forEach(function(b){ ST.picked[b]=true; });
        syncBlockGrid();
        ST.task=p.task; el("f-task").value=p.task;
        for(var i=0;i<ST.tasks.length;i++){ if(ST.tasks[i].name===p.task){ ST.taskInfo=ST.tasks[i]; break; } }
        if(ST.taskInfo){ el("f-kpi").innerHTML="Standard: <b>"+fmt(ST.taskInfo.daily_target)+" "+esc(ST.taskInfo.uom||"")+"/day</b> @ KES "+fmt(ST.taskInfo.rate,2)+" per "+esc(ST.taskInfo.uom||"unit"); }
        el("f-qty").value=p.quantity;
        el("f-from").value=p.from_date; el("f-to").value=p.to_date;
        recalc();
        var byline=(p.requested_by && ST.roles && p.requested_by!==ST.roles.user) ? " · requested by "+esc(shortUser(p.requested_by)) : "";
        var b=el("f-editbanner");
        if(b){ b.style.display="block"; b.innerHTML="Editing <b>"+esc(p.name)+"</b> ("+esc(p.workflow_state)+byline+") — changes update this plan; resubmitting sends it back to Pending Approval. <a href='#' id='f-cancel-edit'>Cancel edit</a>";
          var c=document.getElementById("f-cancel-edit"); if(c) c.onclick=function(ev){ ev.preventDefault(); clearEdit(); el("f-qty").value=""; ST.task=null; ST.taskInfo=null; ST.picked={}; el("f-task").value=""; el("f-kpi").textContent=""; syncBlockGrid(); recalc(); toast("Edit cancelled"); }; }
        el("b-submit").textContent = "Update & Submit";
        el("b-draft").textContent = "Update Draft";
      };
      call({action:"blocks",farm:p.farm}).then(function(bd){
        ST.blocks=bd.blocks||[];
        var sel=el("f-block"); sel.innerHTML='<option value="">— add a block —</option>';
        ST.blocks.forEach(function(b){ var o=document.createElement("option"); o.value=b.name; o.textContent=b.label; sel.appendChild(o); });
        done();
      });
      call({action:"tasks",farm:p.farm}).then(function(td){
        ST.tasks=td.tasks||[];
        var sel=el("f-task"); sel.innerHTML='<option value="">— select task —</option>';
        ST.tasks.forEach(function(t){ var o=document.createElement("option"); o.value=t.name; o.textContent=t.subject; sel.appendChild(o); });
        done();
      });
    }).catch(function(e){ toast("Could not load plan"); });
  }

  function stateTag(s){
    var c="draft", t=s||"Draft";
    if(s==="Approved") c="appr"; else if(s==="Pending Approval") c="pend"; else if(s==="Rejected") c="rej";
    return '<span class="tag '+c+'">'+esc(t)+'</span>';
  }
  function editableState(s){ return s==="Draft" || s==="Rejected" || s==="Pending Approval"; }

  function loadMine(){
    var b=el("mine-body"); b.className="loading"; b.innerHTML="Loading…";
    call({action:"my_requests"}).then(function(d){
      var rows=d.requests||[];
      ST._farmScope = !!d.farm_scope;
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">You haven’t raised any requests yet.</div>'; return; }
      var fs=ST._farmScope;
      var sts={}; rows.forEach(function(r){ if(r.workflow_state) sts[r.workflow_state]=1; });
      b.className="";
      b.innerHTML='<div class="note" style="margin-bottom:8px">Click a row to see full details — mandays, hours, and rate breakdown.'+(fs?' Plans on your farm(s) raised by others are included — Draft, Rejected and Pending Approval ones can be edited.':'')+'</div>'
        + fbar(rows,{dates:true,statuses:Object.keys(sts).sort(),ph:"Search ref, farm, block, task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:r.workflow_state||"", date:isodate(r.from_date),
                hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.requested_by||"")).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Qty</th><th class="n">Ppl/Day</th><th class="n">Mandays</th><th class="n">Hours</th><th class="n">Cost (KES)</th><th>Period</th>'+(fs?'<th>By</th>':'')+'<th>Status</th></tr></thead><tbody>';
        var cols=fs?12:11;
        list.forEach(function(r, i){
          h+='<tr class="expandrow" data-i="'+i+'" style="cursor:pointer"><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.quantity)+'</td><td class="n">'+fmt(r.people_per_day)+'</td><td class="n m">'+fmt(r.person_days)+'</td><td class="n m">'+fmt(r.total_hours)+'</td><td class="n">'+fmt(r.total_cost)+'</td><td>'+esc(r.from_date)+' → '+esc(r.to_date)+'</td>'+(fs?'<td>'+(r.mine?'<b>me</b>':esc(shortUser(r.requested_by)))+'</td>':'')+'<td>'+stateTag(r.workflow_state)+'</td></tr>';
          h+='<tr class="detailrow" data-d="'+i+'" style="display:none"><td colspan="'+cols+'" style="background:var(--wash);padding:0"><div class="reqdetail" data-panel="'+i+'"></div></td></tr>';
        });
        body.innerHTML=h+'</tbody></table>';
        body.querySelectorAll(".expandrow").forEach(function(tr){
          tr.onclick=function(){
            var i=tr.getAttribute("data-i");
            var dr=body.querySelector('.detailrow[data-d="'+i+'"]');
            var open = dr.style.display!=="none";
            body.querySelectorAll(".detailrow").forEach(function(x){ x.style.display="none"; });
            if(!open){ dr.style.display=""; renderReqDetail(list[i], body.querySelector('.reqdetail[data-panel="'+i+'"]')); }
          };
        });
      });
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load: '+esc(e&&e.message?e.message:e)+'</div>'; });
  }
  function loadRejected(){
    var b=el("rej-body"); if(!b) return; b.className="loading"; b.innerHTML="Loading…";
    call({action:"my_requests"}).then(function(d){
      ST._farmScope = !!d.farm_scope;
      ST._rejRows=(d.requests||[]).filter(function(r){ return r.workflow_state==="Rejected"; });
      renderRej();
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load: '+esc(e&&e.message?e.message:e)+'</div>'; });
  }
  function renderRej(){
    var b=el("rej-body"); if(!b) return;
    var all=ST._rejRows||[];
    if(!all.length){ b.className=""; b.innerHTML='<div class="empty">Nothing rejected — you’re all clear.</div>'; return; }
    var isGm=ST.roles&&ST.roles.is_gm;
    var fs=ST._farmScope;
    var closeLabel=isGm?"Close plan":"Request close";
    b.className="";
    b.innerHTML='<div class="note" style="margin-bottom:8px">These plans were rejected'+(fs?' (yours and your farm’s)':'')+'. Click a row for full details, <b>Edit &amp; resubmit</b> to adjust and send back — or <b>'+closeLabel+'</b> if the plan should be stopped.</div>'
      + fbar(all,{dates:true,ph:"Search ref, farm, block, task…"});
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.requested_by||"")).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Ref</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Qty</th><th class="n">Ppl/Day</th><th class="n">Cost (KES)</th><th>Period</th>'+(fs?'<th>By</th>':'')+'<th>Status</th><th></th></tr></thead><tbody>';
      var cols=fs?11:10;
      rows.forEach(function(r, i){
        h+='<tr class="expandrow" data-i="'+i+'" style="cursor:pointer"><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.quantity)+'</td><td class="n">'+fmt(r.people_per_day)+'</td><td class="n">'+fmt(r.total_cost)+'</td><td>'+esc(r.from_date)+' → '+esc(r.to_date)+'</td>'+(fs?'<td>'+(r.mine?'<b>me</b>':esc(shortUser(r.requested_by)))+'</td>':'')+'<td>'+stateTag(r.workflow_state)+'</td>'+
          '<td><div class="btns"><button class="btn solid" data-edit="'+esc(r.name)+'">Edit &amp; resubmit</button><button class="btn" data-close="'+esc(r.name)+'">'+closeLabel+'</button></div></td></tr>';
        h+='<tr class="detailrow" data-d="'+i+'" style="display:none"><td colspan="'+cols+'" style="background:var(--wash);padding:0"><div class="reqdetail" data-panel="'+i+'"></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireReqExpand(body, rows);
      body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ openPlanForEdit(btn.getAttribute("data-edit")); }; });
      body.querySelectorAll("[data-close]").forEach(function(btn){ btn.onclick=function(){ openCloseDialog(btn.getAttribute("data-close"), loadRejected); }; });
    });
  }
  function renderReqDetail(r, box){
    if(!box) return;
    var uom=r.uom||"";
    var kpi=function(k,v){ return '<div style="min-width:110px"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:600">'+k+'</div><div style="font-size:16px;font-weight:700;margin-top:2px">'+v+'</div></div>'; };
    box.innerHTML=
      '<div style="padding:14px;display:flex;flex-wrap:wrap;gap:20px">'+
        kpi("Target", fmt(r.quantity)+' '+esc(uom))+
        kpi("People/Day", fmt(r.people_per_day))+
        kpi("Mandays", fmt(r.person_days))+
        kpi("Total Hours", fmt(r.total_hours)+' h')+
        kpi("Working Days", fmt(r.working_days))+
        kpi("Rate", 'KES '+fmt(r.rate,2)+' / '+esc(uom||"unit"))+
        kpi("Daily Target", fmt(r.daily_target)+' '+esc(uom))+
        kpi("Total Cost", 'KES '+fmt(r.total_cost))+
      '</div>'+
      '<div style="padding:0 14px 12px;font-size:11px;color:var(--mute)">'+
        (r.requested_by?'Requested by <b>'+esc(shortUser(r.requested_by))+'</b> · ':'')+
        'Hours model: Mon–Fri 8h · Sat 6h · Sun 8h across '+esc(r.from_date)+' → '+esc(r.to_date)+'. Open in ERP: <a href="/app/work-management-planner/'+encodeURIComponent(r.name)+'" target="_blank">'+esc(r.name)+'</a></div>'+
      (editableState(r.workflow_state) ? '<div style="padding:0 14px 14px"><button class="btn solid" data-edit="'+esc(r.name)+'">Edit this plan</button></div>' : '');
    var eb=box.querySelector('[data-edit]');
    if(eb){ eb.onclick=function(ev){ ev.stopPropagation(); openPlanForEdit(eb.getAttribute("data-edit")); }; }
  }

  function wireReqExpand(body, list){
    body.querySelectorAll(".expandrow").forEach(function(tr){
      tr.onclick=function(ev){
        var t=ev.target;
        while(t && t!==tr){ if(t.tagName==="BUTTON"||t.tagName==="A"||t.tagName==="INPUT"||t.tagName==="SELECT") return; t=t.parentNode; }
        var i=tr.getAttribute("data-i");
        var dr=body.querySelector('.detailrow[data-d="'+i+'"]');
        var open=dr && dr.style.display!=="none";
        body.querySelectorAll(".detailrow").forEach(function(x){ x.style.display="none"; });
        if(!open && dr){ dr.style.display=""; renderReqDetail(list[i], body.querySelector('.reqdetail[data-panel="'+i+'"]')); }
      };
    });
  }
  function loadAppr(){
    var b=el("appr-body"); b.className="loading"; b.innerHTML="Loading…";
    call({action:"pending"}).then(function(d){
      ST._apprRows=d.pending||[];
      renderAppr();
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load: '+esc(e&&e.message?e.message:e)+'</div>'; });
  }
  function renderAppr(){
    var b=el("appr-body"); if(!b) return;
    var all=ST._apprRows||[];
    if(!all.length){ b.className=""; b.innerHTML='<div class="empty">Nothing awaiting approval.</div>'; return; }
    b.className="";
    b.innerHTML='<div class="note" style="margin-bottom:8px">Click a row for full details. Approve, reject — or <b>Edit</b> to adjust the plan yourself; edits send it back through Pending Approval.</div>'
      + fbar(all,{dates:true,ph:"Search ref, farm, block, task, requested by…"});
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.requested_by||"")).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Ref</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Qty</th><th class="n">Ppl/Day</th><th class="n">Mandays</th><th class="n">Hours</th><th class="n">Cost (KES)</th><th>Period</th><th>By</th><th>Action</th></tr></thead><tbody>';
      rows.forEach(function(r, i){
        h+='<tr class="expandrow" data-i="'+i+'" style="cursor:pointer"><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td><td class="n">'+fmt(r.quantity)+'</td><td class="n">'+fmt(r.people_per_day)+'</td><td class="n m">'+fmt(r.person_days)+'</td><td class="n m">'+fmt(r.total_hours)+'</td><td class="n">'+fmt(r.total_cost)+'</td><td>'+esc(r.from_date)+' → '+esc(r.to_date)+'</td><td>'+esc(shortUser(r.requested_by))+'</td><td><div class="ib"><button class="btn solid" data-app="'+esc(r.name)+'">Approve</button><button class="btn" data-editp="'+esc(r.name)+'">Edit</button><button class="btn" data-rej="'+esc(r.name)+'">Reject</button></div></td></tr>';
        h+='<tr class="detailrow" data-d="'+i+'" style="display:none"><td colspan="12" style="background:var(--wash);padding:0"><div class="reqdetail" data-panel="'+i+'"></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireReqExpand(body, rows);
      body.querySelectorAll("[data-app]").forEach(function(btn){ btn.onclick=function(){ act("approve", btn.getAttribute("data-app")); }; });
      body.querySelectorAll("[data-editp]").forEach(function(btn){ btn.onclick=function(){ openPlanForEdit(btn.getAttribute("data-editp")); }; });
      body.querySelectorAll("[data-rej]").forEach(function(btn){ btn.onclick=function(){ act("reject", btn.getAttribute("data-rej")); }; });
    });
  }
  function act(which,name){
    call({action:which,name:name}).then(function(d){
      if(d.error){ toast("Error: "+d.error); return; }
      toast(name+" → "+d.workflow_state);
      loadAppr();
    }).catch(function(e){ toast("Action failed"); });
  }

  function boot(){
    Promise.all([ call({action:"meta"}), call({action:"roles"}) ]).then(function(res){
      var meta=res[0], roles=res[1];
      ST.roles=roles;
      el("wp-who").textContent=(roles.user||"")+(roles.is_approver?" · Approver":"");
      initNew(meta);
      buildTabs();
    }).catch(function(e){
      el("wp-who").textContent="Load error: "+(e&&e.message?e.message:e);
    });
  }
  if(typeof frappe==="undefined"){
    document.getElementById("wp-who").textContent="Open this inside Frappe (logged in).";
  } else { boot(); }
})();
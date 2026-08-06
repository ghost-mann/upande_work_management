(function(){
  var API = "/api/method/wm_planner";
  var ST = { farm:null, picked:{}, task:null, taskInfo:null, tasks:[], blocks:[], roles:null };

  function call(args, method){
    var ep = "/api/method/" + (method || "wm_planner");
    var writes = {submit:1, approve:1, reject:1, week_approve:1, week_return:1,
                  save:1, submit_for_review:1, decide_line:1, gm_approve:1};
    var isWrite = writes[args.action] === 1;
    var p = new URLSearchParams();
    for(var k in args){ if(args[k]!==undefined && args[k]!==null) p.append(k, args[k]); }
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    if(!isWrite){
      return fetch(ep + "?" + p.toString(), {
        method: "GET", headers: { "Accept": "application/json" }, credentials: "same-origin"
      }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
        .then(function(j){ return j.message || {}; });
    }
    return fetch(ep, {
      method: "POST",
      headers: { "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body: p.toString(), credentials: "same-origin"
    }).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); })
      .then(function(j){ return j.message || {}; });
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function fmtRate(n){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{maximumFractionDigits:4}); }
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

  // ── master plan: the budget the planner draws down against ──────────────
  var MP = { roles:null, inited:false };
  function loadMasterPlans(){
    if(!MP.inited){
      MP.inited=true;
      el("mp-refresh").onclick=loadMasterPlans;
      el("mp-farm").onchange=loadMasterPlans;
      el("mp-state").onchange=loadMasterPlans;
      el("mp-new").onclick=function(){ mpOpenForm(null, loadMasterPlans); };
    }
    var box=el("mp-body");
    box.innerHTML='<div class="empty">Loading…</div>';
    call({ action:"meta" }, "wm_masterplan").then(function(m){
      MP.roles=m;
      var fs=el("mp-farm");
      if(fs && !fs.options.length){
        var oAll=document.createElement("option"); oAll.value=""; oAll.textContent="All farms"; fs.appendChild(oAll);
        (m.farms||[]).forEach(function(f){
          var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o);
        });
      }
      if(el("mp-new")) el("mp-new").style.display = m.can_edit ? "" : "none";
      return call({ action:"list", farm:(el("mp-farm").value||""),
                    state:(el("mp-state").value||"") }, "wm_masterplan");
    }).then(function(d){
      var rows=d.plans||[];
      if(!rows.length){
        var fv=el("mp-farm").value;
        box.innerHTML='<div class="empty">No master plans'+(fv?(" for "+esc(fv)):"")+' yet.</div>';
        return;
      }
      var h='<table><thead><tr><th>Master plan</th><th>Farm</th><th>Period</th>'+
        '<th class="n">Activities</th><th class="n">Man days</th><th class="n">Budget KES</th>'+
        '<th>Status</th><th>Raised by</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr><td class="m" style="font-size:10px"><a href="#" data-mp="'+esc(r.name)+'">'+esc(r.name)+'</a></td>'+
           '<td>'+esc(r.farm||"")+'</td>'+
           '<td class="m" style="font-size:10px">'+esc(r.period_from)+' → '+esc(r.period_to)+'</td>'+
           '<td class="n m">'+fmt(r.total_activities)+'</td>'+
           '<td class="n m">'+fmt(r.total_man_days)+'</td>'+
           '<td class="n m">'+fmt(r.total_cost,2)+'</td>'+
           '<td style="font-size:10px">'+esc(r.workflow_state||"")+'</td>'+
           '<td style="font-size:10px">'+esc((r.raised_by||"").split("@")[0])+'</td></tr>';
      });
      box.innerHTML=h+'</tbody></table>';
      box.querySelectorAll("[data-mp]").forEach(function(a){
        a.onclick=function(ev){ ev.preventDefault(); openMasterPlan(a.getAttribute("data-mp")); };
      });
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function openMasterPlan(name){
    var box=el("mp-body");
    box.innerHTML='<div class="empty">Loading…</div>';
    call({ action:"get", name:name }, "wm_masterplan").then(function(d){
      if(d.error){ toast(d.error); return; }
      var p=d.plan, acts=d.activities||[];
      // "get" reads the last-persisted planned/remaining figures, which only "headroom"
      // refreshes -- pull it for this plan's own period so "Left" is never stale.
      return call({ action:"headroom", farm:p.farm, from_date:p.period_from, to_date:p.period_to },
                  "wm_masterplan").then(function(hd){
        var byRow={};
        (hd.activities||[]).forEach(function(x){ byRow[x.row]=x; });
        acts.forEach(function(a){
          var live=byRow[a.name];
          if(live){ a.planned_qty=live.planned_qty; a.planned_cost=live.planned_cost;
                    a.remaining_qty=live.remaining_qty; a.remaining_cost=live.remaining_cost; }
        });
        return {p:p, acts:acts, rate_drift:d.rate_drift,
                can_edit:d.can_edit, can_decide:d.can_decide, can_gm_approve:d.can_gm_approve};
      }).catch(function(){ return {p:p, acts:acts, rate_drift:d.rate_drift,
                can_edit:d.can_edit, can_decide:d.can_decide, can_gm_approve:d.can_gm_approve}; });
    }).then(function(res){
      if(!res) return;
      var p=res.p, acts=res.acts;
      var h='<div class="sech">'+esc(p.name)+' · '+esc(p.farm)+' · '+esc(p.period_from)+' → '+
            esc(p.period_to)+' · '+esc(p.workflow_state)+'</div>';
      // hiding these is only a convenience -- every rule they call is re-checked
      // and re-reported by the server, never trusted from these flags alone
      if(res.can_edit || res.can_decide || res.can_gm_approve){
        h+='<div class="btns" style="margin:8px 0 4px">';
        if(res.can_edit){
          h+='<button type="button" class="btn" id="mp-edit">Edit</button>'+
             '<button type="button" class="btn solid" id="mp-submitrev">Submit for review</button>';
        }
        if(res.can_decide){
          h+='<button type="button" class="btn" id="mp-rejectdoc" style="color:#b91c1c;border-color:#fca5a5">Reject entire plan</button>';
        }
        if(res.can_gm_approve){
          h+='<button type="button" class="btn solid" id="mp-gmapprove">GM Approve</button>'+
             '<button type="button" class="btn" id="mp-rejectdoc" style="color:#b91c1c;border-color:#fca5a5">Reject</button>';
        }
        h+='</div>';
      }
      if((res.rate_drift||[]).length){
        h+='<div style="margin:8px 0;padding:10px 14px;border:1px solid #bfdbfe;background:#eff6ff;border-radius:10px;font-size:12px">'+
           '<b>Rates have changed since this plan was budgeted.</b> The money is fixed, '+
           'so fewer units now fit the same budget:<ul style="margin:6px 0 0 16px">';
        res.rate_drift.forEach(function(x){
          h+='<li>'+esc(x.task)+' — budgeted at '+fmt(x.budget_rate,6)+', now '+fmt(x.live_rate,6)+
             ' (same work would cost '+fmt(x.cost_at_live_rate,2)+')</li>';
        });
        h+='</ul></div>';
      }
      h+='<div class="note" style="margin-bottom:8px">Click an activity to see which plans are drawing on its budget — including stale drafts still holding it.</div>';
      var mpColspan = res.can_decide ? 12 : 11;
      h+='<table><thead><tr><th>Activity</th><th class="n">Man days</th><th class="n">Days</th>'+
         '<th class="n">Work</th><th>Unit</th><th class="n">Rate</th><th class="n">Cost</th>'+
         '<th class="n">Planned</th><th class="n">Left</th><th>Consultant</th><th>Remarks</th>'+
         (res.can_decide?'<th>Decide</th>':'')+'</tr></thead><tbody>';
      acts.forEach(function(a,i){
        var exhausted = (a.remaining_qty!=null && a.remaining_qty<=0.005) ||
                        (a.remaining_cost!=null && a.remaining_cost<=0.005);
        h+='<tr class="mp-actrow" data-ai="'+i+'" style="cursor:pointer"><td>'+esc(a.task)+'</td><td class="n m">'+fmt(a.man_days)+'</td>'+
           '<td class="n m">'+fmt(a.days)+'</td><td class="n m">'+fmt(a.work_qty)+'</td>'+
           '<td>'+esc(a.uom||"")+'</td><td class="n m">'+fmt(a.rate,6)+'</td>'+
           '<td class="n m">'+fmt(a.cost,2)+'</td><td class="n m">'+fmt(a.planned_qty)+'</td>'+
           '<td class="n m">'+fmt(a.remaining_qty)+
           (exhausted?' <span style="color:#b91c1c;font-weight:600;font-size:9px;text-transform:uppercase">used up</span>':'')+'</td>'+
           '<td style="font-size:10px">'+esc(a.consultant_state||"")+
           (a.original_qty?(' <span class="hint">was '+fmt(a.original_qty)+'</span>'):'')+'</td>'+
           '<td style="font-size:10px">'+esc(a.remarks||"")+'</td>'+
           (res.can_decide?(
             '<td onclick="event.stopPropagation()" style="min-width:150px">'+
             '<select class="mp-dec-state" data-i="'+i+'" style="width:100%">'+
               '<option value="">— decide —</option><option value="OK">OK</option>'+
               '<option value="Edit work">Edit work</option><option value="Rejected">Rejected</option>'+
             '</select>'+
             '<input type="number" class="mp-dec-qty" data-i="'+i+'" placeholder="revised qty" '+
               'style="margin-top:4px;display:none;width:100%">'+
             '<input type="text" class="mp-dec-remarks" data-i="'+i+'" placeholder="remarks" style="margin-top:4px;width:100%">'+
             '<button type="button" class="btn sm mp-dec-save" data-i="'+i+'" style="margin-top:4px">Save decision</button>'+
             '</td>'
           ):'')+'</tr>';
        h+='<tr class="mp-actdetail" data-ad="'+i+'" style="display:none"><td colspan="'+mpColspan+'" style="background:var(--wash);padding:0">'+
           '<div class="mp-consumers" data-panel="'+i+'"></div></td></tr>';
      });
      h+='</tbody></table>';
      box.innerHTML=h;
      var mpEditBtn=el("mp-edit");
      if(mpEditBtn) mpEditBtn.onclick=function(){ mpOpenForm(p.name, function(nm){ openMasterPlan(nm); }); };
      var mpSubBtn=el("mp-submitrev");
      if(mpSubBtn) mpSubBtn.onclick=function(){
        mpSubBtn.disabled=true;
        call({action:"submit_for_review", name:p.name}, "wm_masterplan").then(function(d2){
          if(d2.error){ toast(d2.error); mpSubBtn.disabled=false; return; }
          toast(p.name+" submitted for review");
          openMasterPlan(p.name);
        }).catch(function(){ toast("Could not submit"); mpSubBtn.disabled=false; });
      };
      var mpRejBtn=el("mp-rejectdoc");
      if(mpRejBtn) mpRejBtn.onclick=function(){
        mpRejBtn.disabled=true;
        call({action:"reject", name:p.name}, "wm_masterplan").then(function(d2){
          if(d2.error){ toast(d2.error); mpRejBtn.disabled=false; return; }
          toast(p.name+" rejected");
          openMasterPlan(p.name);
        }).catch(function(){ toast("Could not reject"); mpRejBtn.disabled=false; });
      };
      var mpGmBtn=el("mp-gmapprove");
      if(mpGmBtn) mpGmBtn.onclick=function(){
        mpGmBtn.disabled=true;
        call({action:"gm_approve", name:p.name}, "wm_masterplan").then(function(d2){
          if(d2.error){ toast(d2.error); mpGmBtn.disabled=false; return; }
          toast(p.name+" approved");
          openMasterPlan(p.name);
        }).catch(function(){ toast("Could not approve"); mpGmBtn.disabled=false; });
      };
      if(res.can_decide){
        box.querySelectorAll(".mp-dec-state").forEach(function(sel){
          sel.onchange=function(){
            var i=this.getAttribute("data-i");
            var qi=box.querySelector('.mp-dec-qty[data-i="'+i+'"]');
            if(qi) qi.style.display = (this.value==="Edit work") ? "" : "none";
          };
        });
        box.querySelectorAll(".mp-dec-save").forEach(function(btn){
          btn.onclick=function(){
            var i=btn.getAttribute("data-i");
            var sel=box.querySelector('.mp-dec-state[data-i="'+i+'"]');
            var qi=box.querySelector('.mp-dec-qty[data-i="'+i+'"]');
            var ri=box.querySelector('.mp-dec-remarks[data-i="'+i+'"]');
            var state=sel.value;
            if(!state){ toast("Choose OK, Edit work or Rejected"); return; }
            var args={ action:"decide_line", row:acts[i].name, state:state, remarks:ri.value||"" };
            if(state==="Edit work") args.work_qty=parseFloat(qi.value)||0;
            btn.disabled=true;
            call(args, "wm_masterplan").then(function(dd){
              if(dd.error){ toast(dd.error); btn.disabled=false; return; }
              toast("Line "+dd.state+(dd.moved_to?(" · plan moved to "+dd.moved_to):""));
              openMasterPlan(p.name);
            }).catch(function(){ toast("Could not save decision"); btn.disabled=false; });
          };
        });
      }
      box.querySelectorAll(".mp-actrow").forEach(function(tr){
        tr.onclick=function(ev){
          var t=ev.target;
          while(t && t!==tr){ if(t.tagName==="BUTTON"||t.tagName==="A"||t.tagName==="INPUT"||t.tagName==="SELECT") return; t=t.parentNode; }
          var i=parseInt(tr.getAttribute("data-ai"),10);
          var dr=box.querySelector('.mp-actdetail[data-ad="'+i+'"]');
          var open=dr && dr.style.display!=="none";
          box.querySelectorAll(".mp-actdetail").forEach(function(x){ x.style.display="none"; });
          if(open || !dr) return;
          dr.style.display="";
          var panel=box.querySelector('.mp-consumers[data-panel="'+i+'"]');
          panel.innerHTML='<div class="empty">Loading…</div>';
          call({ action:"consumers", row: acts[i].name }, "wm_masterplan").then(function(cd){
            if(cd.error){ panel.innerHTML='<div class="empty">'+esc(cd.error)+'</div>'; return; }
            var rows=cd.plans||[], stale=cd.stale_drafts||[];
            if(!rows.length){ panel.innerHTML='<div class="empty">Nothing is drawing on this line yet.</div>'; return; }
            var ph='<table><thead><tr><th>Plan</th><th>Block</th><th>Period</th><th class="n">Qty</th>'+
                   '<th class="n">Cost</th><th>Status</th><th>Requested by</th></tr></thead><tbody>';
            rows.forEach(function(r){
              var isStale = stale.indexOf(r.name)>-1;
              ph+='<tr><td class="m" style="font-size:10px">'+esc(r.name)+'</td>'+
                  '<td style="font-size:10px">'+esc(lbl(r.block_section))+'</td>'+
                  '<td class="m" style="font-size:10px">'+esc(r.from_date)+' → '+esc(r.to_date)+'</td>'+
                  '<td class="n m">'+fmt(r.quantity)+'</td><td class="n m">'+fmt(r.total_cost,2)+'</td>'+
                  '<td style="font-size:10px">'+esc(r.workflow_state||"")+
                  (isStale?' <span style="color:#a06000;font-weight:600">(stale draft — still holding budget)</span>':'')+'</td>'+
                  '<td style="font-size:10px">'+esc(shortUser(r.requested_by))+'</td></tr>';
            });
            ph+='</tbody></table>';
            panel.innerHTML=ph;
          }).catch(function(e){ panel.innerHTML='<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
        };
      });
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not open: '+esc(e.message)+'</div>'; });
  }

  // ── master plan: create / edit form ──────────────────────────────────
  // The server sources rate + cost itself from the Work Task Rate in force
  // on Period From (falling back to Task.custom_rate) -- never sent here,
  // only mirrored so the budget is visible before Save. man_days/days are
  // reporting fields only: nothing below treats them as a ceiling.
  var MPF = { editing:null, rows:[], catalog:[], onSaved:null };

  function mpTaskOptions(selected){
    var h='<option value="">— select task —</option>';
    MPF.catalog.forEach(function(t){
      h+='<option value="'+esc(t.name)+'"'+(t.name===selected?' selected':'')+'>'+esc(t.subject)+'</option>';
    });
    return h;
  }
  function mpCatalogEntry(task){
    for(var i=0;i<MPF.catalog.length;i++){ if(MPF.catalog[i].name===task) return MPF.catalog[i]; }
    return null;
  }
  function mpRowMarkup(r,i){
    var c=mpCatalogEntry(r.task);
    var rate=c?c.rate:0, unit=c?(c.uom||""):"";
    var cost=(r.work_qty||0)*rate;
    return '<tr data-i="'+i+'">'+
      '<td><select class="mpf-r-task" data-i="'+i+'">'+mpTaskOptions(r.task)+'</select></td>'+
      '<td><input type="number" class="mpf-r-md" data-i="'+i+'" min="0" step="any" value="'+(r.man_days||"")+'"></td>'+
      '<td><input type="number" class="mpf-r-days" data-i="'+i+'" min="0" step="1" value="'+(r.days||"")+'"></td>'+
      '<td><input type="number" class="mpf-r-qty" data-i="'+i+'" min="0" step="any" value="'+(r.work_qty||"")+'"></td>'+
      '<td class="mpf-r-unit" data-i="'+i+'">'+esc(unit||"—")+'</td>'+
      '<td class="n m mpf-r-rate" data-i="'+i+'">'+(c?fmt(rate,6):"—")+'</td>'+
      '<td class="n m mpf-r-cost" data-i="'+i+'">'+(c?fmt(cost,2):"—")+'</td>'+
      '<td><button type="button" class="btn sm mpf-r-remove" data-i="'+i+'">&times;</button></td>'+
    '</tr>';
  }
  function mpRenderRows(){
    var tb=el("mpf-rows"); if(!tb) return;
    tb.innerHTML=MPF.rows.map(mpRowMarkup).join("");
    mpWireRows();
    mpUpdateTotals();
  }
  function mpRenderRowCalc(i){
    var r=MPF.rows[i]; var c=mpCatalogEntry(r.task);
    var rate=c?c.rate:0, unit=c?(c.uom||""):"";
    var cost=(r.work_qty||0)*rate;
    var tb=el("mpf-rows"); if(!tb) return;
    var u=tb.querySelector('.mpf-r-unit[data-i="'+i+'"]'); if(u) u.textContent=unit||"—";
    var rt=tb.querySelector('.mpf-r-rate[data-i="'+i+'"]'); if(rt) rt.textContent=c?fmt(rate,6):"—";
    var co=tb.querySelector('.mpf-r-cost[data-i="'+i+'"]'); if(co) co.textContent=c?fmt(cost,2):"—";
  }
  function mpWireRows(){
    var tb=el("mpf-rows"); if(!tb) return;
    tb.querySelectorAll(".mpf-r-task").forEach(function(s){
      s.onchange=function(){ var i=parseInt(this.getAttribute("data-i"),10); MPF.rows[i].task=this.value; mpRenderRowCalc(i); mpUpdateTotals(); };
    });
    tb.querySelectorAll(".mpf-r-md").forEach(function(s){
      s.oninput=function(){ var i=parseInt(this.getAttribute("data-i"),10); MPF.rows[i].man_days=parseFloat(this.value)||0; };
    });
    tb.querySelectorAll(".mpf-r-days").forEach(function(s){
      s.oninput=function(){ var i=parseInt(this.getAttribute("data-i"),10); MPF.rows[i].days=parseFloat(this.value)||0; };
    });
    tb.querySelectorAll(".mpf-r-qty").forEach(function(s){
      s.oninput=function(){ var i=parseInt(this.getAttribute("data-i"),10); MPF.rows[i].work_qty=parseFloat(this.value)||0; mpRenderRowCalc(i); mpUpdateTotals(); };
    });
    tb.querySelectorAll(".mpf-r-remove").forEach(function(b){
      b.onclick=function(){ var i=parseInt(this.getAttribute("data-i"),10); MPF.rows.splice(i,1); mpRenderRows(); };
    });
  }
  function mpUpdateTotals(){
    var t=el("mpf-totals"); if(!t) return;
    var md=0, cost=0;
    MPF.rows.forEach(function(r){
      md+=r.man_days||0;
      var c=mpCatalogEntry(r.task);
      if(c) cost+=(r.work_qty||0)*c.rate;
    });
    t.textContent=MPF.rows.length+" activit"+(MPF.rows.length===1?"y":"ies")+" · "+fmt(md)+" mandays · KES "+fmt(cost,2)+" budgeted";
  }
  function mpRefreshCatalog(){
    var fs=el("mpf-farm"), fr=el("mpf-from");
    if(!fs || !fr) return;
    var farm=fs.value, from=fr.value;
    if(!farm || !from){ MPF.catalog=[]; mpRenderRows(); return; }
    call({action:"pickable_tasks", farm:farm, period_from:from}, "wm_masterplan").then(function(d){
      if(d.error){ toast(d.error); MPF.catalog=[]; }
      else { MPF.catalog=d.tasks||[]; }
      mpRenderRows();
    }).catch(function(){ toast("Could not load tasks for this farm"); });
  }
  function mpFormShell(){
    return '<div style="background:#fff;max-width:960px;width:96%;max-height:92vh;display:flex;flex-direction:column;border:2px solid var(--ink)">'+
      '<div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--faint)">'+
        '<div style="font-size:13px;font-weight:700" id="mpf-title">New master plan</div>'+
        '<button type="button" id="mpf-x" style="border:none;background:none;font-size:20px;line-height:1;color:var(--mute);cursor:pointer">&times;</button>'+
      '</div>'+
      '<div style="padding:16px 18px;overflow:auto;flex:1">'+
        '<div class="row">'+
          '<div><label class="fl">Farm</label><select id="mpf-farm"><option value="">— select farm —</option></select></div>'+
          '<div><label class="fl">Period From</label><input type="date" id="mpf-from"></div>'+
          '<div><label class="fl">Period To</label><input type="date" id="mpf-to"></div>'+
        '</div>'+
        '<div class="sech" style="margin-top:18px">Activities</div>'+
        '<table><thead><tr><th>Task</th><th class="n">Man Days</th><th class="n">Days</th>'+
          '<th class="n">Work Qty</th><th>Unit</th><th class="n">Rate</th><th class="n">Cost</th><th></th></tr></thead>'+
          '<tbody id="mpf-rows"></tbody></table>'+
        '<button type="button" class="btn" id="mpf-addrow" style="margin-top:10px">+ Add activity</button>'+
        '<div class="note" style="margin-top:10px">Rate is the one in force on Period From — the same rate the '+
        'server freezes onto the line when you save. Man Days and Days are recorded for reporting only; Work Qty '+
        'is what the budget is measured against.</div>'+
      '</div>'+
      '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 18px;border-top:1px solid var(--faint);flex-wrap:wrap">'+
        '<div style="font-size:11.5px;color:var(--mute)" id="mpf-totals"></div>'+
        '<div class="btns">'+
          '<button type="button" class="btn" id="mpf-cancel">Cancel</button>'+
          '<button type="button" class="btn" id="mpf-save">Save Draft</button>'+
          '<button type="button" class="btn solid" id="mpf-submit">Save &amp; submit for review</button>'+
        '</div>'+
      '</div>'+
    '</div>';
  }
  function mpCloseForm(){
    var dlg=el("mp-formdialog"); if(!dlg) return;
    dlg.style.display="none"; dlg.innerHTML="";
  }
  function mpCollectPayload(){
    var farm=el("mpf-farm").value, from=el("mpf-from").value, to=el("mpf-to").value;
    var acts=MPF.rows.filter(function(r){ return r.task; }).map(function(r){
      return { task:r.task, man_days:r.man_days||0, days:r.days||0, work_qty:r.work_qty||0 };
    });
    return { farm:farm, period_from:from, period_to:to, acts:acts };
  }
  function mpDoSave(submitAfter, saveBtn, submitBtn){
    var p=mpCollectPayload();
    var missing=[];
    if(!p.farm) missing.push("select a farm");
    if(!p.period_from || !p.period_to) missing.push("set the period");
    if(!p.acts.length) missing.push("add at least one activity with a task");
    if(missing.length){ toast("To save: "+missing.join(" · ")); return; }
    saveBtn.disabled=true; submitBtn.disabled=true;
    var args={ action:"save", farm:p.farm, period_from:p.period_from, period_to:p.period_to,
               activities:JSON.stringify(p.acts) };
    if(MPF.editing) args.name=MPF.editing;
    // the server is the only real gate here -- overlap with an approved plan,
    // duplicate tasks, an out-of-order period, all come back as d.error text,
    // surfaced verbatim rather than pre-guessed client-side
    call(args, "wm_masterplan").then(function(d){
      if(d.error){ toast(d.error); saveBtn.disabled=false; submitBtn.disabled=false; return; }
      var savedName=d.name;
      if(!submitAfter){
        toast("Draft saved: "+savedName);
        mpCloseForm();
        if(typeof MPF.onSaved==="function") MPF.onSaved(savedName);
        return;
      }
      call({action:"submit_for_review", name:savedName}, "wm_masterplan").then(function(sd){
        if(sd.error){ toast("Saved as Draft, but could not submit: "+sd.error); saveBtn.disabled=false; submitBtn.disabled=false; return; }
        toast(savedName+" saved and submitted for review");
        mpCloseForm();
        if(typeof MPF.onSaved==="function") MPF.onSaved(savedName);
      }).catch(function(){ toast("Saved as Draft, but the submit call failed"); saveBtn.disabled=false; submitBtn.disabled=false; });
    }).catch(function(){ toast("Could not save"); saveBtn.disabled=false; submitBtn.disabled=false; });
  }
  function mpOpenForm(existingName, onSaved){
    var dlg=el("mp-formdialog"); if(!dlg) return;
    MPF.editing=existingName||null;
    MPF.rows=[]; MPF.catalog=[];
    MPF.onSaved=onSaved||loadMasterPlans;
    dlg.innerHTML=mpFormShell();
    dlg.style.display="flex";
    var farms=(MP.roles&&MP.roles.farms)||[];
    var fs=el("mpf-farm");
    farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); });
    function shut(){ mpCloseForm(); }
    el("mpf-x").onclick=shut; el("mpf-cancel").onclick=shut;
    dlg.onclick=function(ev){ if(ev.target===dlg) shut(); };
    el("mpf-addrow").onclick=function(){ MPF.rows.push({task:"",man_days:0,days:0,work_qty:0}); mpRenderRows(); };
    fs.onchange=mpRefreshCatalog;
    el("mpf-from").onchange=mpRefreshCatalog;
    var saveBtn=el("mpf-save"), submitBtn=el("mpf-submit");
    saveBtn.onclick=function(){ mpDoSave(false, saveBtn, submitBtn); };
    submitBtn.onclick=function(){ mpDoSave(true, saveBtn, submitBtn); };
    if(existingName){
      el("mpf-title").textContent="Edit "+existingName;
      call({action:"get", name:existingName}, "wm_masterplan").then(function(d){
        if(d.error){ toast(d.error); shut(); return; }
        var p=d.plan;
        fs.value=p.farm;
        el("mpf-from").value=isodate(p.period_from);
        el("mpf-to").value=isodate(p.period_to);
        MPF.rows=(d.activities||[]).map(function(a){
          return { task:a.task, man_days:a.man_days||0, days:a.days||0, work_qty:a.work_qty||0 };
        });
        mpRefreshCatalog();
      }).catch(function(){ toast("Could not load plan for editing"); shut(); });
    } else {
      el("mpf-title").textContent="New master plan";
      MPF.rows=[{task:"",man_days:0,days:0,work_qty:0}];
      mpRenderRows();
    }
  }

  function buildTabs(){
    var tabs=[["new","New Request"],["mine","My Requests"],["rej","Rejected"]];
    if(ST.roles && ST.roles.is_approver) tabs.push(["appr","Approvals"]);
    tabs.push(["week","Weekly review"]);
    tabs.push(["mp","Master plan"]);
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
    ["new","mine","rej","appr","week","mp"].forEach(function(n){ var p=el("p-"+n); if(p) p.classList.toggle("on", n===name); });
    document.querySelectorAll("#wp-tabs button").forEach(function(b){ b.setAttribute("aria-selected", b.getAttribute("data-tab")===name); });
    if(name==="mine") loadMine();
    if(name==="rej") loadRejected();
    if(name==="appr") loadAppr();
    if(name==="week") initWeekBoard();
    if(name==="mp") loadMasterPlans();
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
      ST.tasks.forEach(function(t){
        var o=document.createElement("option");
        o.value=t.name;
        o.textContent=t.subject+" · "+fmt(t.remaining_qty)+" "+(t.uom||"")+" / KES "+fmt(t.remaining_cost,0)+" left";
        if(t.exhausted){ o.disabled=true; o.textContent=t.subject+" · budget used up"; }
        sel.appendChild(o);
      });
      if(d.blocked_reason){
        sel.innerHTML="";
        toast(d.blocked_reason);
      }
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
      el("f-kpi").innerHTML="Standard: <b>"+fmt(ST.taskInfo.daily_target)+" "+esc(ST.taskInfo.uom||"")+"/day</b> @ KES "+fmtRate(ST.taskInfo.rate)+" per "+esc(ST.taskInfo.uom||"unit");
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
        if(ST.taskInfo){ el("f-kpi").innerHTML="Standard: <b>"+fmt(ST.taskInfo.daily_target)+" "+esc(ST.taskInfo.uom||"")+"/day</b> @ KES "+fmtRate(ST.taskInfo.rate)+" per "+esc(ST.taskInfo.uom||"unit"); }
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
        kpi("Rate", 'KES '+fmtRate(r.rate)+' / '+esc(uom||"unit"))+
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


  // ── one plan, end to end ────────────────────────────────────────────────
  // The weekly board could only show a plan's own row, so there was no way to
  // answer "who approved this, and who actually worked it". Clicking a plan
  // opens its full trail: approval chain, crews, the people on them, what they
  // recorded and what it cost.
  function ensurePlanModal(){
    if(el("wp-tr-overlay")) return;
    var d=document.createElement("div");
    d.id="wp-tr-overlay";
    d.style.cssText="display:none;position:fixed;inset:0;background:rgba(20,18,12,.42);z-index:900;padding:4vh 4vw;overflow:auto";
    d.innerHTML='<div style="max-width:960px;margin:0 auto;background:#fff;border-radius:16px;'+
      'box-shadow:0 40px 80px -30px rgba(10,10,10,.45);padding:20px 24px">'+
      '<div style="display:flex;align-items:flex-start;gap:12px">'+
        '<div style="flex:1"><div id="wp-tr-title" style="font-size:17px;font-weight:700"></div>'+
        '<div id="wp-tr-sub" style="font-size:11px;color:var(--mute);margin-top:2px"></div></div>'+
        '<button type="button" class="btn sm" id="wp-tr-close">Close</button></div>'+
      '<div id="wp-tr-body" style="margin-top:14px"></div></div>';
    document.body.appendChild(d);
    el("wp-tr-close").onclick=function(){ d.style.display="none"; };
    d.onclick=function(ev){ if(ev.target===d) d.style.display="none"; };
    document.addEventListener("keydown", function(ev){
      if(ev.key==="Escape" && d.style.display==="block") d.style.display="none";
    });
  }
  function trTile(k,v,u,color){
    return '<div style="border:1px solid var(--line);border-radius:10px;padding:8px 12px;background:var(--wash)">'+
      '<div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:600">'+k+'</div>'+
      '<div style="font-size:16px;font-weight:700;font-variant-numeric:tabular-nums'+(color?(';color:'+color):'')+'">'+v+'</div>'+
      (u?'<div style="font-size:9.5px;color:var(--mute)">'+u+'</div>':'')+'</div>';
  }
  function trWho(x){ return x ? esc(String(x).split("@")[0]) : '<span style="color:var(--mute)">not yet</span>'; }
  function openPlanTrace(name){
    ensurePlanModal();
    el("wp-tr-overlay").style.display="block";
    el("wp-tr-title").textContent=name;
    el("wp-tr-sub").textContent="Loading…";
    el("wp-tr-body").innerHTML='<div class="empty">Following the plan through…</div>';
    call({ action:"plan_trace", plan:name }).then(function(d){
      if(d.error){ el("wp-tr-body").innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
      var p=d.plan||{}, dv=d.delivery||{};
      el("wp-tr-title").textContent=p.task||name;
      el("wp-tr-sub").textContent=name+" · "+(p.farm||"")+" · "+p.from_date+" → "+p.to_date+" · "+(p.workflow_state||"");
      var h='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px">';
      h+=trTile("Target", fmt(dv.target)+" "+esc(p.uom||""), "planned quantity");
      h+=trTile("Delivered", fmt(dv.actual)+" "+esc(p.uom||""),
                fmt(dv.achieved_pct,0)+"% of target",
                dv.achieved_pct>=90?"#0a7a43":(dv.achieved_pct>=60?"#a06000":"#b91c1c"));
      h+=trTile("Planned", "KES "+fmt(dv.planned,0), "rate × target");
      h+=trTile("Spent", "KES "+fmt(dv.spent,0), fmt(dv.of_planned_pct,0)+"% of planned");
      h+=trTile("Crew", fmt(dv.crew_assigned)+" / "+fmt(dv.crew_planned), "assigned vs asked for",
                dv.crew_assigned<dv.crew_planned?"#a06000":"var(--ink)");
      h+=trTile("Paid workers", fmt(dv.workers_paid), "people who recorded work");
      h+='</div>';

      h+='<div class="sech" style="margin-top:16px">Approval chain</div>';
      h+='<table><thead><tr><th>Step</th><th>Who</th><th>When</th></tr></thead><tbody>';
      (d.chain||[]).forEach(function(c){
        h+='<tr><td>'+esc(c.step)+'</td><td>'+trWho(c.who)+'</td>'+
           '<td class="m" style="font-size:10px">'+esc(c.when||"")+'</td></tr>';
        if(c.note) h+='<tr><td colspan="3" style="font-size:10px;color:var(--mute)">“'+esc(c.note)+'”</td></tr>';
      });
      h+='</tbody></table>';

      var asg=d.assignments||[];
      h+='<div class="sech" style="margin-top:16px">Crews raised from this plan · '+fmt(asg.length)+'</div>';
      if(!asg.length){ h+='<div class="empty">No crew has been assigned to this plan yet.</div>'; }
      else{
        h+='<table><thead><tr><th>Assignment</th><th>Period</th><th class="n">Asked</th><th class="n">Assigned</th>'+
           '<th>Assigned by</th><th>Approved by</th><th>State</th></tr></thead><tbody>';
        asg.forEach(function(a){
          h+='<tr><td class="m" style="font-size:10px">'+esc(a.name)+'</td>'+
             '<td class="m" style="font-size:10px">'+esc(a.from_date)+' → '+esc(a.to_date)+'</td>'+
             '<td class="n m">'+fmt(a.planned_people)+'</td><td class="n m">'+fmt(a.assigned_count)+'</td>'+
             '<td style="font-size:10px">'+trWho(a.assigned_by)+'</td>'+
             '<td style="font-size:10px">'+trWho(a.approved_by)+'</td>'+
             '<td style="font-size:10px">'+esc(a.workflow_state||"")+'</td></tr>';
        });
        h+='</tbody></table>';
      }

      var acts=d.actuals||[];
      h+='<div class="sech" style="margin-top:16px">Work recorded · '+fmt(acts.length)+' document'+(acts.length===1?'':'s')+'</div>';
      if(!acts.length){ h+='<div class="empty">Nothing recorded against this plan yet.</div>'; }
      else{
        h+='<table><thead><tr><th>Document</th><th>Entered</th><th>Entered by</th><th>HR</th><th>GM</th>'+
           '<th class="n">Qty</th><th class="n">Pay KES</th><th>State</th></tr></thead><tbody>';
        acts.forEach(function(a){
          h+='<tr><td class="m" style="font-size:10px">'+esc(a.name)+'</td>'+
             '<td class="m" style="font-size:10px">'+esc(String(a.entry_date||"").slice(0,10))+'</td>'+
             '<td style="font-size:10px">'+trWho(a.entered_by)+'</td>'+
             '<td style="font-size:10px">'+trWho(a.hr_approved_by)+'</td>'+
             '<td style="font-size:10px">'+trWho(a.gm_approved_by)+'</td>'+
             '<td class="n m">'+fmt(a.total_actual_qty)+'</td>'+
             '<td class="n m">'+fmt(a.total_payment,2)+'</td>'+
             '<td style="font-size:10px">'+esc(a.workflow_state||"")+'</td></tr>';
        });
        h+='</tbody></table>';
      }

      var wk=d.workers||[], crew=d.crew||[];
      h+='<div class="sech" style="margin-top:16px">People · '+fmt(crew.length)+' assigned, '+fmt(wk.length)+' recorded work</div>';
      if(!crew.length && !wk.length){ h+='<div class="empty">Nobody has been put on this plan yet.</div>'; }
      else{
        var earned={};
        wk.forEach(function(w){ earned[w.employee]=w; });
        h+='<div style="max-height:260px;overflow:auto"><table><thead><tr><th>Worker</th><th>ID</th><th>On crew</th>'+
           '<th class="n">Days</th><th class="n">Qty</th><th class="n">Earned KES</th><th>Paid</th></tr></thead><tbody>';
        var seen={};
        crew.forEach(function(c){
          seen[c.employee]=1;
          var e=earned[c.employee];
          h+='<tr><td>'+esc(c.employee_name||c.employee)+'</td><td class="m" style="font-size:10px">'+esc(c.employee)+'</td>'+
             '<td style="font-size:10px">'+esc(c.status||"Active")+(c.left_date?(' · left '+esc(c.left_date)):'')+'</td>'+
             '<td class="n m">'+(e?fmt(e.days):'—')+'</td><td class="n m">'+(e?fmt(e.qty):'—')+'</td>'+
             '<td class="n m">'+(e?fmt(e.amount,2):'—')+'</td>'+
             '<td style="font-size:10px">'+(e?(e.paid?'paid':'unpaid'):'<span style="color:var(--mute)">no work</span>')+'</td></tr>';
        });
        wk.forEach(function(w){
          if(seen[w.employee]) return;
          h+='<tr><td>'+esc(w.employee_name||w.employee)+'</td><td class="m" style="font-size:10px">'+esc(w.employee)+'</td>'+
             '<td style="font-size:10px;color:var(--warn)">not on the crew</td>'+
             '<td class="n m">'+fmt(w.days)+'</td><td class="n m">'+fmt(w.qty)+'</td>'+
             '<td class="n m">'+fmt(w.amount,2)+'</td>'+
             '<td style="font-size:10px">'+(w.paid?'paid':'unpaid')+'</td></tr>';
        });
        h+='</tbody></table></div>';
      }
      el("wp-tr-body").innerHTML=h;
    }).catch(function(e){
      el("wp-tr-body").innerHTML='<div class="empty">Could not follow the plan: '+esc(e.message)+'</div>';
    });
  }

  // ── consultant weekly review board ──
  var WK={inited:false,data:null};
  function wkMonday(offsetWeeks){
    var d=new Date(); var wd=(d.getDay()+6)%7;   // Mon=0
    d.setDate(d.getDate()-wd+7*(offsetWeeks||1)); // default: NEXT Monday
    function p(n){ return (n<10?"0":"")+n; }
    return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());
  }
  function initWeekBoard(){
    if(!WK.inited){
      WK.inited=true;
      el("wk-start").value=wkMonday(1);
      el("wk-load").onclick=loadWeekBoard;
      el("wk-farm").onchange=loadWeekBoard;
      el("wk-prev").onclick=function(){ wkShift(-7); };
      el("wk-next").onclick=function(){ wkShift(7); };
    }
    loadWeekBoard();
  }
  function wkShift(days){
    var v=el("wk-start").value; if(!v) return;
    var d=new Date(v+"T00:00:00"); d.setDate(d.getDate()+days);
    function p(n){ return (n<10?"0":"")+n; }
    el("wk-start").value=d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate());
    loadWeekBoard();
  }
  function loadWeekBoard(){
    var b=el("wk-body"); b.className="loading"; b.innerHTML="Loading week…";
    call({action:"week_board", farm:el("wk-farm").value, week_start:el("wk-start").value||""}).then(function(d){
      if(d.error){ b.className=""; b.innerHTML='<div class="empty">'+esc(d.error)+'</div>'; return; }
      WK.data=d; renderWeekBoard();
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function renderWeekBoard(){
    var b=el("wk-body"); var d=WK.data; if(!b||!d) return;
    b.className="";
    var t=d.totals||{}, plans=d.plans||[], load=d.load||[];
    var h='';
    h+='<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">';
    function chip(k,v,u,c){ return '<div style="border:1px solid var(--line);border-radius:12px;padding:8px 14px;background:#fff"><div style="font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:600">'+k+'</div><div style="font-size:17px;font-weight:700;color:'+(c||"var(--ink)")+'">'+v+'</div>'+(u?'<div style="font-size:9.5px;color:var(--mute)">'+u+'</div>':'')+'</div>'; }
    h+=chip("Plans", fmt(t.plans), esc(d.farm)+" · week "+esc((d.week||{}).start||""));
    h+=chip("Budgeted value", "KES "+fmt(t.budget,2), "rate × target across the week");
    h+=chip("Peak crew / day", fmt(t.peak_crew), "of "+fmt(d.workforce)+" active workers", t.peak_crew>d.workforce?"#b91c1c":"var(--ink)");
    var st = t.plans && t.approved===t.plans ? "Approved" : (t.returned===t.plans && t.plans ? "Returned" : (t.approved||t.returned ? "Partly decided" : "Awaiting review"));
    h+=chip("Consultant state", st, fmt(t.approved)+" approved · "+fmt(t.returned)+" returned", st==="Approved"?"#0a7a43":(st==="Returned"?"#b91c1c":"#a06000"));
    h+='</div>';
    if(t.peak_crew>d.workforce){
      h+='<div class="note" style="border-color:#fca5a5;background:#fef2f2;color:#b91c1c;margin-bottom:10px"><b>Over-planned:</b> the peak day asks for '+fmt(t.peak_crew)+' workers but the farm has '+fmt(d.workforce)+' active people.</div>';
    }
    if(load.length){
      var mx=Math.max(d.workforce||0, 1);
      load.forEach(function(l){ if(l.crew>mx) mx=l.crew; });
      h+='<div class="sech" style="font-size:10px">Crew needed per day <span style="color:var(--mute);font-weight:500">vs '+fmt(d.workforce)+' active workers (dashed line)</span></div>';
      h+='<div style="display:flex;gap:8px;align-items:flex-end;height:120px;padding:6px 4px 0;position:relative;margin-bottom:14px">';
      var wfPct=(d.workforce/mx*100);
      h+='<div style="position:absolute;left:0;right:0;bottom:'+wfPct.toFixed(1)+'%;border-top:2px dashed #a06000;opacity:.55"></div>';
      load.forEach(function(l){
        var pct=Math.max(2,(l.crew/mx*100));
        var over=l.crew>d.workforce;
        h+='<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;z-index:1;justify-content:flex-end;height:100%">'+
           '<div style="font-size:10px;font-weight:700">'+fmt(l.crew)+'</div>'+
           '<div style="width:70%;max-width:52px;height:'+pct.toFixed(1)+'%;background:'+(over?"#b91c1c":"#2563eb")+';border-radius:6px 6px 0 0;opacity:.8"></div>'+
           '<div style="font-size:9px;color:var(--mute)">'+esc(l.d.slice(5))+'</div></div>';
      });
      h+='</div>';
    }
    if(!plans.length){
      h+='<div class="empty">No plans proposed for this farm-week yet.</div>';
    } else {
      h+='<table><thead><tr><th>Plan</th><th>Task</th><th>Blocks</th><th>Period</th><th class="n">Crew/day</th><th class="n">Target</th><th class="n">Rate</th><th class="n">Budget KES</th><th>Requested by</th><th>State</th><th>Consultant</th></tr></thead><tbody>';
      plans.forEach(function(r){
        var cs=r.consultant_state==="Approved"?'<span style="color:#0a7a43;font-weight:700">Approved</span>'
             :(r.consultant_state==="Returned"?'<span style="color:#b91c1c;font-weight:700" title="'+esc(r.consultant_note||"")+'">Returned</span>'
             :'<span style="color:#a06000">awaiting</span>');
        h+='<tr><td class="m" style="font-size:10px"><a href="#" data-trace="'+esc(r.name)+'" style="color:var(--blue,#2563eb);text-decoration:none">'+esc(r.name)+'</a></td><td><b>'+esc(r.task||"")+'</b></td>'+
           '<td style="font-size:10px">'+esc((r.blocks||[]).map(lbl).join(", "))+'</td>'+
           '<td class="m" style="font-size:10px">'+esc(r.period)+'</td>'+
           '<td class="n m">'+fmt(r.crew)+'</td><td class="n m">'+fmt(r.target)+' '+esc(r.uom||"")+'</td>'+
           '<td class="n m">'+fmt(r.rate,4)+'</td><td class="n m">'+fmt(r.budget,2)+'</td>'+
           '<td style="font-size:10px">'+esc((r.requested_by||"").split("@")[0])+'</td>'+
           '<td style="font-size:10px">'+esc(r.state||"")+'</td><td>'+cs+'</td></tr>';
      });
      h+='</tbody></table>';
      setTimeout(function(){
        document.querySelectorAll("[data-trace]").forEach(function(a){
          a.onclick=function(ev){ ev.preventDefault(); openPlanTrace(a.getAttribute("data-trace")); };
        });
      },0);
      if(d.is_consultant && d.gate_on){
        h+='<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px">'+
           '<button type="button" class="btn solid" id="wk-approve">Approve week · '+fmt(t.plans)+' plans · KES '+fmt(t.budget,0)+'</button>'+
           '<button type="button" class="btn" id="wk-return" style="color:#b91c1c;border-color:#fca5a5">Return with note</button>'+
           '<span class="hint" style="font-size:10px">Approving stamps every plan; Farm Managers can then approve them individually. Returning sends the week back with your note on every plan.</span></div>';
      } else if(d.gate_on){
        h+='<div class="note" style="margin-top:12px">Only the consultants named in Work Management Settings can decide this week. Farm Managers cannot approve future-week plans until the week is consultant-approved.</div>';
      }
    }
    b.innerHTML=h;
    var ap=el("wk-approve");
    if(ap){
      ap.onclick=function(){
        if(!window.confirm("Approve "+fmt(t.plans)+" plans for "+d.farm+", week of "+(d.week||{}).start+" — KES "+fmt(t.budget,0)+" budgeted?\n\nFarm Managers can then approve them individually.")) return;
        ap.disabled=true;
        call({action:"week_approve", farm:d.farm, week_start:(d.week||{}).start}).then(function(r){
          if(r.error){ toast("Error: "+r.error); ap.disabled=false; return; }
          toast(fmt(r.decided)+" plans consultant-approved");
          loadWeekBoard();
        }).catch(function(){ toast("Failed"); ap.disabled=false; });
      };
    }
    var rt=el("wk-return");
    if(rt){
      rt.onclick=function(){
        var note=window.prompt("Why is this week being returned? (required — goes on every plan)");
        if(!note || !note.trim()) return;
        rt.disabled=true;
        call({action:"week_return", farm:d.farm, week_start:(d.week||{}).start, note:note.trim()}).then(function(r){
          if(r.error){ toast("Error: "+r.error); rt.disabled=false; return; }
          toast(fmt(r.decided)+" plans returned with your note");
          loadWeekBoard();
        }).catch(function(){ toast("Failed"); rt.disabled=false; });
      };
    }
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
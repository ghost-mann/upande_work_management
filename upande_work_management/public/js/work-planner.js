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
      var stages=el("mp-stages");
      if(stages) stages.querySelectorAll("[data-stage]").forEach(function(b){
        b.onclick=function(){
          stages.querySelectorAll("[data-stage]").forEach(function(x){ x.setAttribute("aria-selected","false"); });
          b.setAttribute("aria-selected","true");
          el("mp-state").value=b.getAttribute("data-stage");
          loadMasterPlans();
        };
      });
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
      // raising a plan belongs to the farm managers, the HR head and the GM; a
      // consultant reviews and may correct in place, so can_edit is the wrong flag
      if(el("mp-new")) el("mp-new").style.display = m.can_create ? "" : "none";
      var cnt={}; (m.counts||[]).forEach(function(c){ cnt[c.st]=c.n; });
      var badge={ "mpc-consultant":"Pending Consultant", "mpc-gm":"Pending GM",
                  "mpc-appr":"Approved", "mpc-draft":"Draft", "mpc-rej":"Rejected" };
      Object.keys(badge).forEach(function(id){
        var e=el(id); if(e) e.textContent=fmt(cnt[badge[id]]||0);
      });
      return call({ action:"list", farm:(el("mp-farm").value||""),
                    state:(el("mp-state").value||"") }, "wm_masterplan");
    }).then(function(d){
      var rows=d.plans||[];
      MP.canGm=d.can_gm_approve; MP.canDecide=d.can_decide; MP.rows=rows;
      if(!rows.length){
        var fv=el("mp-farm").value;
        box.innerHTML='<div class="empty">No master plans'+(fv?(" for "+esc(fv)):"")+' yet.</div>';
        return;
      }
      var stage=el("mp-state").value;
      var mpAct = (stage==="Pending Consultant" && MP.canDecide) ||
                  (stage==="Pending GM" && MP.canGm);
      var h='';
      var note={"Pending Consultant":"Waiting on the consultants. Approve sends the plan to the general manager.",
                "Pending GM":"Waiting on the general manager. Approve puts the budget in force.",
                "Approved":"In force. These are the budgets the planner caps every request against.",
                "Draft":"Still with whoever raised them — not yet submitted for review.",
                "Rejected":"Turned down. The raiser can edit one and submit it again."}[stage];
      if(note) h+='<div class="mpd-stagenote">'+esc(note)+'</div>';
      if(mpAct){
        h+='<div class="mpd-bulk" id="mpl-bulkbar">'+
             '<label><input type="checkbox" id="mpl-all"> Select all</label>'+
             '<span class="hint" id="mpl-sel">none selected</span>'+
             '<span style="flex:1"></span>'+
             '<button type="button" class="btn sm solid" id="mpl-appr" disabled>Approve selected</button>'+
             '<button type="button" class="btn sm" id="mpl-rej" disabled style="color:#b91c1c;border-color:#fca5a5">Reject selected</button>'+
           '</div>';
      }
      h+='<div class="mpf-tablewrap"><table><thead><tr>'+
        (mpAct?'<th style="width:30px"></th>':'')+'<th>Master plan</th><th>Farm</th><th>Period</th>'+
        '<th class="n">Activities</th><th class="n">Man days</th><th class="n">Budget KES</th>'+
        '<th>Status</th><th>Raised by</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr>'+
           (mpAct?('<td><input type="checkbox" class="mpl-ck" data-n="'+esc(r.name)+'" data-st="'+esc(r.workflow_state||"")+'"></td>'):'')+
           '<td class="m" style="font-size:10px"><a href="#" data-mp="'+esc(r.name)+'">'+esc(r.name)+'</a></td>'+
           '<td>'+esc(r.farm||"")+'</td>'+
           '<td class="m" style="font-size:10px">'+esc(r.period_from)+' → '+esc(r.period_to)+'</td>'+
           '<td class="n m">'+fmt(r.total_activities)+'</td>'+
           '<td class="n m">'+fmt(r.total_man_days)+'</td>'+
           '<td class="n m">'+fmt(r.total_cost,2)+'</td>'+
           '<td>'+mpStateTag(r.workflow_state)+'</td>'+
           '<td style="font-size:10px">'+esc((r.raised_by||"").split("@")[0])+'</td></tr>';
      });
      box.innerHTML=h+'</tbody></table></div>';
      if(mpAct) wirePlanBulk(box);
      box.querySelectorAll("[data-mp]").forEach(function(a){
        a.onclick=function(ev){ ev.preventDefault(); openMasterPlan(a.getAttribute("data-mp")); };
      });
    }).catch(function(e){ box.innerHTML='<div class="empty">Could not load: '+esc(e.message)+'</div>'; });
  }
  function wirePlanBulk(box){
    var picked=function(st){
      var out=[];
      box.querySelectorAll(".mpl-ck").forEach(function(c){
        if(c.checked && (!st || c.getAttribute("data-st")===st)) out.push(c.getAttribute("data-n"));
      });
      return out;
    };
    var sync=function(){
      var k=picked().length;
      el("mpl-sel").textContent = k? (k+" selected") : "none selected";
      if(el("mpl-appr")) el("mpl-appr").disabled = !k;
      if(el("mpl-rej"))  el("mpl-rej").disabled  = !k;
    };
    var paintRow=function(c){
      var tr=c.parentNode; while(tr && tr.tagName!=="TR") tr=tr.parentNode;
      if(tr) tr.className = c.checked ? "mpl-on" : "";
    };
    box.querySelectorAll(".mpl-ck").forEach(function(c){
      c.onchange=function(){ paintRow(c); sync(); };
    });
    if(el("mpl-all")) el("mpl-all").onchange=function(){
      var on=this.checked;
      box.querySelectorAll(".mpl-ck").forEach(function(c){ c.checked=on; paintRow(c); });
      sync();
    };
    // each plan is judged on its own state server-side, so a mixed selection
    // reports per plan instead of refusing the lot
    var run=function(op,names,btn){
      if(!names.length) return;
      btn.disabled=true;
      call({action:"plans_bulk", op:op, names:JSON.stringify(names)}, "wm_masterplan").then(function(d){
        if(d.error){ toast(d.error); btn.disabled=false; return; }
        var msg=(d.done||[]).length+" plan"+((d.done||[]).length===1?"":"s")+" "+
                (op==="approve"?"approved":op==="reject"?"rejected":"sent to the GM");
        if((d.failed||[]).length){
          msg+=" \u00b7 "+d.failed.length+" skipped: "+d.failed.map(function(f){ return f.name+" ("+f.why+")"; }).join(", ");
        }
        toast(msg);
        loadMasterPlans();
      }).catch(function(){ toast("Could not apply that"); btn.disabled=false; });
    };
    // "approve" means whatever approval this stage is: the consultants pass the
    // plan to the GM, the GM puts it in force
    var stage=el("mp-state").value;
    var op = (stage==="Pending Consultant") ? "send_to_gm" : "approve";
    if(el("mpl-appr")) el("mpl-appr").onclick=function(){ run(op,picked(),this); };
    if(el("mpl-rej"))  el("mpl-rej").onclick=function(){ run("reject",picked(),this); };
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
                can_edit:d.can_edit, can_decide:d.can_decide, can_gm_approve:d.can_gm_approve,
                edit_is_review:d.edit_is_review, deciding_as_standin:d.deciding_as_standin,
                can_send_to_gm:d.can_send_to_gm, undecided_lines:d.undecided_lines,
                edited_lines:d.edited_lines, ok_lines:d.ok_lines};
      }).catch(function(){ return {p:p, acts:acts, rate_drift:d.rate_drift,
                can_edit:d.can_edit, can_decide:d.can_decide, can_gm_approve:d.can_gm_approve,
                edit_is_review:d.edit_is_review, deciding_as_standin:d.deciding_as_standin,
                can_send_to_gm:d.can_send_to_gm, undecided_lines:d.undecided_lines,
                edited_lines:d.edited_lines, ok_lines:d.ok_lines}; });
    }).then(function(res){
      if(!res) return;
      var p=res.p, acts=res.acts;
      var mpTotQty=0, mpTotCost=0, mpTotMd=0, mpTotLeft=0;
      acts.forEach(function(a){
        mpTotQty+=(a.work_qty||0); mpTotCost+=(a.cost||0); mpTotMd+=(a.man_days||0);
        mpTotLeft+=(a.remaining_cost!=null?a.remaining_cost:0);
      });
      var h='<button type="button" class="mpd-back" id="mp-back">&larr; All master plans</button>'+
        '<div class="mpd-head"><div class="mpd-top">'+
          '<div><div class="mpd-name">'+esc(p.name)+' &middot; '+esc(p.farm)+'</div>'+
            '<div class="mpd-meta">'+esc(p.period_from)+' &rarr; '+esc(p.period_to)+
            (p.raised_by?(' &middot; raised by '+esc((p.raised_by||"").split("@")[0])):'')+
            (p.gm_approved_by?(' &middot; approved by '+esc((p.gm_approved_by||"").split("@")[0])):'')+
            '</div></div>'+
          mpStateTag(p.workflow_state)+
        '</div>'+
        '<div class="mpd-figs">'+
          '<div><span class="fk">Activities</span><span class="fv">'+fmt(acts.length)+'</span></div>'+
          '<div><span class="fk">Man days</span><span class="fv">'+fmt(mpTotMd)+'</span></div>'+
          '<div><span class="fk">Budgeted</span><span class="fv">KES '+fmt(mpTotCost,2)+'</span></div>'+
          '<div><span class="fk">Still available</span><span class="fv">KES '+fmt(mpTotLeft,2)+'</span></div>'+
        '</div></div>';
      // hiding these is only a convenience -- every rule they call is re-checked
      // and re-reported by the server, never trusted from these flags alone
      if(res.can_edit || res.can_decide || res.can_gm_approve){
        h+='<div class="btns" style="margin:8px 0 4px">';
        if(res.can_edit){
          // during review the same button corrects the plan in place; submitting is
          // the raiser's action alone, and the server refuses it in any other state
          h+='<button type="button" class="btn" id="mp-edit">'+
             (res.edit_is_review?"Correct this plan":"Edit")+'</button>';
          if(!res.edit_is_review){
            h+='<button type="button" class="btn solid" id="mp-submitrev">Submit for review</button>';
          }
        }
        if(res.can_decide){
          // the plan also advances on its own once the last line is decided; this is
          // the explicit step, and it says what is still outstanding rather than
          // simply not being there
          if(res.can_send_to_gm){
            h+='<button type="button" class="btn solid" id="mp-sendgm">Approve &amp; send to GM</button>';
          } else {
            var why = res.edited_lines ? (res.edited_lines+" line"+(res.edited_lines>1?"s":"")+" marked Edit work — goes back to the raiser")
                    : res.undecided_lines ? (res.undecided_lines+" line"+(res.undecided_lines>1?"s":"")+" still undecided")
                    : !res.ok_lines ? "every line rejected — nothing to approve"
                    : "";
            h+='<button type="button" class="btn" id="mp-sendgm" disabled title="'+esc(why)+'">Send to GM</button>'+
               (why?'<span class="hint">'+esc(why)+'</span>':'');
          }
          h+='<button type="button" class="btn" id="mp-rejectdoc" style="color:#b91c1c;border-color:#fca5a5">Reject entire plan</button>';
        }
        if(res.can_gm_approve){
          h+='<button type="button" class="btn solid" id="mp-gmapprove">GM Approve</button>'+
             '<button type="button" class="btn" id="mp-rejectdoc" style="color:#b91c1c;border-color:#fca5a5">Reject</button>';
        }
        h+='</div>';
      }
      if(res.deciding_as_standin){
        h+='<div class="mpd-standin">You are deciding these lines as the <b>general manager standing in '+
           'for a consultant</b>. Each decision is recorded against your name on the line and on this plan.</div>';
      }
      if((res.rate_drift||[]).length){
        var anyUnit=res.rate_drift.some(function(x){ return x.kind==="unit"; });
        h+='<div class="mpd-drift">'+
           '<b>This plan was budgeted at rates that have since changed.</b> '+
           (anyUnit ? 'Some of it changed unit, which the budget cannot convert on its own:'
                    : 'The money is fixed, so fewer units now fit the same budget:')+
           '<ul style="margin:6px 0 0 16px">';
        res.rate_drift.forEach(function(x){
          if(x.kind==="unit"){
            h+='<li><b>'+esc(x.task)+' changed unit.</b> Budgeted per '+esc(x.budget_uom||"—")+
               ' at '+fmt(x.budget_rate,6)+'; the task is now priced per '+esc(x.live_uom||"—")+
               ' at '+fmt(x.live_rate,6)+'. The quantity has to be re-entered in the new unit — '+
               'one '+esc(x.budget_uom||"unit")+' is not one '+esc(x.live_uom||"unit")+'.</li>';
          } else {
            h+='<li>'+esc(x.task)+' — budgeted at '+fmt(x.budget_rate,6)+', now '+fmt(x.live_rate,6)+
               ' (same work would cost '+fmt(x.cost_at_live_rate,2)+')</li>';
          }
        });
        h+='</ul></div>';
      }
      h+='<div class="note" style="margin-bottom:8px">Click an activity to see which plans are drawing on its budget — including stale drafts still holding it.</div>';
      var mpColspan = 10;
      h+='<div class="mpf-tablewrap"><table><thead><tr><th>Activity</th><th class="n">Man days</th><th class="n">Days</th>'+
         '<th class="n">Work</th><th>Unit</th><th class="n">Rate</th><th class="n">Cost</th>'+
         '<th class="n">Planned</th><th class="n">Left</th><th>Remarks</th></tr></thead><tbody>';
      acts.forEach(function(a,i){
        var exhausted = (a.remaining_qty!=null && a.remaining_qty<=0.005) ||
                        (a.remaining_cost!=null && a.remaining_cost<=0.005);
        h+='<tr class="mp-actrow" data-ai="'+i+'" style="cursor:pointer"><td>'+esc(a.task)+'</td><td class="n m">'+fmt(a.man_days)+'</td>'+
           '<td class="n m">'+fmt(a.days)+'</td><td class="n m">'+fmt(a.work_qty)+'</td>'+
           '<td>'+esc(a.uom||"")+'</td><td class="n m">'+fmt(a.rate,6)+'</td>'+
           '<td class="n m">'+fmt(a.cost,2)+'</td><td class="n m">'+fmt(a.planned_qty)+'</td>'+
           '<td class="n m">'+fmt(a.remaining_qty)+
           (exhausted?' <span class="mpd-used">used up</span>':'')+'</td>'+
           '<td style="font-size:10px">'+esc(a.remarks||"")+
           (a.original_qty?('<span class="mpd-was">was '+fmt(a.original_qty)+'</span>'):'')+'</td>'+
'</tr>';
        h+='<tr class="mp-actdetail" data-ad="'+i+'" style="display:none"><td colspan="'+mpColspan+'" style="background:var(--wash);padding:0">'+
           '<div class="mp-consumers" data-panel="'+i+'"></div></td></tr>';
      });
      h+='</tbody></table></div>';
      box.innerHTML=h;
      var mpBack=el("mp-back");
      if(mpBack) mpBack.onclick=loadMasterPlans;
      var mpSendGm=el("mp-sendgm");
      if(mpSendGm && !mpSendGm.disabled) mpSendGm.onclick=function(){
        mpSendGm.disabled=true;
        call({action:"send_to_gm", name:p.name}, "wm_masterplan").then(function(d){
          if(d.error){ toast(d.error); mpSendGm.disabled=false; return; }
          toast(p.name+" sent to the GM");
          openMasterPlan(p.name);
        }).catch(function(){ toast("Could not send to the GM"); mpSendGm.disabled=false; });
      };
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
  var MPF = { editing:null, rows:[], catalog:[], catalogState:"nofarm", filter:"", clash:null, onSaved:null };

  function mpStateTag(st){
    var k={"Draft":"draft","Pending Consultant":"consultant","Pending GM":"gm",
           "Approved":"approved","Rejected":"rejected"}[st]||"draft";
    return '<span class="mps '+k+'">'+esc(st||"—")+'</span>';
  }
  function mpFilteredCatalog(selected){
    var q=(MPF.filter||"").trim().toLowerCase();
    if(!q) return MPF.catalog;
    return MPF.catalog.filter(function(t){
      return t.name===selected ||
             (t.subject||"").toLowerCase().indexOf(q)>-1 ||
             (t.uom||"").toLowerCase().indexOf(q)>-1;
    });
  }
  function mpTaskOptions(selected){
    var lbl={nofarm:"— choose a farm first —", loading:"— loading tasks… —",
             empty:"— no tasks on this farm's project —", error:"— could not load tasks —"}[MPF.catalogState]
             || "— select task —";
    var h='<option value="">'+lbl+'</option>';
    mpFilteredCatalog(selected).forEach(function(t){
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
      '<td><input type="number" class="mpf-r-md" data-i="'+i+'" min="0" step="any" placeholder="0" value="'+(r.man_days||"")+'">'+
        (c&&c.daily_target?('<span class="mpf-std">'+fmt(c.daily_target)+' '+esc(c.uom||"")+'/day</span>'):
                            (c?'<span class="mpf-std">no daily target set</span>':''))+'</td>'+
      '<td><input type="number" class="mpf-r-days" data-i="'+i+'" min="0" step="1" placeholder="0" value="'+(r.days||"")+'"></td>'+
      '<td><input type="number" class="mpf-r-qty" data-i="'+i+'" min="0" step="any" placeholder="0" value="'+(r.work_qty||"")+'"></td>'+
      '<td class="mpf-unit mpf-r-unit" data-i="'+i+'">'+esc(unit||"—")+'</td>'+
      '<td class="mpf-derived'+(c?" set":"")+' mpf-r-rate" data-i="'+i+'">'+(c?fmt(rate,6):"—")+'</td>'+
      '<td class="mpf-cost mpf-r-cost" data-i="'+i+'">'+(c&&cost?("KES "+fmt(cost,2)):"—")+'</td>'+
      '<td><button type="button" class="mpf-rm mpf-r-remove" data-i="'+i+'" title="Remove this activity" aria-label="Remove">&times;</button></td>'+
    '</tr>';
  }
  function mpRenderRows(){
    var tb=el("mpf-rows"); if(!tb) return;
    var cnt=el("mpf-count");
    if(cnt){
      var tot=MPF.catalog.length, shown=mpFilteredCatalog(null).length;
      cnt.textContent = !tot ? "" : ((MPF.filter||"").trim()
        ? (fmt(shown)+" of "+fmt(tot)+" activities")
        : (fmt(tot)+" activities"));
    }
    tb.innerHTML=MPF.rows.length
      ? MPF.rows.map(mpRowMarkup).join("")
      : '<tr><td colspan="8"><div class="mpf-empty"><b>No activities yet</b>'+
        'Add the activities this farm may plan in this period, and how much work each may cover.</div></td></tr>';
    mpWireRows();
    mpUpdateTotals();
  }
  function mpRenderRowCalc(i){
    var r=MPF.rows[i]; var c=mpCatalogEntry(r.task);
    var rate=c?c.rate:0, unit=c?(c.uom||""):"";
    var cost=(r.work_qty||0)*rate;
    // man-days are what the quantity is worth in labour: quantity / daily target.
    // Typed over freely -- some work does not match the standard -- but correct
    // by default, and the same arithmetic the planner uses.
    if(c && c.daily_target>0 && !MPF.rows[i].md_touched){
      MPF.rows[i].man_days = Math.round((MPF.rows[i].work_qty||0)/c.daily_target*100)/100;
      var mdi=document.querySelector('.mpf-r-md[data-i="'+i+'"]');
      if(mdi) mdi.value = MPF.rows[i].man_days || "";
    }
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
      s.oninput=function(){ var i=parseInt(this.getAttribute("data-i"),10);
        MPF.rows[i].man_days=parseFloat(this.value)||0; MPF.rows[i].md_touched=1; };
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
    t.innerHTML='<div><span class="tk">Activities</span><span class="tv">'+fmt(MPF.rows.length)+'</span></div>'+
      '<div><span class="tk">Man days</span><span class="tv">'+fmt(md)+'</span></div>'+
      '<div><span class="tk">Budgeted</span><span class="tv">KES '+fmt(cost,2)+'</span></div>';
  }
  function mpRefreshCatalog(){
    var fs=el("mpf-farm"), fr=el("mpf-from");
    if(!fs || !fr) return;
    var farm=fs.value, from=fr.value;
    // the farm alone is enough to list the tasks; Period From only decides WHICH
    // rate is shown, so waiting for both left the picker empty with no reason given
    if(!farm){ MPF.catalog=[]; MPF.catalogState="nofarm"; mpRenderRows(); return; }
    MPF.catalogState="loading"; mpRenderRows();
    call({action:"pickable_tasks", farm:farm, period_from:from||""}, "wm_masterplan").then(function(d){
      if(d.error){ toast(d.error); MPF.catalog=[]; MPF.catalogState="error"; }
      else { MPF.catalog=d.tasks||[]; MPF.catalogState=MPF.catalog.length?"ok":"empty"; }
      if(MPF.seedTouch){ mpSeedTouched(); MPF.seedTouch=false; }
      mpRenderRows();
    }).catch(function(){
      MPF.catalog=[]; MPF.catalogState="error"; MPF.seedTouch=false; mpRenderRows();
      toast("Could not load tasks for this farm");
    });
  }
  function mpSeedTouched(){
    // A reopened plan's rows carry no record of whether Man Days was typed over --
    // that flag lived only in the browser and was never sent to the server. Rebuild
    // it once the catalog (and its daily targets) has actually loaded: a stored
    // figure that still matches the derivation was never overridden, so leave it
    // derivable -- if quantity changes later, man-days should follow it. A stored
    // figure that differs was a deliberate choice and must survive later edits.
    MPF.rows.forEach(function(r){
      if(r.md_touched) return;
      var c=mpCatalogEntry(r.task);
      if(!c || !(c.daily_target>0)) return;
      var derived=Math.round((r.work_qty||0)/c.daily_target*100)/100;
      if(Math.abs((r.man_days||0)-derived) > 0.005) r.md_touched=1;
    });
  }
  function mpFormShell(){
    return '<div class="mpf-card">'+
      '<div class="mpf-head">'+
        '<div>'+
          '<div class="mpf-eyebrow">Work Management</div>'+
          '<div class="mpf-title" id="mpf-title">New master plan</div>'+
          '<div class="mpf-sub">One farm, one period. Every activity you list here becomes plannable '+
            'once the consultants and the GM approve it &mdash; and nothing outside this list can be planned at all.</div>'+
        '</div>'+
        '<button type="button" class="mpf-x" id="mpf-x" title="Close" aria-label="Close">&times;</button>'+
      '</div>'+
      '<div class="mpf-body">'+
        '<div class="mpf-grid">'+
          '<div><label class="fl" for="mpf-farm">Farm</label><select id="mpf-farm"><option value="">— select farm —</option></select></div>'+
          '<div><label class="fl" for="mpf-from">Period from</label><input type="date" id="mpf-from"></div>'+
          '<div><label class="fl" for="mpf-to">Period to</label><input type="date" id="mpf-to"></div>'+
        '</div>'+
        '<div class="mpf-clash" id="mpf-clash" style="display:none"></div>'+
        '<div class="mpf-sechrow">'+
          '<div class="sech">Activities &amp; budget</div>'+
          '<div class="mpf-find">'+
            '<input type="search" id="mpf-find" placeholder="Filter activities&hellip;" autocomplete="off">'+
            '<span class="mpf-count" id="mpf-count"></span>'+
          '</div>'+
        '</div>'+
        '<div class="mpf-tablewrap">'+
          '<table><thead><tr>'+
            '<th style="width:34%">Activity</th>'+
            '<th class="n" style="width:9%">Man days</th>'+
            '<th class="n" style="width:8%">Days</th>'+
            '<th class="n" style="width:12%">Work qty</th>'+
            '<th style="width:8%">Unit</th>'+
            '<th class="n" style="width:12%">Rate</th>'+
            '<th class="n" style="width:15%">Cost</th>'+
            '<th style="width:34px"></th>'+
          '</tr></thead><tbody id="mpf-rows"></tbody></table>'+
        '</div>'+
        '<button type="button" class="mpf-add" id="mpf-addrow">+ Add activity</button>'+
        '<div class="mpf-note">Unit, rate and cost come from the server &mdash; the rate is the one in force on '+
          '<b>Period from</b>, and it is frozen onto the line when you save. <b>Work qty</b> and <b>cost</b> are what '+
          'the budget is enforced against. Man days and days are recorded for reporting and never cap anything.</div>'+
      '</div>'+
      '<div class="mpf-foot">'+
        '<div class="mpf-tot" id="mpf-totals"></div>'+
        '<div class="btns">'+
          '<button type="button" class="btn" id="mpf-cancel">Cancel</button>'+
          '<button type="button" class="btn" id="mpf-save">Save draft</button>'+
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
    MPF.rows=[]; MPF.catalog=[]; MPF.filter=""; MPF.clash=null; MPF.seedTouch=false;
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
    fs.onchange=function(){ mpRefreshCatalog(); chkPeriod(); };
    var chkPeriod=function(){
      var fm=el("mpf-farm").value, a=el("mpf-from").value, b=el("mpf-to").value;
      var bar=el("mpf-clash"); if(!bar) return;
      if(!fm||!a||!b){ bar.style.display="none"; MPF.clash=null; mpSaveState(); return; }
      call({action:"period_free", farm:fm, period_from:a, period_to:b,
            name:MPF.editing||""}, "wm_masterplan").then(function(d){
        if(d.free){ bar.style.display="none"; MPF.clash=null; }
        else {
          MPF.clash=d.clash;
          bar.style.display="";
          bar.innerHTML='<b>'+esc(fm)+' already has a master plan for these dates.</b> '+
            esc(d.clash)+' covers '+esc(d.clash_from)+' &rarr; '+esc(d.clash_to)+
            ' ('+esc(d.clash_state)+'). A farm has one budget per period &mdash; put this work on '+
            esc(d.clash)+', or choose dates outside it.';
        }
        mpSaveState();
      });
    };
    el("mpf-from").onchange=function(){ mpRefreshCatalog(); chkPeriod(); };
    el("mpf-to").onchange=chkPeriod;
    var findBox=el("mpf-find");
    if(findBox){
      // narrows every task picker at once; a row's own selection always stays in
      // its list, so typing can never quietly drop an activity already chosen
      findBox.oninput=function(){ MPF.filter=this.value; mpRenderRows(); };
      findBox.onkeydown=function(ev){ if(ev.key==="Escape"){ this.value=""; MPF.filter=""; mpRenderRows(); } };
    }
    var saveBtn=el("mpf-save"), submitBtn=el("mpf-submit");
    var mpSaveState=function(){
      var bad=!!MPF.clash;
      saveBtn.disabled=bad; submitBtn.disabled=bad;
      saveBtn.title = bad ? "This period already has a master plan" : "";
    };
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
        MPF.seedTouch=true;
        mpRefreshCatalog();
      }).catch(function(){ toast("Could not load plan for editing"); shut(); });
    } else {
      el("mpf-title").textContent="New master plan";
      MPF.rows=[{task:"",man_days:0,days:0,work_qty:0}];
      mpRenderRows();
    }
  }

  // what may be planned depends on the DATES, not just the farm: the budget that
  // governs 10-15 Aug is not necessarily the one governing the week after. Fetch
  // against the dates on screen so the picker and the cap can never disagree.
  function loadPlannableTasks(){
    var sel=el("f-task"); if(!sel || !ST.farm) return;
    var f=el("f-from").value, t=el("f-to").value;
    call({action:"tasks", farm:ST.farm, from_date:f||"", to_date:t||""}).then(function(d){
      ST.tasks=d.tasks||[];
      ST.lastTasks=d;
      ST.blocked = d.blocked_reason || null;
      var keep=sel.value;
      sel.innerHTML='<option value="">'+
        (d.blocked_reason ? "— nothing can be planned for these dates —" : "— select task —")+
        '</option>';
      ST.tasks.forEach(function(x){
        var o=document.createElement("option");
        o.value=x.name;
        o.textContent=x.subject+" · "+fmt(x.remaining_qty)+" "+(x.uom||"")+" / KES "+fmt(x.remaining_cost,0)+" left";
        if(x.exhausted){ o.disabled=true; o.textContent=x.subject+" · budget used up"; }
        sel.appendChild(o);
      });
      if(keep) sel.value=keep;
      renderPeriodBar(d);
      recalc();
    });
  }

  // every budget the farm has, so a period is chosen from what exists rather than
  // typed and then refused. The active one is the budget the dates currently sit in.
  function loadBudgets(){
    if(!ST.farm){ ST.budgets=[]; renderPeriodBar(ST.lastTasks||{}); return; }
    call({action:"budgets", farm:ST.farm}).then(function(d){
      ST.budgets=d.budgets||[];
      renderPeriodBar(ST.lastTasks||{});
    });
  }

  function renderPeriodBar(d){
    var bar=el("f-mpperiod"), txt=el("f-mptext"), btn=el("f-usemp");
    if(!bar) return;
    var buds=ST.budgets||[];
    var active=d.master_plan||null;
    var f=el("f-from").value, t=el("f-to").value;
    if(!buds.length){
      // no budget at all for this farm: nothing here can be planned, and saying so
      // plainly beats an empty task list the person is left to interpret
      bar.style.display=""; bar.className="mp-period out"; btn.style.display="none";
      txt.innerHTML='<b>'+esc(ST.farm||"This farm")+' cannot be planned yet.</b> '+
        'Work is capped by an approved master plan, and this farm has none'+
        (d.pending_plan ? (' &mdash; '+esc(d.pending_plan)+' is still at '+esc(d.pending_plan_state)+
                           ', so planning opens when it is approved.')
                        : '. Someone with the farm manager, HR head or GM role raises one '+
                          'from the Master plan tab, and the GM approves it.');
      return;
    }
    bar.style.display=""; btn.style.display="none";
    var inside = buds.filter(function(b){ return (!f||f>=b.period_from) && (!t||t<=b.period_to); }).length>0;
    bar.className = inside ? "mp-period" : "mp-period out";
    var h = (inside
      ? "Budget period &mdash; the request must fit inside one:"
      : "<b>These dates cannot be planned.</b> A request has to sit wholly inside one "+
        "approved budget, and "+esc(ST.farm||"this farm")+"&rsquo;s budgets are below. "+
        "Pick one to snap the dates to it:") + "<div class=\"mp-buds\">";
    buds.forEach(function(b){
      var on = (active===b.name) || (b.period_from===f && b.period_to===t);
      h += '<button type="button" class="bud'+(on?" on":"")+'" data-bf="'+esc(b.period_from)+
           '" data-bt="'+esc(b.period_to)+'">'+esc(b.name)+
           '<span>'+esc(b.period_from)+' &rarr; '+esc(b.period_to)+
           ' · '+fmt(b.activities)+' activit'+(b.activities===1?"y":"ies")+'</span></button>';
    });
    txt.innerHTML = h+"</div>";
    bar.querySelectorAll("[data-bf]").forEach(function(x){
      x.onclick=function(){
        el("f-from").value=x.getAttribute("data-bf");
        el("f-to").value=x.getAttribute("data-bt");
        syncSlider(); recalc(); loadPlannableTasks();
      };
    });
  }

  function buildTabs(){
    var tabs=[["new","New Request"],["mine","My Requests"],["rej","Rejected"]];
    if(ST.roles && ST.roles.is_approver) tabs.push(["appr","Approvals"]);
    tabs.push(["mp","Master plan"]);
    if(ST.canRates) tabs.push(["rates","Rates"]);
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
    ["new","mine","rej","appr","week","mp","rates"].forEach(function(n){ var p=el("p-"+n); if(p) p.classList.toggle("on", n===name); });
    document.querySelectorAll("#wp-tabs button").forEach(function(b){ b.setAttribute("aria-selected", b.getAttribute("data-tab")===name); });
    if(name==="mine") loadMine();
    if(name==="rej") loadRejected();
    if(name==="appr") loadAppr();
    if(name==="mp") loadMasterPlans();
    if(name==="rates") loadRates();
  }

  function initNew(meta){
    var fs=el("f-farm");
    fs.innerHTML='<option value="">— select farm —</option>';
    meta.farms.forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fs.appendChild(o); });
    fs.onchange=onFarm;
    el("f-block").onchange=function(){ if(this.value){ ST.picked[this.value]=true; this.value=''; } syncBlockGrid(); recalc(); };
    el("f-task").onchange=onTask;
    el("f-qty").oninput=recalc;
    el("f-from").onchange=function(){ syncSlider(); recalc(); loadPlannableTasks(); };
    el("f-to").onchange=function(){ syncSlider(); recalc(); loadPlannableTasks(); };
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
    loadPlannableTasks();
    loadBudgets();
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
    // man-days are what the quantity itself is worth in labour: quantity / daily
    // target. The crew is those man-days spread over the days, rounded up because
    // people come whole -- so the crew rounding never inflates the man-days.
    var mandays = (tgt>0) ? (qty/tgt) : 0;
    var ppd = (mandays>0 && wd>0) ? Math.ceil(mandays/wd) : 0;
    var cost=qty*rate;
    el("o-ppl").textContent = ppd>0?fmt(ppd):"—";
    el("o-ppl-u").textContent = (info?fmt(tgt)+" "+(info.uom||"")+"/day":"crew size");
    el("o-pd").textContent = mandays>0?fmt(mandays,2):"—";
    var mdu=el("o-pd-u");
    if(mdu) mdu.textContent = (mandays>0 && wd>0)
      ? (fmt(qty)+" ÷ "+fmt(tgt)+" = "+fmt(mandays,2)+" over "+fmt(wd)+" day"+(wd>1?"s":""))
      : "quantity ÷ daily target";
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
    // saying "select a task" when there is nothing selectable sends people looking
    // for a control that is empty for a reason -- give them the reason
    if(!ST.task){
      missing.push(ST.blocked ? "no activities are budgeted for these dates — see the note above the period"
                              : "select a task");
    }
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

  function loadRates(){
    var sel=el("rt-task");
    if(sel && !sel.options.length){
      sel.innerHTML='<option value="">— select task —</option>';
      (ST.rateTasks||[]).forEach(function(t){
        var o=document.createElement("option"); o.value=t.name; o.textContent=t.subject; sel.appendChild(o);
      });
      sel.onchange=function(){ RT.task=this.value; renderRates(); };
      var f=el("rt-find");
      if(f) f.oninput=function(){
        var q=(this.value||"").toLowerCase();
        sel.innerHTML='<option value="">— select task —</option>';
        (ST.rateTasks||[]).forEach(function(t){
          if(q && (t.subject||"").toLowerCase().indexOf(q)<0 && t.name!==RT.task) return;
          var o=document.createElement("option"); o.value=t.name; o.textContent=t.subject;
          if(t.name===RT.task) o.selected=true;
          sel.appendChild(o);
        });
      };
    }
    renderRates();
  }

  var RT = { task:null, mode:null, preview:null };

  function renderRates(){
    var box=el("rt-body");
    if(!RT.task){ box.innerHTML='<div class="empty">Pick a task to see its rate history.</div>'; return; }
    box.innerHTML='<div class="loading">Loading…</div>';
    call({action:"periods", task:RT.task}, "wm_rates").then(function(d){
      var ps=d.periods||[], tm=d.task_master||{};
      var h='<div class="rt-cur"><b>'+esc(RT.task)+'</b> — now '+fmt(tm.custom_rate,6)+
            ' per '+esc(tm.custom_uom||"—")+', target '+fmt(tm.custom_daily_target)+'/day</div>';
      h+='<div class="rt-acts">'+
         '<button type="button" class="btn sm solid" id="rt-new">New rate from a date</button>'+
         '<button type="button" class="btn sm" id="rt-fix">Correct a period</button>'+
         '<button type="button" class="btn sm" id="rt-unit">Change the unit</button></div>';
      h+='<div id="rt-panel"></div>';
      h+='<div class="mpf-tablewrap"><table><thead><tr><th>Period</th><th>From</th><th>To</th>'+
         '<th class="n">Rate</th><th>Unit</th><th class="n">Target</th><th>Source</th></tr></thead><tbody>';
      ps.forEach(function(p){
        h+='<tr><td class="m" style="font-size:10px">'+esc(p.name)+'</td>'+
           '<td class="m">'+esc(p.valid_from)+'</td><td class="m">'+esc(p.valid_to||"open")+'</td>'+
           '<td class="n m">'+fmt(p.rate,6)+'</td><td>'+esc(p.uom||"")+'</td>'+
           '<td class="n m">'+fmt(p.daily_target)+'</td>'+
           '<td style="font-size:10px;color:var(--mute)">'+esc(p.source||"")+'</td></tr>';
      });
      box.innerHTML=h+'</tbody></table></div>';
      RT.periods=ps;
      el("rt-new").onclick=function(){ ratePanel("new"); };
      el("rt-fix").onclick=function(){ ratePanel("fix"); };
      el("rt-unit").onclick=function(){ ratePanel("unit"); };
    });
  }

  function ratePanel(mode){
    var p=el("rt-panel"); RT.mode=mode; RT.preview=null;
    if(mode==="new"){
      p.innerHTML='<div class="rt-form"><div class="row">'+
        '<div><label class="fl">New rate</label><input type="number" step="any" id="rt-r"></div>'+
        '<div><label class="fl">Effective from</label><input type="date" id="rt-d"></div>'+
        '<button type="button" class="btn solid" id="rt-go">Create the period</button></div>'+
        '<div class="note">The rate in force is closed the day before. Nothing already priced changes.</div></div>';
      el("rt-go").onclick=function(){
        this.disabled=true;
        var btn=this;
        call({action:"new_rate", task:RT.task, rate:el("rt-r").value,
              effective_from:el("rt-d").value}, "wm_rates").then(function(d){
          if(d.error){ toast(d.error); btn.disabled=false; return; }
          toast("Created "+d.created); renderRates();
        });
      };
    } else if(mode==="fix"){
      var opts=(RT.periods||[]).map(function(x){
        return '<option value="'+esc(x.name)+'">'+esc(x.valid_from)+' → '+esc(x.valid_to||"open")+
               ' · '+fmt(x.rate,6)+'</option>'; }).join("");
      p.innerHTML='<div class="rt-form"><div class="row">'+
        '<div><label class="fl">Period to correct</label><select id="rt-p">'+opts+'</select></div>'+
        '<div><label class="fl">Corrected rate</label><input type="number" step="any" id="rt-r"></div>'+
        '<button type="button" class="btn" id="rt-go">Show what this changes</button></div>'+
        '<div class="note">The rate was wrong. Everything priced from this period is re-priced — after you approve the list.</div></div>';
      el("rt-go").onclick=function(){
        call({action:"correct_preview", period:el("rt-p").value, rate:el("rt-r").value},
             "wm_rates").then(function(d){
          if(d.error){ toast(d.error); return; }
          RT.preview=d; renderImpact(d);
        });
      };
    } else {
      p.innerHTML='<div class="rt-form"><div class="row">'+
        '<div><label class="fl">New unit</label><input type="text" id="rt-u" placeholder="Hour"></div>'+
        '<div><label class="fl">Daily target</label><input type="number" step="any" id="rt-t"></div>'+
        '<div><label class="fl">Quantity factor (optional)</label><input type="number" step="any" id="rt-f" placeholder="e.g. 8"></div>'+
        '<button type="button" class="btn" id="rt-go">Show what this affects</button></div>'+
        '<div class="note">A quantity in the old unit does not mean the same in the new one. Draft plans are converted only if you give a factor; everything else has to be re-entered.</div></div>';
      el("rt-go").onclick=function(){
        call({action:"unit_change_preview", task:RT.task, uom:el("rt-u").value,
              daily_target:el("rt-t").value}, "wm_rates").then(function(d){
          if(d.error){ toast(d.error); return; }
          var a=d.affected||{};
          el("rt-panel").insertAdjacentHTML("beforeend",
            '<div class="rt-impact"><h4>What is priced in '+esc(d.old_uom||"the old unit")+'</h4>'+
            '<div>Master plan lines: <b>'+fmt(a.master_plan_lines)+'</b> · Planner requests: <b>'+
            fmt(a.planners)+'</b> · Actuals documents: <b>'+fmt(a.actuals)+'</b></div>'+
            '<div class="note" style="margin-top:8px">New rate would be <b>'+fmt(d.derived_rate,6)+
            '</b> per '+esc(d.new_uom)+' (daily basis '+fmt(d.daily_basis,2)+' ÷ '+fmt(d.new_target)+').</div>'+
            '<button type="button" class="btn solid" id="rt-uapply" style="margin-top:10px">Apply the unit change</button></div>');
          el("rt-uapply").onclick=function(){
            this.disabled=true;
            var btn=this;
            call({action:"unit_change_apply", task:RT.task, uom:el("rt-u").value,
                  daily_target:el("rt-t").value, factor:el("rt-f").value||0}, "wm_rates")
              .then(function(r){
                if(r.error){ toast(r.error); btn.disabled=false; return; }
                toast("New period "+r.created+" · "+fmt(r.converted)+" draft lines converted");
                renderRates();
              });
          };
        });
      };
    }
  }

  function renderImpact(d){
    var h='<div class="rt-impact"><h4>Correcting '+esc(d.task)+' · '+fmt(d.old_rate,6)+' → '+
          fmt(d.new_rate,6)+' for '+esc(d.valid_from)+' → '+esc(d.valid_to||"open")+'</h4>';
    if((d.master_plans||[]).length){
      h+='<div style="margin:8px 0 4px"><label><input type="checkbox" id="rt-allmp" checked> '+
         'Master plan lines ('+fmt(d.master_plans.length)+')</label></div>'+
         '<div class="mpf-tablewrap"><table><thead><tr><th></th><th>Plan</th><th>Farm</th><th>Status</th>'+
         '<th class="n">Qty</th><th class="n">Now</th><th class="n">Becomes</th></tr></thead><tbody>';
      d.master_plans.forEach(function(m){
        h+='<tr><td><input type="checkbox" class="rt-mp" data-r="'+esc(m.row)+'" checked></td>'+
           '<td class="m" style="font-size:10px">'+esc(m.plan)+'</td><td>'+esc(m.farm||"")+'</td>'+
           '<td style="font-size:10px">'+esc(m.state)+'</td><td class="n m">'+fmt(m.qty)+'</td>'+
           '<td class="n m">'+fmt(m.old_cost,2)+'</td><td class="n m">'+fmt(m.new_cost,2)+'</td></tr>';
      });
      h+='</tbody></table></div>';
    }
    h+='<div style="margin-top:10px"><label><input type="checkbox" id="rt-pl" checked> Planner requests — '+
       fmt(d.planners.rows)+' rows, '+fmt(d.planners.old_total,2)+' → '+fmt(d.planners.new_total,2)+'</label></div>'+
       '<div><label><input type="checkbox" id="rt-ac" checked> Actuals — '+
       fmt(d.actuals.rows)+' rows, '+fmt(d.actuals.old_total,2)+' → '+fmt(d.actuals.new_total,2)+'</label></div>';
    if(d.locked && d.locked.rows){
      h+='<div class="rt-locked"><b>'+fmt(d.locked.rows)+' rows totalling '+fmt(d.locked.total,2)+
         ' are already paid and will not be changed.</b> Money that has gone to accounts does not move '+
         'because a rate was corrected afterwards.</div>';
    }
    h+='<button type="button" class="btn solid" id="rt-apply" style="margin-top:12px">Apply this correction</button>'+
       '<span class="hint" style="margin-left:10px">Recorded as a run you can reverse in one step.</span></div>';
    el("rt-panel").insertAdjacentHTML("beforeend", h);
    var all=el("rt-allmp");
    if(all) all.onchange=function(){
      var on=this.checked;
      document.querySelectorAll(".rt-mp").forEach(function(c){ c.checked=on; });
    };
    el("rt-apply").onclick=function(){
      var rows=[];
      document.querySelectorAll(".rt-mp").forEach(function(c){ if(c.checked) rows.push(c.getAttribute("data-r")); });
      this.disabled=true;
      var btn=this;
      call({action:"correct_apply", period:d.period, rate:d.new_rate,
            plan_rows:JSON.stringify(rows), do_planners:el("rt-pl").checked?1:0,
            do_actuals:el("rt-ac").checked?1:0}, "wm_rates").then(function(r){
        if(r.error){ toast(r.error); btn.disabled=false; return; }
        var msg=r.changed+" rows re-priced · run "+r.run+" · delta "+fmt(r.delta,2);
        if(r.skipped_plan_rows){ msg += " · "+fmt(r.skipped_plan_rows)+" rows skipped (no longer eligible)"; }
        toast(msg);
        renderRates();
      });
    };
  }

  function boot(){
    Promise.all([ call({action:"meta"}), call({action:"roles"}) ]).then(function(res){
      var meta=res[0], roles=res[1];
      ST.roles=roles;
      el("wp-who").textContent=(roles.user||"")+(roles.is_approver?" · Approver":"");
      initNew(meta);
      call({action:"rate_meta"}, "wm_rates").then(function(d){
        ST.canRates = !!(d && d.can_edit);
        ST.rateTasks = (d && d.tasks) || [];
        buildTabs();
      }).catch(function(){ ST.canRates=false; buildTabs(); });
    }).catch(function(e){
      el("wp-who").textContent="Load error: "+(e&&e.message?e.message:e);
    });
  }
  if(typeof frappe==="undefined"){
    document.getElementById("wp-who").textContent="Open this inside Frappe (logged in).";
  } else { boot(); }
})();
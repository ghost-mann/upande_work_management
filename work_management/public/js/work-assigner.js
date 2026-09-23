(function(){
  var ST = { plan:null, planDetail:null, employees:[], picked:{}, roles:null, planList:[] };

  // Frappe answers a validation failure with HTTP 417 and puts the reason in the
  // body -- as _server_messages, or exception, or exc_type. Throwing "HTTP 417" and
  // letting the caller print "Failed to save" discarded exactly the sentence the
  // person needed, and left every refusal looking like the same anonymous failure.
  // Kept identical to serverMessage() in work-planner.js.
  function serverMessage(body, status){
    var j=null;
    try{ j=JSON.parse(body); }catch(e){}
    if(j){
      var msgs=[];
      try{
        (JSON.parse(j._server_messages||"[]")).forEach(function(m){
          var o=null; try{ o=JSON.parse(m); }catch(e2){ o={message:m}; }
          if(o && o.message) msgs.push(String(o.message));
        });
      }catch(e3){}
      if(msgs.length) return msgs.join(" ").replace(/<[^>]+>/g,"").trim();
      if(j.message && typeof j.message==="string") return j.message;
      if(j.exception) return String(j.exception).replace(/^[\w.]+Error:\s*/,"").trim();
      if(j.exc_type) return String(j.exc_type);
    }
    return "The server refused it (HTTP "+status+")";
  }
  function readOr(r){
    if(r.ok) return r.json();
    return r.text().then(function(t){ throw new Error(serverMessage(t, r.status)); });
  }
  function call(args, method){
    // `method` names another screen's script, the way work-planner.js does it --
    // needed only for wm_dashboard's task_names map, which no other script serves.
    var ep = "/api/method/" + (method || "wm_assigner");
    // Which actions POST. This is not decoration: frappe/app.py:sync_database()
    // commits on POST and ROLLS BACK on GET, so an action missing from here is
    // answered "1 approved." by a server that then throws the approval away.
    var writes = {a_submit:1, a_approve:1, a_reject:1,
                  a_substitute:1, a_release:1, a_add_crew:1,
                  a_approve_bulk:1, a_reject_bulk:1};
    var isWrite = writes[args.action] === 1;
    var p = new URLSearchParams();
    for(var k in args){ if(args[k]!==undefined && args[k]!==null) p.append(k, args[k]); }
    var token = (typeof frappe!=="undefined" && frappe.csrf_token) ? frappe.csrf_token : "";
    if(!isWrite){
      return fetch(ep + "?" + p.toString(), { method:"GET", headers:{ "Accept":"application/json" }, credentials:"same-origin" })
        .then(readOr).then(function(j){ return j.message || {}; });
    }
    return fetch(ep, {
      method:"POST",
      headers:{ "Content-Type":"application/x-www-form-urlencoded", "X-Frappe-CSRF-Token":token, "Accept":"application/json" },
      body:p.toString(),
      credentials:"same-origin"
    }).then(readOr).then(function(j){ return j.message || {}; });
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  // What a task is CALLED, not what it is filed under. Every read here hands back
  // a Task docname, and on a site whose Task autoname is a series that docname is
  // `TASK-2026-00131` -- which is what this screen was printing, including in the
  // plan picker. wm_dashboard's task_names action returns {docname: subject}; the
  // fallback is the docname, so a site named by subject looks exactly as it did.
  var TASK_NAMES={};
  function taskName(t){ return (t && TASK_NAMES[t]) || t || ""; }
  // What this installation calls the levels. Falls back to the shipped wording
  // so the screen still reads correctly if the template has not loaded.
  var TXN = (window.WM_TAXONOMY || {});
  function TX(key, fallback) { return TXN[key] || fallback; }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function blocksLbl(obj){ var a=(obj&&obj.blocks)||null; if(a&&a.length){ var o=[]; for(var i=0;i<a.length;i++){ o.push(lbl(a[i])); } return o.join(", "); } return lbl(obj&&obj.block_section); }
  function el(id){ return document.getElementById(id); }
  function isoTodayA(){ var d=new Date(); function p(n){ return (n<10?"0":"")+n; } return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate()); }
  function toast(m){ var t=el("wa-toast"); t.textContent=m; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2200); }
  function nPicked(){ var n=0; for(var k in ST.picked){ if(ST.picked[k]) n++; } return n; }

  // ── THE CHAIN THIS SITE RUNS ────────────────────────────────────────────
  // Delivered with the page (window.WM_CHAIN), so the first render is already
  // right: a status chip is drawn before any roles call has answered, and a
  // screen that waits for the chain prints the raw state once and never
  // corrects itself. See api/config.py:screen_chain().
  var WM_DT = "Work Management Assigner";
  var CHAIN = (window.WM_CHAIN || {});
  // WHAT A WORKFLOW STATE IS CALLED HERE. `Pending GM` is a state name, not a
  // word anybody chose: the step waiting in it is called whatever Settings
  // says, and on Altura a chip read "Pending GM" beside a step labelled
  // "Master Plan: Manager". The state stays the identity underneath -- this is
  // only what gets printed. An unmapped state falls back to itself, which is
  // already the right word for Approved, Draft and Rejected: they are not
  // steps, and nothing configures them.
  function stateLabel(s, dt){
    var m=((CHAIN.labels||{})[dt||WM_DT])||{};
    return m[s] || s || "";
  }
  // One of the grouped state lists pipeline_states() publishes -- "all",
  // "waiting", "active", "open". For filters and option lists, which must keep
  // listing the states of switched-off steps: a list that narrows because
  // somebody changed a setting looks like data loss.
  function chainStates(group, dt){
    return (((CHAIN.states||{})[dt||WM_DT])||{})[group||"all"] || [];
  }
  // The three singular ones: "draft", "terminal", "reject". Not steps -- they
  // are where a chain begins and the two ways it ends -- so they are named
  // rather than listed, and a screen asks for them by role, never by name.
  function chainState(which, dt){
    return (((CHAIN.states||{})[dt||WM_DT])||{})[which] || "";
  }

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
    // WHO DECIDES A CLOSE comes from the chain, not from `is_gm` -- a shipped
    // role name that answered no to the person Altura's last actuals step
    // actually names.
    var isGm = !!(ST.roles && ST.roles.may_close_plans);
    var who = (ST.roles && ST.roles.decider_label) || "the approver";
    var dlg=el("wa-subdialog");
    var title = isGm ? "Close plan now" : "Request close";
    var desc = isGm
      ? "This finalises any open draft actuals to Confirmed and caps the plan (target kept for reporting). A reason is required."
      : ("This sends a close request to "+who+". Entry stays open until they confirm. A reason is required.");
    dlg.innerHTML =
      '<div style="background:#fff;max-width:440px;width:92%;border:2px solid var(--ink)">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--faint)">'+
          '<div style="font-size:13px;font-weight:700">'+title+'</div>'+
          '<button type="button" id="wac-x" style="border:none;background:none;font-size:20px;line-height:1;color:var(--mute);cursor:pointer">&times;</button>'+
        '</div>'+
        '<div style="padding:16px 18px">'+
          '<div style="font-size:12px;color:#444;margin-bottom:10px">'+esc(desc)+(planName?(' <span style="color:#777">Plan <b>'+esc(planName)+'</b>.</span>'):'')+'</div>'+
          '<label style="display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:600;margin-bottom:5px">Reason (required)</label>'+
          '<textarea id="wac-reason" rows="3" style="font-family:inherit;font-size:13px;border:1px solid var(--line);padding:8px 10px;width:100%;background:#fff;color:var(--ink);resize:vertical" placeholder="e.g. crop finished early, '+esc(TX("unit_singular","block").toLowerCase())+' cleared ahead of target"></textarea>'+
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
        toast(isGm ? "Plan closed" : ("Close request sent to "+who));
        if(typeof onDone==="function") onDone();
      }).catch(function(e){ toast("Close failed"); go.disabled=false; });
    };
  }

  // WHAT TO CALL THE PERSON READING THIS. The server answers it from the
  // configured chain -- the step or steps they can actually act on -- so a
  // Production Manager is not greeted as an HR Head, which is what a hardcoded
  // shipped role name did on Altura. Empty when they take no step.
  function whoSuffix(roles){
    var s=(roles&&roles.approver_label)||"";
    return s ? (" \u00b7 "+s) : "";
  }
  // THE APPROVALS TAB IS FOR APPROVERS, and who they are comes from the chain.
  // `is_approver` is true when the signed-in user may take any ENABLED step of
  // this document type -- the same question the approve action asks, so the tab
  // is there exactly when a press would be allowed.
  function buildTabs(){
    var tabs=[["assign","Assign"],["amine","My Assignments"],["arej","Rejected"]];
    if(ST.roles && ST.roles.is_approver) tabs.push(["aappr","Approvals"]);
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
  // THE QUEUES THIS INSTALLATION HAS, not the three this file used to name.
  // Farm Manager / HR Head / GM was the shipped chain and stopped being the
  // chain the moment the chain became configurable: a step switched off kept a
  // tab that could never fill, a renamed step kept its old name, and a step
  // ADDED got no tab at all. The server sends the strip -- label, state, action,
  // count, and whether it is a switched-off step still holding work -- built
  // from the same chain the approve actions consult. See
  // work_management/stage_pills.py.
  //
  // `key` is what the server is addressed by and `action` is only ever a LABEL.
  // They were confused here: the tab's `action` is the step's WORKFLOW action
  // ("FM Approve"), which is what the desk button says, and this screen posted it
  // as the dispatcher's own action and was answered "unknown action: FM Approve".
  // The dispatcher has one approval action and takes the step's key; see
  // work_management/chain.py.
  function apprQueues(){
    return ((ST.roles||{}).stages||[]).map(function(s){
      return {key:s.key, label:s.short_label||s.label, stage:s.state,
              verb:s.action, count:s.count, legacy:s.legacy};
    });
  }
  function renderApprovals(){
    var queues=apprQueues();
    var ok=false, i;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) ok=true; }
    if(!ok) ST._apprKey=queues[0].key;
    var bar=el("wa-appr-subtabs");
    if(bar){
      var h="";
      // label, count, and -- for a step switched off that still holds work --
      // the marker that says why a queue nobody routes to is still on screen
      queues.forEach(function(q){
        h+='<button type="button" class="subtab'+(q.key===ST._apprKey?" on":"")+
           '" data-sub="'+esc(q.key)+'"'+(q.legacy?' title="Switched off, so nothing new is routed here \u2014 but these are still waiting. Approving them needs the step switched back on in Settings; the tab goes once the last one is decided."':'')+'>'+
           esc(q.label)+
           (q.count ? ' <span class="cnt">'+fmt(q.count)+'</span>' : '')+
           (q.legacy ? ' <span class="subtab-legacy">off</span>' : '')+
           '</button>';
      });
      bar.innerHTML=h;
      bar.querySelectorAll("[data-sub]").forEach(function(b){ b.onclick=function(){ ST._apprKey=b.getAttribute("data-sub"); renderApprovals(); }; });
    }
    var q=null;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) q=queues[i]; }
    if(q) loadStage("aappr-body", q.key, q.verb);
  }
  // ---- shared list filter bar (search / farm / status / date range) ----
  function fbar(rows, opts){
    var farms={}; rows.forEach(function(r){ if(r.farm) farms[r.farm]=1; });
    var h='<div class="lfb">'+
      '<input type="text" data-f="q" placeholder="'+esc(opts.ph||"Search…")+'">'+
      '<select data-f="farm"><option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option>'+Object.keys(farms).sort().map(function(f){ return '<option>'+esc(f)+'</option>'; }).join("")+'</select>';
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
            '<div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:2px"><b style="font-size:12.5px">'+esc(a.name)+'</b><span style="font-size:10.5px;color:var(--mute)">'+esc(a.farm||"")+' · '+esc(taskName(a.task))+' · '+esc(blocksLbl(a))+'</span>'+
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
      fsel.innerHTML='<option value="">All '+esc(TX("top_plural","Farms")).toLowerCase()+'</option>';
      Object.keys(farms).sort().forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
      fsel.value=fkeep||"";
    }
    var tsel=el("a-f-task");
    if(tsel){
      var tkeep=tsel.value;
      tsel.innerHTML='<option value="">All tasks</option>';
      Object.keys(tasks).sort(function(x,y){ return taskName(x).localeCompare(taskName(y)); })
        .forEach(function(t){ var o=document.createElement("option"); o.value=t; o.textContent=taskName(t); tsel.appendChild(o); });
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
        var hay=((p.name||"")+" "+(p.farm||"")+" "+(p.block_section||"")+" "+taskName(p.task)).toLowerCase();
        if(hay.indexOf(fq)<0) return;
      }
      shown++;
      var taken = p.already_assigned?true:false;
      var sel = (ST.plan===p.name) ? " sel" : "";
      var takenCls = taken ? " taken" : "";
      var meta='<div class="pl-task">'+esc(taskName(p.task))+(taken?'<span class="pl-tk">assigned</span>':'')+'</div>'+
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
        '<div class="dl"><span class="k">'+esc(TX("top_singular","Farm"))+'</span><span class="v">'+esc(p.farm)+'</span></div>'+
        '<div class="dl"><span class="k">'+esc(TX("unit_singular","Block"))+'</span><span class="v">'+esc(blocksLbl(p))+'</span></div>'+
        '<div class="dl"><span class="k">Task</span><span class="v">'+esc(taskName(p.task))+'</span></div>'+
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
    ST.curFarm=farm;
    call({action:"a_employees",farm:farm,from_date:pd.from_date,to_date:pd.to_date,exclude_assignment:(ST.editingAsg||"")}).then(function(d){
      ST.employees=d.employees||[];
      ST._empAll=d.employees||[];
      ST._empSplitOk=!!d.allow_split_day;
      ST.scanInfo=d.scan_info||{};
      // whether the project asked for today's presence -- the endpoint answers,
      // because off it does not run the reads and there is nothing to draw
      ST.showToday=!!d.show_today;
      el("a-emfilter").disabled=false;
      renderEmployees();
    });
  }

  function renderEmployees(){
    var q=(el("a-emfilter").value||"").toLowerCase();
    var box=el("a-empicker");
    var si=ST.scanInfo||{};
    var list=ST.employees.filter(function(e){
      if(ST.onlyIn && ST.showToday && !e.present_today) return false;
      if(!q) return true;
      return ((e.employee_name||"")+" "+(e.designation||"")+" "+(e.name||"")).toLowerCase().indexOf(q)>=0;
    });
    var h="";
    // ── PRESENCE BAR: the scans for the WINDOW'S OWN DAYS ──
    // ...but only when the endpoint actually read them. With the setting off it
    // runs none of the three presence queries, so present_count is 0 because
    // nothing was counted, not because nobody came in. Printing "P 0 of 79
    // scanned in" then states as measured a thing never measured, and the
    // "Only workers who are in" filter beside it hides everybody.
    //
    // WHICH DAY, said out loud. This read "scanned in / marked present today"
    // whatever window the plan covered, and Altura plans past weeks -- so a
    // fortnight-old window was captioned with this morning's scans. The server
    // now answers for the window's last day that has happened, and says which
    // day that was; the caption repeats it rather than assuming.
    if(ST.showToday) h+='<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 12px;margin-bottom:8px;border:1px solid var(--line,#e5e5e5);border-radius:10px;background:rgba(10,122,67,.05);font-size:11.5px">'+
      '<b style="color:#0a7a43">P '+(si.present_count||0)+'</b> of '+(si.total||0)+' '+esc(ST.curFarm||"")+' workers scanned in / marked present '+esc(presDayWord(si))+
      (si.checked && si.gate_on && !si.cutoff_passed ? ' <span style="color:#a06000">· scan check starts at '+esc((si.cutoff||"09:00").slice(0,5))+'</span>' : '')+
      ' <span style="color:#8a8780">· key: <b style="color:#0a7a43">P · time</b> in &nbsp;<b style="color:#b91c1c">A</b> absent &nbsp;<b>?</b> no record yet</span>'+
      '<span style="flex:1"></span>'+
      '<label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;font-weight:600"><input type="checkbox" id="a-onlyin"'+(ST.onlyIn?" checked":"")+'> Only workers who are in</label>'+
      '<a href="#" id="a-rescan" style="font-weight:600">Refresh scans</a></div>';
    if(!list.length){ box.innerHTML=h+'<div class="empty">No matching workers'+(ST.onlyIn?' — nobody in this filter was seen on site '+esc(presDayWord(si)):'')+'.</div>'; wireScanBar(box); return; }
    list.forEach(function(e){
      var on=ST.picked[e.name]?" on":"";
      var offbadge = (e.off_days>0) ? ' <span class="offb">'+e.off_days+' off</span>' : '';
      var aw=attReasons(e);
      var attbadge = aw.length? ' <span class="offb" style="background:rgba(185,28,28,.12);color:#b91c1c">⚠ '+esc(aw[0].split(" on 2")[0])+'</span>' : '';
      // Today's presence chip, only where the project asked for it. Off -- the
      // default -- the endpoint runs none of the attendance reads and there is
      // nothing to draw; "?" against every worker on a site without biometric
      // hardware reads as a finding and is not. Everything else on the row, and
      // the warning badge from the att_block_* checks above, is unaffected.
      var pday=presDayWord(si);
      var pspan=presSpanWord(si, e);
      if(!ST.showToday){
        /* no presence chip */
      } else if(e.is_night){
        attbadge += ' <span class="offb" style="background:rgba(37,99,235,.1);color:#2563eb">night shift</span>';
      } else if(e.present_today){
        attbadge += ' <span class="offb" style="background:rgba(10,122,67,.14);color:#0a7a43;font-weight:700" title="On site '+esc(pday)+(e.scan_in?(' — scanned in '+esc(e.scan_in)):'')+pspan+'">P'+(e.scan_in?(' · '+esc(e.scan_in)):'')+'</span>';
      } else if(e.absent_today){
        attbadge += ' <span class="offb" style="background:rgba(185,28,28,.14);color:#b91c1c;font-weight:700" title="Marked Absent '+esc(pday)+' (submitted attendance)'+pspan+'">A '+esc(pday)+'</span>';
      } else {
        attbadge += ' <span class="offb" style="background:rgba(10,10,10,.06);color:#8a8780" title="No scan or attendance record for '+esc(pday)+pspan+'">? '+esc(pday)+'</span>';
      }
      var busy = e.allocated_elsewhere?true:false;
      if(busy){
        // BUSY IS A FAULT OR A PLAN, and the switch is what decides which. With a
        // split day allowed this worker may be picked -- the chip warns, the row
        // stays live, and the click asks for confirmation. Rendering the hard block
        // regardless is what made the switch look broken: the server had been
        // flag-aware here since the feature shipped, and the picker greyed the row
        // out anyway, so the people the switch exists to allow were the exact
        // people it hid.
        var tag = ST._empSplitOk
          ? ' <span class="allocb warn">on another task — day will split</span>'
          : ' <span class="allocb">assigned elsewhere'+(e.allocated_farm?(" · "+esc(e.allocated_farm)):"")+'</span>';
        var where = 'Already on '+esc(e.allocated_asg||"")+' ('+esc(e.allocated_task||"")+') for an overlapping period';
        h+='<div class="emrow '+(ST._empSplitOk?"split":"busy")+(ST._empSplitOk?on:"")+'" data-emp="'+esc(e.name)+'" title="'+where+(ST._empSplitOk?'. Selecting them splits the day — record the hours each task took on the actuals screen.':'')+'">'+
           '<input type="checkbox" '+(ST._empSplitOk?(ST.picked[e.name]?"checked":""):"disabled")+'>'+
           '<span class="en">'+esc(e.employee_name||e.name)+tag+'</span>'+
           '<span class="ed">'+esc(e.designation||"")+' · '+esc(e.employment_type||"")+'</span></div>';
      } else {
        h+='<div class="emrow'+on+'" data-emp="'+esc(e.name)+'"'+(aw.length?' title="'+esc(aw.join(" · "))+'"':'')+'>'+
           '<input type="checkbox" '+(ST.picked[e.name]?"checked":"")+'>'+
           '<span class="en">'+esc(e.employee_name||e.name)+offbadge+attbadge+'</span>'+
           '<span class="ed">'+esc(e.designation||"")+' · '+esc(e.employment_type||"")+'</span></div>';
      }
    });
    box.innerHTML=h;
    wireScanBar(box);
    box.querySelectorAll(".emrow").forEach(function(row){
      // Busy elsewhere is non-selectable only while a shared day is a fault. With
      // the split-day switch on it is a plan, and refusing to select these rows
      // would hide exactly the people the switch permits -- the server warns
      // instead of refusing, so the screen should too. `.busy` is now rendered
      // only in the hard-block case, so this is belt and braces.
      if(row.classList.contains("busy")) return;
      row.onclick=function(){
        var id=row.getAttribute("data-emp");
        if(!ST.picked[id]){
          // TIME & ATTENDANCE: explicit consent before selecting a flagged worker
          var emp=null;
          (ST.employees||[]).forEach(function(x){ if(x.name===id) emp=x; });
          var aw2=emp?attReasons(emp):[];
          if(aw2.length){
            var nm=(emp.employee_name||id);
            if(!window.confirm("Attendance check — "+nm+" is "+aw2.join(", and ")+".\n\nSelect this worker anyway?")) return;
          }
          // SPLITTING A DAY IS DELIBERATE, so it is confirmed rather than assumed.
          // Same shape as the attendance consent above, and the same words the
          // server uses when it warns on submit.
          if(emp && emp.allocated_elsewhere && ST._empSplitOk){
            var nm2=(emp.employee_name||id);
            if(!window.confirm(nm2+" is already assigned to "+(emp.allocated_task||emp.allocated_asg||"another task")+
              " over these dates.\n\nTheir day will be split between the two. Record the hours each task took on the actuals screen, or the day counts twice.\n\nAdd them to this crew?")) return;
          }
        }
        ST.picked[id]=!ST.picked[id];
        row.classList.toggle("on", ST.picked[id]);
        var cb=row.querySelector("input"); if(cb) cb.checked=ST.picked[id];
        refreshCounts();
      };
    });
  }

  // WHICH DAY THE PRESENCE CHIPS ANSWER FOR. "today" only when the window
  // actually contains today; otherwise the date itself, because "today" printed
  // against a plan for last Tuesday is the bug this replaces. Empty when no day
  // of the window has happened yet -- a future window has no presence, and none
  // is not a finding.
  function presDayWord(si){
    if(!si || !si.to) return "—";
    return si.is_today ? "today" : ("on "+si.to);
  }
  // ...and, on a window of more than one day, how much of it they were there
  // for. A single-day window says nothing extra; the day itself is the answer.
  function presSpanWord(si, e){
    if(!si || !si.days || si.days < 2) return "";
    var seen = e.present_days||0, abs = e.absent_days_window||0;
    return ". Seen on "+seen+" of the "+si.days+" days asked about ("+si.from+" → "+si.to+")"+
           (abs? ", marked Absent on "+abs : "");
  }

  // TIME & ATTENDANCE reasons for one worker in the plan window (from a_employees)
  function attReasons(e){
    var aw=[];
    if(e.att_leave) aw.push("on "+e.att_leave);
    if(e.att_absent_days>0) aw.push("marked Absent "+e.att_absent_days+" day"+(e.att_absent_days>1?"s":"")+(e.att_absent_span?" ("+e.att_absent_span+")":"")+" in this window");
    if(e.att_all_off) aw.push(e.att_off_reason||"off-day conflict in this window");
    var si=ST.scanInfo||{};
    // ST.showToday first: with the presence setting off the endpoint looks nothing
    // up, so present_today is 0 for everybody and means "not asked", not "not here".
    // Without this the screen red-flags every worker on site and puts a confirm()
    // on each row click -- which is what it did to 79 Vale workers who had all
    // scanned in before 07:00. The other three reasons above come from the
    // att_block_* settings and are unaffected.
    if(ST.showToday && si.checked && si.gate_on && si.cutoff_passed && !e.present_today && !e.is_night){
      aw.push("not seen on site today (no scan or Present attendance yet)");
    }
    return aw;
  }

  function wireScanBar(box){
    var oi=el("a-onlyin");
    if(oi){ oi.onchange=function(){ ST.onlyIn=oi.checked; renderEmployees(); }; }
    var rs=el("a-rescan");
    if(rs){ rs.onclick=function(ev){ ev.preventDefault(); rs.textContent="Refreshing…"; loadEmployees(ST.curFarm); }; }
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
      if(d.needs_att_override){
        // server-side attendance gate: show every conflict, ask once, resend
        var lines=(d.att_conflicts||[]).map(function(c){ return "• "+(c.name||c.employee)+": "+(c.reasons||[]).join("; "); });
        if(window.confirm("Attendance check — these workers have conflicts:\n\n"+lines.join("\n")+"\n\nAssign anyway? The override is recorded on the assignment.")){
          args.att_override=1;
          call(args).then(function(d2){
            if(d2.error){ toast("Error: "+d2.error); refreshCounts(); return; }
            afterSubmit(d2, submitNow);
          }).catch(function(e){ toast(e && e.message ? e.message : "Failed to save"); refreshCounts(); });
        } else { refreshCounts(); }
        return;
      }
      if(d.error){ toast("Error: "+d.error); refreshCounts(); return; }
      afterSubmit(d, submitNow);
    }).catch(function(e){ toast(e && e.message ? e.message : "Failed to save"); refreshCounts(); });
  }

  function afterSubmit(d, submitNow){
    var verb = d.editing ? (submitNow?"Updated & submitted ":"Draft updated ") : (submitNow?"Submitted ":"Draft saved ");
    // WHAT THE SERVER ALLOWED BUT WANTED SAID. With a split day permitted the
    // submit stops refusing and starts warning -- about a crew larger than the
    // plan's people/day, and about workers whose day is now shared -- and both
    // warnings were being computed and then dropped on the floor here, so the
    // one screen that could act on them never showed them. Same treatment the
    // Add-to-crew path already gives them.
    var notes=[];
    if(d.crew_warning) notes.push(d.crew_warning);
    if(d.split_warning) notes.push(d.split_warning);
    if(notes.length){
      window.alert(verb+d.name+" · "+d.workflow_state+"\n\n\u2022 "+notes.join("\n\n\u2022 "));
    }
    toast(verb+d.name+" · "+d.workflow_state+(d.att_overridden?(" · attendance override logged for "+d.att_overridden):""));
    clearEdit();
    ST.plan=null; ST.picked={}; ST.planDetail=null; ST.employees=[];
    el("a-plan").value=""; el("a-detail").style.display="none";
    el("a-empicker").innerHTML='<div class="empty">Pick a plan to load that '+esc(TX("top_singular","Farm")).toLowerCase()+'’s workers.</div>';
    el("a-emfilter").value=""; el("a-emfilter").disabled=true; el("a-farmlabel").textContent="";
    el("o-plan").textContent="—";
    refreshCounts(); loadPlans();
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
          '<div class="dl"><span class="k">'+esc(TX("top_singular","Farm"))+'</span><span class="v">'+esc(p.farm)+'</span></div>'+
          '<div class="dl"><span class="k">'+esc(TX("unit_singular","Block"))+'</span><span class="v">'+esc(blocksLbl(p))+'</span></div>'+
          '<div class="dl"><span class="k">Task</span><span class="v">'+esc(taskName(p.task))+'</span></div>'+
          '<div class="dl"><span class="k">Standard</span><span class="v">'+esc(p.task_kpi||"—")+'</span></div>'+
          '<div class="dl"><span class="k">Period</span><span class="v">'+esc(p.from_date)+' → '+esc(p.to_date)+'</span></div>'+
          '<div class="dl"><span class="k">Planned people/day</span><span class="v big">'+fmt(p.people_per_day)+'</span></div>'+
          '<div class="dl"><span class="k">Planned cost</span><span class="v big">KES '+fmt(p.total_cost)+'</span></div>';
        el("a-farmlabel").textContent="· "+p.farm;
        el("o-plan").textContent=fmt(p.people_per_day);
        call({action:"a_employees",farm:p.farm}).then(function(ed){
          ST.employees=ed.employees||[];
          ST._empAll=ed.employees||[];
          ST._empSplitOk=!!ed.allow_split_day;
          el("a-emfilter").disabled=false;
          ST.picked={};
          (a.workers||[]).forEach(function(w){ if((w.status||"Active")==="Active") ST.picked[w.employee]=true; });
          renderEmployees();
          refreshCounts();
        });
      });
      var b=el("a-editbanner");
      if(b){ b.style.display="block"; b.innerHTML="Editing <b>"+esc(a.name)+"</b> ("+esc(stateLabel(a.workflow_state))+") — changes update this assignment. <a href='#' id='a-cancel-edit'>Cancel edit</a>";
        var c=document.getElementById("a-cancel-edit"); if(c) c.onclick=function(ev){ ev.preventDefault(); clearEdit(); onPlan.call({value:""}); toast("Edit cancelled"); }; }
      el("b-asubmit").textContent="Update & Submit";
      el("b-adraft").textContent="Update Draft";
    }).catch(function(e){ toast("Could not load"); });
  }

  // The chip prints the step's configured LABEL and keeps the state as its
  // identity underneath -- `title` and `data-state` still carry the raw string,
  // so anything reading the DOM, or anybody reporting a fault, still has it.
  // The colour is chosen by what the state IS in this chain rather than by its
  // name: the end of the chain, a rejection, or somewhere work is waiting.
  function stateTag(s){
    var c="pend";
    if(s===chainState("terminal")) c="assigned";
    else if(s===chainState("reject")) c="rej";
    else if(chainStates("waiting").indexOf(s)<0) c="";
    return '<span class="tag '+c+'" data-state="'+esc(s||"")+'" title="'+esc(s||"")+'">'+
           esc(stateLabel(s)||"Draft")+'</span>';
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
        + fbar(rows,{dates:hasDates,statuses:Object.keys(sts).sort(),ph:"Search ref, plan, "+TX("top_singular","Farm").toLowerCase()+", "+TX("unit_singular","Block").toLowerCase()+", task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:r.workflow_state||"", date:isodate(r.from_date),
                hay:((r.name||"")+" "+(r.planner_request||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+taskName(r.task)).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Plan</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>'+esc(TX("unit_singular","Block"))+'</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Var</th><th>Status</th><th></th></tr></thead><tbody>';
        list.forEach(function(r){
          // EDITABLE WHILE THE CHAIN HAS NOT FINISHED WITH IT. Three states
          // were named here, two of which are not steps and one of which --
          // `Pending HR Head` -- is a step a site need not have, so on a
          // reconfigured chain the Edit button vanished from every row waiting
          // mid-chain. `open` is draft, rejected and every waiting step, which
          // is what pipeline_states() publishes it for.
          var editable = chainStates("open").indexOf(r.workflow_state)>=0;
          var canSub = (r.workflow_state===chainState("terminal"));
          var actionBtn = editable ? '<button class="btn" data-edit="'+esc(r.name)+'">Edit</button>' : (canSub ? '<button class="btn solid" data-sub="'+esc(r.name)+'">Manage crew</button>' : '');
          h+='<tr data-xa="'+esc(r.name)+'"><td>'+esc(r.name)+'</td><td>'+esc(r.planner_request)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(taskName(r.task))+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+varTag(r.variance)+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+actionBtn+'</td></tr>';
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
    var isGm=!!(ST.roles&&ST.roles.may_close_plans);
    var closeLabel=isGm?"Close plan":"Request close";
    b.className="";
    b.innerHTML='<div class="note" style="margin-bottom:8px">These assignments were rejected. Click <b>Edit</b> to adjust the roster and resubmit — or <b>'+closeLabel+'</b> if the underlying plan should be stopped.</div>'
      + fbar(all,{dates:true,ph:"Search ref, plan, "+TX("top_singular","Farm").toLowerCase()+", "+TX("unit_singular","Block").toLowerCase()+", task…"});
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.planner_request||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+taskName(r.task)).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Ref</th><th>Plan</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>'+esc(TX("unit_singular","Block"))+'</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Status</th><th></th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr data-xa="'+esc(r.name)+'"><td>'+esc(r.name)+'</td><td>'+esc(r.planner_request)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(taskName(r.task))+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+stateTag(r.workflow_state)+'</td>'+
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
        // Two pools, because swap and add have two different write paths: swap
        // refuses a busy replacement whatever the flag, add allows one when the
        // flag is on. The payload carries the flag too, so this dialog no longer
        // depends on state some earlier flow happened to leave behind.
        ST._empSplitOk=!!cd.allow_split_day;
        showSubDialog(a, actives, cd.candidates||[], cd.add_candidates||cd.candidates||[]);
      });
    });
  }
  function showSubDialog(a, actives, cands, addCands){
    var ov=el("wa-subdialog");
    var uom=a.uom||"";
    var pct = a.target_qty>0 ? (a.fulfilled_qty/a.target_qty*100) : 0;
    var barPct=Math.min(pct,100);
    var left =
      '<div class="sub-col sub-left">'+
        '<div class="sub-h">Plan &amp; task</div>'+
        '<div class="dl"><span class="k">Assignment</span><span class="v">'+esc(a.name)+'</span></div>'+
        '<div class="dl"><span class="k">Plan</span><span class="v">'+esc(a.planner_request)+'</span></div>'+
        '<div class="dl"><span class="k">'+esc(TX("top_singular","Farm"))+'</span><span class="v">'+esc(a.farm)+'</span></div>'+
        '<div class="dl"><span class="k">'+esc(TX("unit_singular","Block"))+'</span><span class="v">'+esc(blocksLbl(a))+'</span></div>'+
        '<div class="dl"><span class="k">Task</span><span class="v">'+esc(taskName(a.task))+'</span></div>'+
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
    // WHO MAY CHANGE THE CREW. Three role flags OR-ed together, two of them
    // named after roles a site need not have -- so on Altura the release panel
    // was hidden from the Production Manager the server would have allowed.
    // One answer, resolved from the configured chain by a_roles.
    var canRelease = !!(ST.roles && ST.roles.may_change_crew);
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
    // Add offers the same candidates, plus -- where a split day is allowed --
    // the ones already assigned elsewhere, tagged so the picker is honest about
    // it. Hiding them would hide exactly the people the switch permits.
    //
    // The server builds this pool now. It used to be assembled here from
    // `ST._empAll`, which only the assign and edit flows ever fill: opening
    // Manage crew directly left it undefined, so the pool silently fell back to
    // the free-workers-only list and the switch did nothing on this screen.
    var addPool = addCands || cands;
    var onRoster = {};
    (a.workers||[]).forEach(function(w){ onRoster[w.employee]=1; });
    var addOpts = addPool.filter(function(c){ return !onRoster[c.name]; })
      .map(function(c){
        var tag = c.allocated_elsewhere ? (' \u00b7 also on '+(c.allocated_task||c.allocated_asg||'another task')) : '';
        return '<option value="'+esc(c.name)+'">'+esc(c.employee_name||c.name)+esc(tag)+'</option>';
      }).join("");
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
        (canRelease ? (
          '<div class="sub-h" style="margin-top:16px">Add a worker</div>'+
          '<div class="sub-note" style="margin-bottom:8px">For somebody who worked and is not on the list. Nobody has to leave to make room \u2014 the plan\u2019s quantity still caps what can be recorded and paid, so the crew simply shares the same budgeted work.</div>'+
          '<label>Worker to add</label>'+
          '<select id="add-emp"><option value="">\u2014 pick a worker \u2014</option>'+(addOpts||'')+'</select>'+
          '<label>Starting on</label>'+
          '<input type="date" id="add-start" min="'+esc(a.from_date)+'" max="'+esc(a.to_date)+'" value="'+esc(a.from_date)+'">'+
          '<div class="sub-actions"><button class="btn solid" id="add-confirm">Add to crew</button></div>'
        ) : '')+
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
    // ---- add-a-worker wiring (same FM/HR/GM gate as release; the server
    //      enforces it too, because a gate in the browser is not a gate) ----
    var addBtn=el("add-confirm");
    if(addBtn){
      addBtn.onclick=function(){
        var emp=el("add-emp").value, from=el("add-start").value;
        if(!emp){ toast("Pick a worker to add"); return; }
        if(!from){ toast("Pick the date they start"); return; }
        addBtn.disabled=true;
        call({action:"a_add_crew", assignment:a.name, employees:emp, start_date:from})
          .then(function(r){
            if(r.error){ toast("Error: "+r.error); addBtn.disabled=false; return; }
            var notes=[];
            if(r.cap_warning) notes.push(r.cap_warning);
            if(r.split_warning) notes.push(r.split_warning);
            if(notes.length) window.alert((r.message||"Added.")+"\n\n\u2022 "+notes.join("\n\n\u2022 "));
            else toast(r.message||"Added to crew");
            close(); loadMine();
          })
          .catch(function(e){ toast("Could not add"); addBtn.disabled=false; });
      };
    }
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

  // ── BULK APPROVE / REJECT ───────────────────────────────────────────────
  // The client: "the system allows submission and approval of one task at a
  // time... time consuming with a large number of people." The server runs each
  // document through the very branch its own row button uses, so nothing here
  // decides anything -- this only chooses WHICH documents and renders what came
  // back. See work_management/bulk.py.
  //
  // This tab shows ONE stage at a time, and the bulk call carries that stage:
  // approving across stages in one press would approve work the user is not
  // looking at.
  var BULK={picked:{}};
  function bulkPicked(rows){
    var live={}; (rows||[]).forEach(function(r){ live[r.name]=1; });
    return Object.keys(BULK.picked).filter(function(n){ return BULK.picked[n] && live[n]; });
  }
  function bulkBar(rows){
    var n=bulkPicked(rows).length;
    return '<div class="filters" id="bulk-bar" style="margin-bottom:8px;padding:8px 14px;gap:8px;align-items:center">'+
      '<label style="display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;cursor:pointer">'+
        '<input type="checkbox" id="bulk-all"> Select all shown</label>'+
      '<span class="hint" id="bulk-n" style="font-weight:600;color:var(--ink)">'+(n?fmt(n)+" selected":"")+'</span>'+
      '<span style="flex:1"></span>'+
      '<button type="button" class="btn solid" id="bulk-app"'+(n?'':' disabled')+'>Approve selected'+(n?' ('+fmt(n)+')':'')+'</button>'+
      '<button type="button" class="btn" id="bulk-rej"'+(n?'':' disabled')+'>Reject selected'+(n?' ('+fmt(n)+')':'')+'</button>'+
      '</div>'+
      // revealed by "Reject selected", so the reason is typed against a
      // selection that is still visible
      '<div id="bulk-why" style="display:none;margin-bottom:8px;padding:10px 14px;border:1px solid #fed7aa;background:#fff7ed;border-radius:var(--r)">'+
        '<label style="display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:#7c2d12;font-weight:700;margin-bottom:5px">Why are these being rejected? (recorded on every one)</label>'+
        '<textarea id="bulk-why-text" rows="2" style="font-family:inherit;font-size:12.5px;border:1px solid var(--line);padding:7px 9px;width:100%;background:#fff;color:var(--ink);resize:vertical"></textarea>'+
        '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:8px">'+
          '<button type="button" class="btn sm" id="bulk-why-cancel">Cancel</button>'+
          '<button type="button" class="btn solid sm" id="bulk-why-go">Reject '+fmt(n)+'</button>'+
        '</div></div>'+
      '<div id="bulk-result"></div>';
  }
  // Partial success is the normal case with a mixed queue, so it renders as a
  // result to read rather than one alert per document.
  function bulkResult(d){
    var box=el("bulk-result"); if(!box) return;
    if(!d || (!d.ok && !d.failed)){ box.innerHTML=""; return; }
    var ok=d.ok||[], bad=d.failed||[];
    var h='<div class="banner '+(bad.length?(ok.length?'info':'warn'):'good')+'" style="margin-bottom:10px;display:block">'+
      '<b>'+esc(d.summary||"")+'</b>';
    if(bad.length){
      h+='<ul style="margin:8px 0 0 16px;padding:0">';
      bad.forEach(function(f){ h+='<li>'+esc(f.name)+' — '+esc(f.why)+'</li>'; });
      h+='</ul>';
    }
    box.innerHTML=h+'</div>';
  }
  function wireBulk(body, rows, stageKey, reload){
    var all=el("bulk-all"), napp=el("bulk-app"), nrej=el("bulk-rej");
    var sync=function(){
      var n=bulkPicked(rows).length;
      if(el("bulk-n")) el("bulk-n").textContent=n?fmt(n)+" selected":"";
      if(napp){ napp.disabled=!n; napp.textContent="Approve selected"+(n?" ("+fmt(n)+")":""); }
      if(nrej){ nrej.disabled=!n; nrej.textContent="Reject selected"+(n?" ("+fmt(n)+")":""); }
    };
    body.querySelectorAll("[data-bpick]").forEach(function(cb){
      cb.onclick=function(ev){ ev.stopPropagation(); BULK.picked[cb.getAttribute("data-bpick")]=cb.checked; sync(); };
    });
    if(all) all.onclick=function(){
      body.querySelectorAll("[data-bpick]").forEach(function(cb){
        cb.checked=all.checked; BULK.picked[cb.getAttribute("data-bpick")]=all.checked;
      });
      sync();
    };
    var send=function(which, reason){
      var names=bulkPicked(rows);
      if(!names.length) return;
      var args={ action:which, names:JSON.stringify(names), stage:stageKey };
      if(reason) args.reason=reason;
      if(napp) napp.disabled=true; if(nrej) nrej.disabled=true;
      call(args).then(function(d){
        if(d.error){ toast("Error: "+d.error); sync(); return; }
        BULK.picked={};
        toast(d.summary||"Done");
        reload(d);
      }).catch(function(e){ toast(e && e.message ? e.message : "Bulk action failed"); sync(); });
    };
    // THE REASON IS A FIELD, NOT A BROWSER PROMPT. It sits in the bar with the
    // selection still on screen, so whoever is rejecting can see what they are
    // rejecting while they type why -- and a prompt() cannot be styled, cannot
    // be a textarea, and disappears the moment focus moves.
    var why=el("bulk-why");
    if(nrej) nrej.onclick=function(){
      if(!bulkPicked(rows).length) return;
      if(why){ why.style.display="block"; var t=el("bulk-why-text"); if(t) t.focus(); }
    };
    var cancel=el("bulk-why-cancel");
    if(cancel) cancel.onclick=function(){ if(why) why.style.display="none"; };
    var confirm=el("bulk-why-go");
    if(confirm) confirm.onclick=function(){
      var t=el("bulk-why-text"), text=String((t&&t.value)||"").trim();
      if(!text){ toast("A reason is required to reject"); if(t) t.focus(); return; }
      if(why) why.style.display="none";
      send("a_reject_bulk", text);
    };
    if(napp) napp.onclick=function(){ send("a_approve_bulk"); };
    sync();
  }

  // `stageKey` is the configured step's key -- the one name a screen may hold,
  // and only because the server handed it over with the tab. `verb` is what the
  // step calls the decision and is printed, never sent.
  function loadStage(bodyId, stageKey, verb){
    var b=el(bodyId); b.className="loading"; b.innerHTML="Loading…";
    call({action:"a_pending", stage:stageKey}).then(function(d){
      var rows=d.pending||[];
      // stash for client-side farm filtering, keyed by the body element id
      ST._stageCache=ST._stageCache||{};
      ST._stageCache[bodyId]={rows:rows, stage:stageKey, verb:verb, farm:(ST._stageCache[bodyId]&&ST._stageCache[bodyId].farm)||""};
      renderStage(bodyId);
    });
  }
  function renderStage(bodyId){
    var b=el(bodyId); if(!b) return;
    var c=ST._stageCache[bodyId]; if(!c) return;
    var all=c.rows||[];
    if(!all.length){ b.className=""; b.innerHTML='<div class="empty">Nothing at this stage.</div>'; return; }
    b.className="";
    b.innerHTML=fbar(all,{dates:true,ph:"Search ref, "+TX("top_singular","Farm").toLowerCase()+", "+TX("unit_singular","Block").toLowerCase()+", task, assigned by…"}) + bulkBar(all);
    fwire(b, all, function(r){
      return {farm:r.farm||"", status:"", date:isodate(r.from_date),
              hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+taskName(r.task)+" "+(r.assigned_by||"")).toLowerCase()};
    }, function(body, rows){
      if(!rows.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th class="c" style="width:34px"></th><th>Ref</th><th>'+esc(TX("top_singular","Farm"))+'</th><th>'+esc(TX("unit_singular","Block"))+'</th><th>Task</th><th class="n">Planned</th><th class="n">Assigned</th><th>Var</th><th class="n">Cost</th><th>By</th><th>Action</th></tr></thead><tbody>';
      rows.forEach(function(r){
        h+='<tr data-xa="'+esc(r.name)+'">'+
           // stopPropagation on the box keeps a tick from also expanding the row
           '<td class="c"><input type="checkbox" data-bpick="'+esc(r.name)+'"'+(BULK.picked[r.name]?" checked":"")+'></td>'+
           '<td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(taskName(r.task))+'</td><td class="n">'+fmt(r.planned_people)+'</td><td class="n">'+fmt(r.assigned_count)+'</td><td>'+varTag(r.variance)+'</td><td class="n">'+fmt(r.planned_cost)+'</td><td>'+esc(r.assigned_by)+'</td><td><div class="ib"><button class="btn" data-edit="'+esc(r.name)+'">Edit</button><button class="btn solid" data-app="'+esc(r.name)+'">'+esc(c.verb||"Approve")+'</button><button class="btn" data-rej="'+esc(r.name)+'">Reject</button></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireExpandAsg(body, 11);
      body.querySelectorAll("[data-app]").forEach(function(btn){ btn.onclick=function(){ act("a_approve", btn.getAttribute("data-app"), bodyId, c.stage, c.verb); }; });
      body.querySelectorAll("[data-rej]").forEach(function(btn){ btn.onclick=function(){ act("a_reject", btn.getAttribute("data-rej"), bodyId, c.stage, c.verb); }; });
      body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ openAsgForEdit(btn.getAttribute("data-edit")); }; });
      // the stage the server wants is the step's KEY, which is the tab's own key.
      // It used to be derived by splitting the approve action on an underscore --
      // "a_fm_approve" -> "fm" -- which on a configured chain produced undefined.
      wireBulk(body, rows, c.stage,
        function(d){ loadStage(bodyId, c.stage, c.verb); setTimeout(function(){ bulkResult(d); }, 250); });
    });
  }
  function act(which,name,bodyId,stageKey,verb){
    var args={action:which,name:name};
    if(stageKey) args.stage=stageKey;
    call(args).then(function(d){
      if(d.error){ toast("Error: "+d.error); return; }
      toast(name+" → "+d.workflow_state);
      if(bodyId){ loadStage(bodyId, stageKey, verb); }
    }).catch(function(e){ toast(e && e.message ? e.message : "Action failed"); });
  }

  // WAIT FOR THE MAP BEFORE THE FIRST RENDER.
  // Every list on this screen prints its task through taskName(), and nothing
  // re-renders when a later answer arrives. The map used to be fetched by a call
  // nobody joined, so whether a row read "Coffee picking" or "TASK-2026-00155"
  // came down to which of two independent requests landed first -- undefined,
  // and free to differ between a local bench and a deployed site, or between two
  // loads of the same page. Joined now, not raced.
  //
  // It still cannot stop the screen opening, which is what the old comment here
  // was protecting: the call is caught, so a failure resolves instead of
  // rejecting, and an answer slower than the cap is abandoned. taskName() falls
  // back to the docname in both cases.
  var TASK_NAMES_WAIT = 4000;
  function taskNamesReady(){
    var got = call({action:"task_names"}, "wm_dashboard").then(function(d){
      TASK_NAMES = (d && d.task_names) || {};
    }).catch(function(){});
    return Promise.race([got, new Promise(function(done){
      setTimeout(done, TASK_NAMES_WAIT);
    })]);
  }

  function boot(){
    var names = taskNamesReady();
    call({action:"a_roles"}).then(function(roles){
      ST.roles=roles;
      el("wa-who").textContent=(roles.user||"")+whoSuffix(roles);
      return names.then(function(){
        initAssign();
        buildTabs();
      });
    }).catch(function(e){ el("wa-who").textContent="Could not load."; });
  }

  // No window.frappe check before booting -- see the note on the same line in
  // work-planner.js. The token is read on click, not now, and Guest is refused
  // server-side; guarding here only blanked the page when this script beat
  // Frappe's web bundle, which is what happens on the app's portal route.
  if(document.getElementById("a-plan")) boot();
  else document.addEventListener("DOMContentLoaded", boot);
})();
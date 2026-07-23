(function(){
  var ST = { asg:null, detail:null, cells:{}, roles:null };

  function csrf(){
    // Robust CSRF lookup: frappe global, then boot, then the meta tag Frappe injects.
    try{
      if(typeof frappe!=="undefined"){
        if(frappe.csrf_token) return frappe.csrf_token;
        if(frappe.boot && frappe.boot.csrf_token) return frappe.boot.csrf_token;
      }
    }catch(e){}
    var m=document.querySelector('meta[name="csrf_token"]');
    if(m && m.getAttribute("content")) return m.getAttribute("content");
    return "";
  }
  function call(args){
    var writes={act_submit:1,act_fm_approve:1,act_hr_approve:1,act_gm_approve:1,act_reject:1,a_substitute:1,act_close_confirm:1,act_close_request:1};
    var isWrite=writes[args.action]===1;
    var p=new URLSearchParams();
    for(var k in args){ if(args[k]!==undefined && args[k]!==null) p.append(k,args[k]); }
    var token=csrf();
    if(!isWrite){
      return fetch("/api/method/wm_actuals?"+p.toString(),{method:"GET",headers:{"Accept":"application/json","X-Frappe-CSRF-Token":token},credentials:"same-origin"})
        .then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){return j.message||{};});
    }
    return fetch("/api/method/wm_actuals",{method:"POST",
      headers:{"Content-Type":"application/x-www-form-urlencoded","X-Frappe-CSRF-Token":token,"Accept":"application/json"},
      body:p.toString(),credentials:"same-origin"}).then(function(r){ if(!r.ok) throw new Error("HTTP "+r.status); return r.json(); }).then(function(j){return j.message||{};});
  }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; return Number(n).toLocaleString("en-KE",{minimumFractionDigits:d||0,maximumFractionDigits:d||0}); }
  function esc(v){ return (v==null?"":String(v)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];}); }
  function lbl(w){ return (w||"").replace(" - KL",""); }
  function blocksLbl(obj){ var a=(obj&&obj.blocks)||null; if(a&&a.length){ var o=[]; for(var i=0;i<a.length;i++){ o.push(lbl(a[i])); } return o.join(", "); } return lbl(obj&&obj.block_section); }
  function el(id){ return document.getElementById(id); }
  function toast(m){ var t=el("ac-toast"); t.textContent=m; t.classList.add("show"); setTimeout(function(){t.classList.remove("show");},2400); }
  function isTaskWorker(et){ return (et||"")==="Task Worker"; }
  // active window: replacement open from start_date; outgoing(Left) open up to & incl left_date
  function offDay(w, iso){
    var offs=w.off_dates||[];
    for(var i=0;i<offs.length;i++){ if(offs[i]===iso) return true; }
    return false;
  }
  function leaveDay(w, iso){
    var lv=w.leave_dates||[];
    for(var i=0;i<lv.length;i++){ if(lv[i]===iso) return true; }
    return false;
  }
  function leavePendingDay(w, iso){
    var lv=w.leave_pending_dates||[];
    for(var i=0;i<lv.length;i++){ if(lv[i]===iso) return true; }
    return false;
  }
  function cellActive(w, iso){
    var st=(w.status||"Active");
    if(w.start_date && iso < w.start_date) return false;   // replacement not started yet
    if(st==="Left" && w.left_date && iso > w.left_date) return false;  // left worker, after last day
    if(offDay(w, iso)) return false;   // worker's rest day / holiday
    if(leaveDay(w, iso)) return false; // approved leave blocks entry
    return true;
  }
  function workerActiveLabel(w){
    var st=(w.status||"Active");
    if(st==="Left") return "left "+(w.left_date||"");
    if(w.start_date) return "from "+w.start_date;
    return "";
  }
  function pad(n){ return (n<10?"0":"")+n; }
  function daysBetween(from,to){
    var out=[]; if(!from||!to) return out;
    var d=new Date(from+"T00:00:00"), e=new Date(to+"T00:00:00");
    var guard=0;
    while(d<=e && guard<400){ out.push(d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())); d.setDate(d.getDate()+1); guard++; }
    return out;
  }
  function dowShort(iso){ var d=new Date(iso+"T00:00:00"); return ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][d.getDay()]; }
  function dnum(iso){ return parseInt(iso.slice(8,10),10); }
  function monLabel(iso){ var d=new Date(iso+"T00:00:00"); return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()]; }

  function buildTabs(){
    var tabs=[["enter","Enter Actuals"],["acmine","My Actuals"],["acrej","Rejected"],["acappr","Approvals"]];
    var nav=el("ac-tabs"); nav.innerHTML="";
    tabs.forEach(function(t){
      var b=document.createElement("button"); b.textContent=t[1]; b.setAttribute("data-tab",t[0]);
      b.onclick=function(){ showTab(t[0]); }; nav.appendChild(b);
    });
    showTab("enter");
  }
  function showTab(name){
    ["enter","acmine","acrej","acappr"].forEach(function(n){ var p=el("p-"+n); if(p) p.classList.toggle("on",n===name); });
    document.querySelectorAll("#ac-tabs button").forEach(function(b){ b.setAttribute("aria-selected",b.getAttribute("data-tab")===name); });
    if(name==="acmine") loadMine();
    if(name==="acrej") loadRejected();
    if(name==="acappr") renderApprovals();
  }
  function apprQueues(){
    var r=ST.roles||{}, q=[];
    if(r.is_farm_manager) q.push({key:"fm",label:"Farm Manager",stage:"Pending Farm Manager",action:"act_fm_approve"});
    if(r.is_hr_head) q.push({key:"hr",label:"HR Head",stage:"Pending HR Head",action:"act_hr_approve"});
    q.push({key:"gm",label:"GM",stage:"Pending GM",action:"act_gm_approve"});
    if(r.is_gm) q.push({key:"close",label:"Close Requests"});
    return q;
  }
  function renderApprovals(){
    var queues=apprQueues();
    var ok=false, i;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) ok=true; }
    if(!ok) ST._apprKey=queues[0].key;
    var bar=el("ac-appr-subtabs");
    if(bar){
      var h="";
      queues.forEach(function(q){ h+='<button type="button" class="subtab'+(q.key===ST._apprKey?" on":"")+'" data-sub="'+q.key+'">'+q.label+'</button>'; });
      bar.innerHTML=h;
      bar.querySelectorAll("[data-sub]").forEach(function(b){ b.onclick=function(){ ST._apprKey=b.getAttribute("data-sub"); renderApprovals(); }; });
    }
    var q=null;
    for(i=0;i<queues.length;i++){ if(queues[i].key===ST._apprKey) q=queues[i]; }
    if(q && q.key==="close") loadCloseRequests();
    else if(q) loadStage("acappr-body", q.stage, q.action);
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
  // ---- inline row expansion: click any row for full detail ----
  function rowFigs(pairs){
    var h='<div class="dv-figs">';
    pairs.forEach(function(p){ if(p[1]==null||p[1]==="") return; h+='<div class="dv-fig"><span>'+p[0]+'</span><b>'+p[1]+'</b></div>'; });
    return h+'</div>';
  }
  function deskA(label, route, name){
    if(!name) return "";
    return '<a class="dv-desk" style="margin-left:0" target="_blank" href="/app/'+route+'/'+encodeURIComponent(name)+'">'+label+' ↗</a>';
  }
  function wireExpand(body, colspan, detailFor){
    body.querySelectorAll("tr[data-x]").forEach(function(tr){
      tr.style.cursor="pointer";
      tr.onclick=function(ev){
        var t=ev.target;
        while(t && t!==tr){ if(t.tagName==="BUTTON"||t.tagName==="A"||t.tagName==="INPUT"||t.tagName==="SELECT"||(t.classList&&t.classList.contains("editlink"))) return; t=t.parentNode; }
        var nx=tr.nextElementSibling;
        var open=nx && nx.classList.contains("xd");
        body.querySelectorAll("tr.xd").forEach(function(x){ x.parentNode.removeChild(x); });
        if(open) return;
        var d=document.createElement("tr"); d.className="xd";
        d.innerHTML='<td colspan="'+colspan+'" style="white-space:normal;background:var(--wash);padding:0"><div class="dv" style="margin:8px 10px;box-shadow:none">'+detailFor(tr.getAttribute("data-x"))+'</div></td>';
        tr.parentNode.insertBefore(d, tr.nextSibling);
      };
    });
  }
  function resumeActual(asg){
    if(!asg) return;
    showTab("enter");
    var sel=el("ac-asg"); if(sel) sel.value=asg;
    onAsg(asg);
    renderAsgList();
    toast("Resuming — adjust quantities and resubmit");
  }

  function initEnter(){
    el("ac-asg").onchange=onAsg;
    ["ac-f-farm","ac-f-task","ac-f-pct","ac-f-from","ac-f-to"].forEach(function(id){ var e=el(id); if(e) e.onchange=renderAsgList; });
    ["ac-f-block","ac-f-q"].forEach(function(id){ var e=el(id); if(e) e.oninput=renderAsgList; });
    var clr=el("ac-f-clear");
    if(clr) clr.onclick=function(){
      ["ac-f-farm","ac-f-task","ac-f-pct","ac-f-from","ac-f-to"].forEach(function(id){ var e=el(id); if(e) e.value=""; });
      ["ac-f-block","ac-f-q"].forEach(function(id){ var e=el(id); if(e) e.value=""; });
      renderAsgList();
    };
    el("b-acdraft").onclick=function(){ doSubmit(0); };
    el("b-acsubmit").onclick=function(){ doSubmit(1); };
    initSubModal();
    initCloseModal();
    loadAssignments();
  }
  function loadAssignments(){
    call({action:"act_assigned"}).then(function(d){
      ST.asgList = d.assignments||[];
      // keep the hidden select in sync as the canonical value holder (existing call sites read/set it)
      var sel=el("ac-asg");
      if(sel){
        sel.innerHTML='<option value="">— select assigned work —</option>';
        ST.asgList.forEach(function(a){
          var o=document.createElement("option"); o.value=a.name; o.textContent=a.name; sel.appendChild(o);
        });
      }
      buildAsgFilters();
      renderAsgList();
    });
  }
  function pctBand(a){
    var t=a.target_qty||0; if(t<=0) return "notgt";
    var p=a.pct||0;
    if(p<=0) return "b0";
    if(p<50) return "b1";
    if(p<100) return "b2";
    return "b3";
  }
  function buildAsgFilters(){
    // farm + task option sets derived from the data
    var farms={}, tasks={};
    (ST.asgList||[]).forEach(function(a){
      if(a.farm) farms[a.farm]=1;
      if(a.task) tasks[a.task]=1;
    });
    var fsel=el("ac-f-farm");
    if(fsel){
      var fkeep=fsel.value;
      fsel.innerHTML='<option value="">All farms</option>';
      Object.keys(farms).sort().forEach(function(f){ var o=document.createElement("option"); o.value=f; o.textContent=f; fsel.appendChild(o); });
      fsel.value=fkeep||"";
    }
    var tsel=el("ac-f-task");
    if(tsel){
      var tkeep=tsel.value;
      tsel.innerHTML='<option value="">All tasks</option>';
      Object.keys(tasks).sort().forEach(function(t){ var o=document.createElement("option"); o.value=t; o.textContent=t; tsel.appendChild(o); });
      tsel.value=tkeep||"";
    }
  }
  function updatePickerRowLive(asgName, target, projected){
    if(!asgName) return;
    var bar=document.querySelector('[data-progbar="'+cssq(asgName)+'"]');
    var pend=document.querySelector('[data-progpend="'+cssq(asgName)+'"]');
    var txt=document.querySelector('[data-progtxt="'+cssq(asgName)+'"]');
    if(!bar && !txt) return;
    var uom=""; var conf=0; var savedPending=0;
    var list=ST.asgList||[];
    for(var i=0;i<list.length;i++){ if(list[i].name===asgName){ uom=list[i].uom||""; conf=list[i].fulfilled_qty||0; savedPending=list[i].pending_qty||0; break; } }
    if(!(target>0)){ return; }
    // projected = confirmed-elsewhere + what is being typed now (from refresh()).
    // confirmed solid stays at conf; overlay covers everything recorded incl. live typing.
    var pctConf=conf/target*100; if(pctConf>100) pctConf=100; if(pctConf<0) pctConf=0;
    var pctRec=projected/target*100; if(pctRec<0) pctRec=0;
    var shownRec=pctRec>100?100:pctRec;
    var pctPend=shownRec-pctConf; if(pctPend<0) pctPend=0;
    var rem=target-projected; if(rem<0) rem=0;
    var confCol = pctRec>=100?"#0a0a0a":"#3aa76d";
    if(bar){ bar.style.width=pctConf+"%"; bar.style.background=confCol; }
    if(pend){ pend.style.left=pctConf+"%"; pend.style.width=pctPend+"%"; }
    var livePending=projected-conf; if(livePending<0) livePending=0;
    if(txt){ txt.innerHTML=fmt(pctRec,0)+"% · "+fmt(rem)+" "+esc(uom)+" left"+(projected>target?" (over)":"")+(livePending>0?(' <span style="color:#3aa76d">('+fmt(livePending)+' pending)</span>'):''); txt.style.color = projected>target?"#a00":"#888"; }
  }
  function renderAsgList(){
    var box=el("ac-asg-list"); if(!box) return;
    var list=ST.asgList||[];
    var ffarm=(el("ac-f-farm")&&el("ac-f-farm").value)||"";
    var ftask=(el("ac-f-task")&&el("ac-f-task").value)||"";
    var fblock=((el("ac-f-block")&&el("ac-f-block").value)||"").trim().toLowerCase();
    var fband=(el("ac-f-pct")&&el("ac-f-pct").value)||"";
    var fq=((el("ac-f-q")&&el("ac-f-q").value)||"").trim().toLowerCase();
    var ffrom=(el("ac-f-from")&&el("ac-f-from").value)||"";
    var fto=(el("ac-f-to")&&el("ac-f-to").value)||"";
    var shown=0;
    var h="";
    list.forEach(function(a){
      if(ffarm && a.farm!==ffarm) return;
      if(ftask && a.task!==ftask) return;
      if(fblock && (lbl(a.block_section)||"").toLowerCase().indexOf(fblock)<0) return;
      if(fband && pctBand(a)!==fband) return;
      if(ffrom && a.to_date && a.to_date<ffrom) return;
      if(fto && a.from_date && a.from_date>fto) return;
      if(fq){
        var hay=((a.name||"")+" "+(a.farm||"")+" "+(a.block_section||"")+" "+(a.task||"")).toLowerCase();
        if(hay.indexOf(fq)<0) return;
      }
      shown++;
      var t=a.target_qty||0;
      var pConf=Math.min(a.pct||0,100);
      var pRec=Math.min(a.pct_recorded||a.pct||0,100);
      var pPend=Math.max(0,pRec-pConf);
      var rem = a.remaining_qty<0?0:a.remaining_qty;
      var confCol = pConf>=100?"#0a0a0a":"#3aa76d";
      var prog = t>0
        ? ('<div style="height:5px;background:#eee;border:1px solid #ddd;margin-top:4px;overflow:hidden;position:relative">'
             +'<div data-progbar="'+esc(a.name)+'" style="position:absolute;left:0;top:0;height:100%;width:'+pConf+'%;background:'+confCol+'"></div>'
             +'<div data-progpend="'+esc(a.name)+'" style="position:absolute;left:'+pConf+'%;top:0;height:100%;width:'+pPend+'%;background:#9fdcbf"></div>'
           +'</div>'
           +'<div data-progtxt="'+esc(a.name)+'" style="font-size:9px;color:#888;margin-top:2px">'+fmt(pRec,0)+'% · '+fmt(rem)+' '+esc(a.uom||"")+' left'+(a.pending_qty>0?(' <span style="color:#3aa76d">('+fmt(a.pending_qty)+' pending)</span>'):'')+'</div>')
        : '<div style="font-size:9px;color:#a00;margin-top:3px">no target set</div>';
      var review = (a.in_review>0)?('<span class="asg-rv">'+a.in_review+' in review</span>'):"";
      var sel = (ST.asg===a.name) ? " sel" : "";
      h+='<div class="asg-row'+sel+'" data-asg="'+esc(a.name)+'">'+
           '<div class="asg-main"><span class="asg-farm">'+esc(a.farm)+'</span> · '+esc(blocksLbl(a))+
           '<div class="asg-task">'+esc(a.task)+review+'</div>'+prog+'</div>'+
           '<div class="asg-ref">'+esc(a.name)+'</div></div>';
    });
    if(!shown){ h='<div class="empty" style="margin:0">No assignments match these filters.</div>'; }
    box.innerHTML=h;
    var cnt=el("ac-asg-count"); if(cnt) cnt.textContent=shown+" of "+list.length;
    box.querySelectorAll(".asg-row").forEach(function(row){
      row.onclick=function(){
        var name=row.getAttribute("data-asg");
        var sel=el("ac-asg"); if(sel) sel.value=name;
        onAsg(name);
        // reflect selection highlight
        box.querySelectorAll(".asg-row").forEach(function(r){ r.classList.remove("sel"); });
        row.classList.add("sel");
      };
    });
  }

  function onAsg(explicitAsg){
    // Accept an explicit assignment (from resume/edit) OR read from the select/`this`.
    // A resumed draft may belong to a plan that's filtered out of the picker options,
    // so we must NOT rely on the select holding a matching option.
    var val = (typeof explicitAsg === "string" && explicitAsg)
      ? explicitAsg
      : ((this && this.value) ? this.value : "");
    ST.asg=val; ST.cells={}; ST.detail=null;
    el("ac-grid").innerHTML='<div class="empty">Loading…</div>';
    if(!ST.asg){ el("ac-detail").style.display="none"; refresh(); return; }
    call({action:"act_detail",assignment:ST.asg}).then(function(d){
      var a=d.detail||{}; ST.detail=a;
      // if a live (in-review/confirmed) doc blocks entry, warn and lock
      renderDetail(a);
      // seed cells from any existing draft
      ST.cells = a.cells || {};
      renderGrid(a);
      refresh();
    });
  }

  function openActualForEdit(assignment, docname, stage){
    // Approver edits the entry grid for a pending doc, then approves from the tab.
    showTab("enter");
    var sel=el("ac-asg");
    if(sel){ sel.value=assignment; }
    ST.asg=assignment; ST.cells={}; ST.detail=null;
    ST._editingDoc=docname; ST._editingStage=stage;
    el("ac-grid").innerHTML='<div class="empty">Loading…</div>';
    call({action:"act_detail",assignment:assignment}).then(function(d){
      var a=d.detail||{}; ST.detail=a;
      renderDetail(a);
      ST.cells = a.cells || {};
      renderGrid(a);
      refresh();
      var banner=el("ac-editbanner");
      if(banner){
        banner.style.display="block";
        banner.innerHTML="Editing <b>"+esc(docname)+"</b> ("+esc(stage)+"). Adjust quantities and <b>Save Draft</b> to update, then approve it from the Approvals tab.";
      }
      toast("Loaded "+docname+" for editing");
    }).catch(function(e){ toast("Could not load for edit"); });
  }
  function renderDetail(a){
    var uom=a.uom||"";
    var over=a.over_target?true:false;
    var barPct=Math.min(a.pct||0,100);
    var barCol=over?"#0a0a0a":((a.pct||0)>=100?"#0a0a0a":"#3aa76d");
    var liveWarn = a.live_name ? ('<div style="margin-top:8px;font-size:11px;color:#a00;border:1px solid #e0b4b4;background:#fff6f6;padding:8px">An actuals record is already '+esc(a.live_state)+' ('+esc(a.live_name)+'). Wait for it to be confirmed or rejected before entering more.</div>') : "";
    var draftNote = a.draft_name ? ('<div style="margin-top:8px;font-size:11px;color:#555">Resuming draft <b>'+esc(a.draft_name)+'</b> — edit and re-save.</div>') : "";
    el("ac-detail").style.display="block";
    el("ac-detail").innerHTML=
      '<div class="dl"><span class="k">Farm</span><span class="v">'+esc(a.farm)+'</span></div>'+
      '<div class="dl"><span class="k">Block</span><span class="v">'+esc(blocksLbl(a))+'</span></div>'+
      '<div class="dl"><span class="k">Task</span><span class="v">'+esc(a.task)+'</span></div>'+
      '<div class="dl"><span class="k">Standard</span><span class="v">'+(a.daily_target>0?(fmt(a.daily_target)+" "+esc(uom||"unit")+"/day"):(a.task_kpi?esc(a.task_kpi):"—"))+'</span></div>'+
      '<div class="dl"><span class="k">Block Area</span><span class="v">'+(a.block_area>0?(fmt(a.block_area,2)+" Ha"):"—")+'</span></div>'+
      '<div class="dl"><span class="k">Rate</span><span class="v">KES '+fmt(a.rate,2)+' / '+esc(uom||"unit")+'</span></div>'+
      '<div class="dl"><span class="k">Period</span><span class="v">'+esc(a.from_date)+' → '+esc(a.to_date)+'</span></div>'+
      '<div class="dl"><span class="k">Target</span><span class="v big">'+fmt(a.target_qty)+' '+esc(uom)+'</span></div>'+
      '<div class="dl"><span class="k">Done so far</span><span class="v big">'+fmt(a.fulfilled_qty)+' '+esc(uom)+'</span></div>'+
      '<div class="dl"><span class="k">Remaining</span><span class="v big">'+(a.remaining_qty<0?"0":fmt(a.remaining_qty))+' '+esc(uom)+(over?' <span style="font-size:9px;font-weight:700;text-transform:uppercase;background:#0a0a0a;color:#fff;padding:1px 5px;border-radius:2px;margin-left:4px">over</span>':'')+'</span></div>'+
      '<div style="height:10px;background:#eee;border:1px solid #cfcfcf;margin-top:8px;overflow:hidden"><div style="height:100%;width:'+barPct+'%;background:'+barCol+'"></div></div>'+
      '<div style="font-size:10px;color:#777;margin-top:4px;text-align:right">'+fmt(a.pct,0)+'% fulfilled</div>'+
      draftNote + liveWarn +
      '<div id="ac-closebox" style="margin-top:14px"></div>'+
      '<div id="ac-cal" style="margin-top:14px"></div>';
    renderCalendar(a);
    loadCloseControl(a);
  }

  // ---- early close (both doc + plan; GM instant, FM/section head requests) ----
  function loadCloseControl(a){
    var box=el("ac-closebox"); if(!box) return;
    box.innerHTML="";
    if(!ST.asg) return;
    call({action:"act_close_roles", assignment:ST.asg}).then(function(d){
      var state=(d.close_state||"");
      var tgt=d.target_qty||0, done=d.fulfilled_qty||0;
      var pctTxt = tgt>0 ? (fmt(done)+" of "+fmt(tgt)+" done") : (fmt(done)+" done");
      if(state==="Closed"){
        box.innerHTML='<div style="border:1px solid #0a0a0a;background:#0a0a0a;color:#fff;padding:10px 12px;font-size:11px">'+
          '<b>Plan closed early.</b> '+esc(pctTxt)+'. '+(d.close_reason?('Reason: '+esc(d.close_reason)):'')+
          (d.closed_by?('<div style="opacity:.75;margin-top:3px">Closed by '+esc(d.closed_by)+'</div>'):'')+'</div>';
        return;
      }
      var head='<div style="font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#777;font-weight:700;margin-bottom:6px">Close this plan early</div>';
      if(state==="Close Requested"){
        var pend='<div style="border:1px solid #a06000;background:#fff8ef;padding:10px 12px;font-size:11px;color:#7a4a00">'+
          '<b>Close requested — awaiting GM.</b> '+esc(pctTxt)+'.'+
          (d.close_reason?('<div style="margin-top:3px">Reason: '+esc(d.close_reason)+'</div>'):'')+
          (d.close_requested_by?('<div style="opacity:.8;margin-top:2px">Requested by '+esc(d.close_requested_by)+'</div>'):'')+'</div>';
        // GM can confirm a pending request straight from here
        if(d.can_close_now){
          pend+='<button type="button" class="btn solid" id="ac-close-confirm" style="margin-top:10px">Approve &amp; close now</button>';
        }
        box.innerHTML=head+pend;
        var cbtn=el("ac-close-confirm");
        if(cbtn) cbtn.onclick=function(){ openCloseModal(true, d.close_reason||""); };
        return;
      }
      // no close state yet: GM -> instant; FM/section head -> request
      if(d.can_close_now){
        box.innerHTML=head+'<div style="font-size:11px;color:#555;margin-bottom:8px">'+esc(pctTxt)+'. As GM you can close immediately — any open draft is finalised and the remaining target is capped.</div>'+
          '<button type="button" class="btn solid" id="ac-close-now">Close plan now</button>';
        el("ac-close-now").onclick=function(){ openCloseModal(true, ""); };
      } else if(d.can_request){
        box.innerHTML=head+'<div style="font-size:11px;color:#555;margin-bottom:8px">'+esc(pctTxt)+'. Send a close request to the GM — entry stays open until they confirm.</div>'+
          '<button type="button" class="btn" id="ac-close-req">Request close</button>';
        el("ac-close-req").onclick=function(){ openCloseModal(false, ""); };
      } else {
        box.innerHTML="";  // no permission -> no control
      }
    }).catch(function(e){ box.innerHTML=""; });
  }
  function openCloseModal(isGm, presetReason){
    var m=el("ac-closemodal"); if(!m) return;
    ST._closeIsGm=isGm;
    el("ac-close-title").textContent = isGm ? "Close plan now" : "Request close";
    el("ac-close-desc").textContent = isGm
      ? "This finalises any open draft actuals to Confirmed and caps the plan (target kept for reporting). A reason is required."
      : "This sends a close request to the GM. Entry stays open until they confirm. A reason is required.";
    var ta=el("ac-close-reason"); ta.value=presetReason||"";
    el("ac-close-go").textContent = isGm ? "Close now" : "Send request";
    el("ac-close-go").disabled = !ta.value.trim();
    m.style.display="flex";
  }
  function closeCloseModal(){ var m=el("ac-closemodal"); if(m) m.style.display="none"; }
  function submitClose(){
    var reason=(el("ac-close-reason").value||"").trim();
    if(!reason){ toast("A reason is required"); return; }
    var act = ST._closeIsGm ? "act_close_confirm" : "act_close_request";
    el("ac-close-go").disabled=true;
    call({action:act, assignment:ST.asg, reason:reason}).then(function(d){
      if(d.error){ toast("Error: "+d.error); el("ac-close-go").disabled=false; return; }
      closeCloseModal();
      if(ST._closeIsGm){
        toast("Plan closed — "+fmt(d.finalised_actuals||0)+" actuals finalised · "+fmt(d.fulfilled_qty)+"/"+fmt(d.target_qty)+" done");
      } else {
        toast("Close request sent to GM");
      }
      // reload detail so the close box + grid reflect new state
      onAsg(ST.asg);
    }).catch(function(e){ toast("Close failed"); el("ac-close-go").disabled=false; });
  }
  function initCloseModal(){
    var x=el("ac-close-x"); if(x) x.onclick=closeCloseModal;
    var c=el("ac-close-cancel"); if(c) c.onclick=closeCloseModal;
    var g=el("ac-close-go"); if(g) g.onclick=submitClose;
    var ta=el("ac-close-reason"); if(ta) ta.oninput=function(){ el("ac-close-go").disabled=!ta.value.trim(); };
    var ov=el("ac-closemodal"); if(ov) ov.onclick=function(ev){ if(ev.target===ov) closeCloseModal(); };
  }

  function ck(emp,date){ return emp+"~"+date; }

  function renderGrid(a){
    var box=el("ac-grid");
    var workers=a.workers||[];
    var days=daysBetween(a.from_date,a.to_date);
    if(!workers.length){ box.innerHTML='<div class="empty">No workers on this assignment.</div>'; return; }
    // all workers released? (plan closed early -> everyone marked Left)
    var anyActive=false;
    for(var wi=0; wi<workers.length; wi++){ if((workers[wi].status||"Active")!=="Left"){ anyActive=true; break; } }
    if(!anyActive){
      var closedNote = a.close_state==="Closed" ? "This plan was closed early." : "All workers on this assignment have been released.";
      box.innerHTML='<div class="empty" style="line-height:1.6">'+
        '<b>'+esc(closedNote)+'</b><br>'+
        'All '+fmt(workers.length)+' worker'+(workers.length>1?"s":"")+' were released (marked left), so there is nothing to enter here.<br>'+
        '<span style="font-size:11px;color:#999">Their recorded work and pay are unchanged — view them in the plan’s lineage on the dashboard.</span>'+
        '</div>';
      return;
    }
    if(!days.length){ box.innerHTML='<div class="empty">This plan has no date range.</div>'; return; }
    var locked = a.live_name ? true : false;

    var h='<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:10px;color:#777;margin-bottom:6px">'+
          '<span><b style="color:#bbb">·</b> rest day / holiday</span>'+
          '<span><b style="color:#c2760c">L</b> approved leave (blocked)</span>'+
          '<span><b style="color:#d97706">○</b> pending leave (can still enter)</span>'+
          '</div>'+
          '<div style="overflow-x:auto"><table class="grid"><thead><tr>'+
          '<th class="wname">Worker</th>';
    days.forEach(function(iso){
      h+='<th class="dcol"><div class="dow">'+dowShort(iso)+'</div><div class="dnum">'+dnum(iso)+'</div><div class="dmon">'+monLabel(iso)+'</div></th>';
    });
    h+='<th class="trow">Total</th></tr></thead><tbody>';
    workers.forEach(function(w){
      var perm=!isTaskWorker(w.employment_type);
      var isLeft=(w.status||"Active")==="Left";
      var alabel=workerActiveLabel(w);
      var rowcls=(perm?"perm ":"")+(isLeft?"leftrow":"");
      // substitute affordance: only Active Task Workers on an unlocked grid are swappable
      var canSub = !perm && !isLeft && !locked;
      var subBtn = canSub ? ('<button type="button" class="subbtn" title="Substitute this worker" data-sub-emp="'+esc(w.employee)+'" data-sub-name="'+esc(w.employee_name||w.employee)+'">swap</button>') : '';
      h+='<tr class="'+rowcls.trim()+'"><td class="wname"><span class="nm">'+esc(w.employee_name||w.employee)+'</span>'+(perm?'<span class="mini">salaried</span>':'')+(isLeft?'<span class="mini left">left</span>':'')+(w.start_date&&!isLeft?'<span class="mini repl">replacement</span>':'')+subBtn+(alabel?'<div style="font-size:8px;color:#999;margin-top:1px">'+esc(alabel)+'</div>':'')+'</td>';
      days.forEach(function(iso){
        var active=cellActive(w,iso);
        var isOff=offDay(w,iso);
        var isLeave=leaveDay(w,iso);
        var isLeavePend=leavePendingDay(w,iso);
        var val=ST.cells[ck(w.employee,iso)];
        var cellLocked = locked || !active;
        if(!active){
          if(isLeave){
            h+='<td class="dcell leaveday" title="approved leave">L</td>';
          } else if(isOff){
            h+='<td class="dcell offday" title="rest day / holiday">·</td>';
          } else {
            h+='<td class="dcell closed" title="not active this day"></td>';
          }
        } else {
          var pendCls = isLeavePend ? " leavepend" : "";
          var pendTitle = isLeavePend ? ' title="pending leave request — not yet approved"' : '';
          h+='<td class="dcell'+pendCls+'"'+pendTitle+'><input type="number" min="0" step="any" '+(cellLocked?"disabled":"")+' data-emp="'+esc(w.employee)+'" data-date="'+iso+'" data-et="'+esc(w.employment_type||"")+'" value="'+(val!=null&&val!==""?esc(val):"")+'" placeholder="0">'+(isLeavePend?'<span class="lp-dot" title="pending leave">○</span>':'')+'</td>';
        }
      });
      h+='<td class="trow" data-wtot="'+esc(w.employee)+'">0</td></tr>';
    });
    h+='</tbody><tfoot><tr><td class="wname">Day total</td>';
    days.forEach(function(iso){ h+='<td class="dtot" data-dtot="'+iso+'">0</td>'; });
    h+='<td class="trow" data-grand>0</td></tr></tfoot></table></div>';
    box.innerHTML=h;

    box.querySelectorAll("input[data-emp]").forEach(function(inp){
      inp.oninput=function(){
        var key=ck(inp.getAttribute("data-emp"), inp.getAttribute("data-date"));
        var v=parseFloat(inp.value);
        if(isNaN(v)||v<=0){ delete ST.cells[key]; } else { ST.cells[key]=v; }
        recompute(a);
      };
    });
    // wire substitute buttons
    box.querySelectorAll("[data-sub-emp]").forEach(function(btn){
      btn.onclick=function(ev){
        ev.stopPropagation();
        openSubModal(btn.getAttribute("data-sub-emp"), btn.getAttribute("data-sub-name"));
      };
    });
    recompute(a);
  }

  function recompute(a){
    var rate=a.rate||0;
    var workers=a.workers||[];
    var days=daysBetween(a.from_date,a.to_date);
    var grand=0, grandPay=0, payPeople={}, people={};
    var twNow=0, salNow=0;
    // per-worker + per-day totals
    var wtot={}, dtot={};
    workers.forEach(function(w){ wtot[w.employee]=0; });
    days.forEach(function(iso){ dtot[iso]=0; });
    workers.forEach(function(w){
      var isTW=isTaskWorker(w.employment_type);
      days.forEach(function(iso){
        if(!cellActive(w,iso)) return;   // skip cells outside this worker's active window
        var q=ST.cells[ck(w.employee,iso)]||0;
        if(q>0){
          wtot[w.employee]+=q; dtot[iso]+=q; grand+=q;
          people[w.employee]=1;
          if(isTW){ grandPay+=q*rate; payPeople[w.employee]=1; twNow+=q; }
          else { salNow+=q; }
        }
      });
    });
    // write cells
    var box=el("ac-grid");
    workers.forEach(function(w){
      var c=box.querySelector('[data-wtot="'+cssq(w.employee)+'"]');
      if(c){ var isTW=isTaskWorker(w.employment_type); c.textContent=fmt(wtot[w.employee])+(isTW&&wtot[w.employee]>0?(" · "+fmt(wtot[w.employee]*rate)):""); }
    });
    days.forEach(function(iso){
      var c=box.querySelector('[data-dtot="'+iso+'"]');
      if(c) c.textContent=fmt(dtot[iso]);
    });
    var g=box.querySelector('[data-grand]'); if(g) g.textContent=fmt(grand);
    // KPIs
    el("o-people").textContent=Object.keys(people).length;
    el("o-paid").textContent=Object.keys(payPeople).length;
    el("o-pay").textContent = grandPay>0?fmt(grandPay):"—";
    // remaining preview: target - (already-confirmed-elsewhere + this draft)
    var target=a.target_qty||0;
    var alreadyDone=(a.done!=null?a.done:(a.fulfilled_qty||0));  // qty confirmed on OTHER docs for this plan
    var projected=alreadyDone+grand;
    var projRemain=target-projected;
    var over=target>0 && projected>target;
    var noTarget=!(target>0);
    var salariedOnly = (twNow<=0) && (salNow>0);
    var balanceLine = "";
    if(target>0){
      balanceLine = ' · <span style="color:#555">task-worker <b>'+fmt(twNow)+'</b> + salaried <b>'+fmt(salNow)+'</b>'+
        ' · balance vs target <b>'+(projRemain<0?"0":fmt(projRemain))+' '+esc(a.uom||"")+'</b></span>';
    }
    el("ac-varnote").innerHTML="This entry adds <b>"+fmt(grand)+"</b> "+esc(a.uom||"")+" · projected remaining <b>"+(projRemain<0?"0":fmt(projRemain))+"</b>"+(over?' <span style="color:#a00;font-weight:700">⚠ exceeds target — reduce by '+fmt(projected-target)+' to submit</span>':'')+(noTarget?' <span style="color:#a00;font-weight:700">⚠ plan has no target set — cannot submit</span>':'')+" · payment <b>KES "+fmt(grandPay)+"</b>"+balanceLine+(salariedOnly&&projRemain>0?' <span style="color:#0a7a43;font-weight:600">✓ salaried — balance documented, no need to finish target</span>':'');
    // LIVE picker row: reflect the qty being typed (not yet saved) on the selected assignment's bar + "left"
    updatePickerRowLive(ST.asg, target, projected);
    var locked=a.live_name?true:false;
    // "completed" = plan reaches 100% of target OR the crew is salaried-only (paid fixed, not qty x rate)
    var complete = (target>0 && Math.abs(projected-target) < 0.0001) || (salariedOnly && !noTarget);
    // DRAFT: allowed whenever there is qty entered, target exists, not over, not locked
    var draftReady = ST.asg && grand>0 && !locked && !over && !noTarget;
    // SUBMIT: when plan qty is completed (100%) OR salaried-only (documented balance)
    var submitReady = draftReady && complete;
    el("b-acdraft").disabled=!draftReady;
    el("b-acsubmit").disabled=!submitReady;
    ST._over=over; ST._noTarget=noTarget; ST._projRemain=projRemain; ST._complete=complete;
    // submit hint: show how much more is needed to complete before submit unlocks
    var hint=el("ac-submithint");
    if(hint){
      if(noTarget){ hint.innerHTML=""; }
      else if(over){ hint.innerHTML=""; }
      else if(!complete){
        var need = target - projected;
        hint.innerHTML = '<span style="color:#a06000">Submit unlocks when the target is completed — '+fmt(projected)+' of '+fmt(target)+' '+esc(a.uom||"")+' done, enter <b>'+fmt(need)+'</b> more (you can Save Draft meanwhile).</span>';
      } else if(salariedOnly && projRemain>0){
        hint.innerHTML = '<span style="color:#0a7a43;font-weight:600">✓ Salaried crew — ready to submit. Balance of '+fmt(projRemain)+' '+esc(a.uom||"")+' will be documented, not required.</span>';
      } else {
        hint.innerHTML = '<span style="color:#0a7a43;font-weight:600">✓ Target completed — ready to submit for approval.</span>';
      }
    }
  }
  function cssq(s){ return (s||"").replace(/"/g,'\\\"'); }

  function doSubmit(submitNow){
    var payload=[];
    for(var key in ST.cells){
      if(ST.cells[key]>0){ payload.push(key+"~"+ST.cells[key]); }
    }
    if(!payload.length){ toast("Enter at least one quantity"); return; }
    var args={ action:"act_submit", assignment:ST.asg, rows:payload.join("|") };
    if(submitNow) args.submit_now=1;
    if(ST._editingDoc){ args.edit_doc=ST._editingDoc; }  // approver updating a pending doc in place
    el("b-acdraft").disabled=true; el("b-acsubmit").disabled=true;
    call(args).then(function(d){
      if(d.error){ toast("Error: "+d.error); refresh(); return; }
      if(d.submit_blocked){ toast(d.submit_blocked); }
      else if(ST._editingDoc){ toast("Updated "+d.name+" · "+fmt(d.total_actual_qty)+" "+(ST.detail&&ST.detail.uom?ST.detail.uom:"")); var bn=el("ac-editbanner"); if(bn){bn.style.display="none";} ST._editingDoc=null; ST._editingStage=null; }
      else toast((submitNow?"Submitted ":"Draft saved ")+d.name+" · "+fmt(d.total_actual_qty)+" "+(ST.detail&&ST.detail.uom?ST.detail.uom:"")+" · KES "+fmt(d.total_payment));
      if(submitNow && !d.submit_blocked){
        ST.asg=null; ST.cells={}; ST.detail=null;
        el("ac-asg").value=""; el("ac-detail").style.display="none";
        el("ac-grid").innerHTML='<div class="empty">Pick an assignment to load the grid.</div>';
        el("ac-varnote").textContent="";
        refresh(); loadAssignments();
      } else {
        // stay on the draft; reload detail so remaining/calendar refresh
        onAsg(ST.asg);
      }
    }).catch(function(e){ toast("Failed to save"); refresh(); });
  }

  function refresh(){
    if(!ST.detail){ el("o-people").textContent="0"; el("o-paid").textContent="0"; el("o-pay").textContent="—"; el("ac-varnote").textContent=""; el("b-acdraft").disabled=true; el("b-acsubmit").disabled=true; }
  }

  // ---- substitution modal ----
  function initSubModal(){
    var close=el("ac-sub-close"); if(close) close.onclick=closeSubModal;
    var cancel=el("ac-sub-cancel"); if(cancel) cancel.onclick=closeSubModal;
    var confirm=el("ac-sub-confirm"); if(confirm) confirm.onclick=confirmSub;
    var overlay=el("ac-submodal");
    if(overlay){ overlay.onclick=function(ev){ if(ev.target===overlay) closeSubModal(); }; }
    var dateInp=el("ac-sub-date");
    if(dateInp){ dateInp.onchange=syncStartHint; }
  }
  function closeSubModal(){ var m=el("ac-submodal"); if(m) m.style.display="none"; ST._subEmp=null; ST._subName=null; }
  function syncStartHint(){
    var d=el("ac-sub-date"); var s=el("ac-sub-starthint");
    if(d && s){ s.textContent = d.value ? ("Replacement starts "+d.value+" (same day).") : ""; }
  }
  function openSubModal(emp, name){
    if(!ST.asg){ toast("Load an assignment first"); return; }
    ST._subEmp=emp; ST._subName=name;
    var m=el("ac-submodal"); if(!m) return;
    el("ac-sub-outname").textContent=name||emp;
    // default changeover date = today, clamped to the assignment period
    var today=new Date();
    var iso=today.getFullYear()+"-"+pad(today.getMonth()+1)+"-"+pad(today.getDate());
    var a=ST.detail||{};
    if(a.from_date && iso < a.from_date) iso=a.from_date;
    if(a.to_date && iso > a.to_date) iso=a.to_date;
    var dinp=el("ac-sub-date");
    dinp.value=iso;
    if(a.from_date) dinp.min=a.from_date;
    if(a.to_date) dinp.max=a.to_date;
    syncStartHint();
    // load candidates (server already excludes on-roster + busy-elsewhere)
    var sel=el("ac-sub-rep");
    sel.innerHTML='<option value="">— loading candidates… —</option>';
    el("ac-sub-confirm").disabled=true;
    m.style.display="flex";
    call({action:"a_sub_candidates",assignment:ST.asg}).then(function(d){
      var cands=d.candidates||[];
      if(!cands.length){
        sel.innerHTML='<option value="">— no eligible replacements —</option>';
        el("ac-sub-note").textContent="No available Task Workers on this farm (all are already assigned somewhere overlapping this period).";
        return;
      }
      sel.innerHTML='<option value="">— select replacement —</option>';
      cands.forEach(function(c){
        var o=document.createElement("option"); o.value=c.name; o.textContent=c.employee_name||c.name; sel.appendChild(o);
      });
      el("ac-sub-note").textContent=cands.length+" eligible Task Worker"+(cands.length===1?"":"s")+" (not on this plan, free for the period).";
      sel.onchange=function(){ el("ac-sub-confirm").disabled=!sel.value; };
    }).catch(function(e){
      sel.innerHTML='<option value="">— could not load —</option>';
      el("ac-sub-note").textContent="Failed to load candidates.";
    });
  }
  function confirmSub(){
    var rep=el("ac-sub-rep").value;
    var date=el("ac-sub-date").value;
    if(!ST._subEmp || !rep || !date){ toast("Pick a replacement and a changeover date"); return; }
    // same-day handoff: outgoing Left on `date`, replacement starts on the same `date`
    el("ac-sub-confirm").disabled=true;
    call({action:"a_substitute", assignment:ST.asg, outgoing:ST._subEmp, replacement:rep, left_date:date, start_date:date}).then(function(d){
      if(d.error){ toast("Error: "+d.error); el("ac-sub-confirm").disabled=false; return; }
      toast("Swapped — "+(ST._subName||ST._subEmp)+" out, replacement in from "+date+" · active now "+fmt(d.active_count));
      closeSubModal();
      // reload the grid: outgoing days close after `date`, replacement opens from `date`,
      // and any quantities already entered for the outgoing worker are preserved (server never touched actuals rows)
      onAsg(ST.asg);
    }).catch(function(e){ toast("Substitution failed"); el("ac-sub-confirm").disabled=false; });
  }

  // ---- calendar (confirmed days) ----
  function renderCalendar(a){
    var box=el("ac-cal"); if(!box) return;
    var from=a.from_date, to=a.to_date;
    if(!from||!to){ box.innerHTML=""; return; }
    var days=a.days||{}; var uom=a.uom||"";
    var start=new Date(from+"T00:00:00"), end=new Date(to+"T00:00:00");
    var totQ=0, totP=0, act=0, maxQ=0, best=null;
    Object.keys(days).forEach(function(k){
      var q=cnum(days[k].qty); totQ+=q; totP+=cnum(days[k].pay); act+=1;
      if(q>maxQ){ maxQ=q; best=k; }
    });
    var months="";
    var cur=new Date(start.getFullYear(),start.getMonth(),1);
    var last=new Date(end.getFullYear(),end.getMonth(),1);
    while(cur<=last){ months+=calMonth(cur.getFullYear(),cur.getMonth(),start,end,days,maxQ); cur=new Date(cur.getFullYear(),cur.getMonth()+1,1); }
    var head='<div class="cal-h">Daily activity</div>'+
      '<div class="cal-sum">'+
        '<span><b>'+act+'</b> confirmed day'+(act===1?'':'s')+'</span>'+
        '<span><b>'+fmt(totQ)+'</b> '+esc(uom)+'</span>'+
        '<span><b>KES '+fmt(totP)+'</b> paid</span>'+
        (act>0?('<span><b>'+fmt(totQ/act,1)+'</b> '+esc(uom)+'/day avg</span>'):'')+
        (best?('<span>best day <b>'+esc(best)+'</b> · '+fmt(maxQ)+' '+esc(uom)+'</span>'):'')+
      '</div>'+
      '<div class="cal-hint">Click any day in the period for details — confirmed output, crew availability and pay.</div>';
    box.innerHTML=head+months+'<div id="ac-daypanel"></div>';
    box.querySelectorAll("[data-cald]").forEach(function(c){
      c.onclick=function(){
        box.querySelectorAll("[data-cald]").forEach(function(x){ x.classList.remove("cal-sel"); });
        c.classList.add("cal-sel");
        renderDayPanel(a, c.getAttribute("data-cald"));
      };
    });
  }
  function calMonth(y,m,start,end,days,maxQ){
    var mn=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    var first=new Date(y,m,1), dow=first.getDay(), dim=new Date(y,m+1,0).getDate();
    var tn=new Date();
    var tISO=tn.getFullYear()+"-"+pad(tn.getMonth()+1)+"-"+pad(tn.getDate());
    var h='<div class="cal-m"><div class="cal-mt">'+mn[m]+' '+y+'</div><div class="cal-g">';
    ["S","M","T","W","T","F","S"].forEach(function(d){ h+='<div class="cal-dw">'+d+'</div>'; });
    for(var b=0;b<dow;b++) h+='<div></div>';
    for(var day=1;day<=dim;day++){
      var dt=new Date(y,m,day);
      var iso=dt.getFullYear()+"-"+pad(dt.getMonth()+1)+"-"+pad(day);
      var inP=(dt>=cstrip(start)&&dt<=cstrip(end));
      var rec=days[iso];
      var today=(iso===tISO)?" cal-today":"";
      if(!inP){ h+='<div class="cal-d out"><span class="cal-n">'+day+'</span></div>'; }
      else if(rec&&cnum(rec.qty)>0){
        var tier=maxQ>0?Math.min(4,Math.max(1,Math.ceil(cnum(rec.qty)/maxQ*4))):1;
        h+='<div class="cal-d has q'+tier+today+'" data-cald="'+iso+'"><span class="cal-n">'+day+'</span><span class="cal-q">'+fmt(rec.qty)+'</span><span class="cal-i">'+fmt(rec.workers)+'w · '+ckk(rec.pay)+'</span></div>';
      }
      else { h+='<div class="cal-d'+today+'" data-cald="'+iso+'"><span class="cal-n">'+day+'</span></div>'; }
    }
    return h+'</div></div>';
  }
  function renderDayPanel(a, iso){
    var p=el("ac-daypanel"); if(!p) return;
    var rec=(a.days||{})[iso]||null;
    var uom=a.uom||"";
    var dhead=dowShort(iso)+", "+dnum(iso)+" "+monLabel(iso)+" "+iso.slice(0,4);
    var h='<div class="dv">'+
      '<div class="dv-h"><b>'+esc(dhead)+'</b><span>'+esc(a.task||"")+' · '+esc(a.farm||"")+' · '+esc(blocksLbl(a))+'</span>'+
      '<a class="dv-desk" target="_blank" href="/app/work-management-actuals?assignment='+encodeURIComponent(ST.asg||"")+'">Open docs ↗</a></div>';
    h+='<div class="dv-figs">'+
      '<div class="dv-fig"><span>Confirmed</span><b>'+(rec?fmt(rec.qty):0)+' '+esc(uom)+'</b></div>'+
      '<div class="dv-fig"><span>Workers paid</span><b>'+(rec?fmt(rec.workers):0)+'</b></div>'+
      '<div class="dv-fig"><span>Pay</span><b>KES '+(rec?fmt(rec.pay):0)+'</b></div>'+
      '<div class="dv-fig"><span>Documents</span><b>'+(rec?fmt(rec.entries||0):0)+'</b></div>'+
    '</div>';
    var confRows=(a.day_workers||{})[iso]||[];
    var confMap={}; confRows.forEach(function(c){ confMap[c.employee]=c; });
    var workers=a.workers||[];
    if(workers.length || confRows.length){
      var rows="", anyDraft=false, anyConf=confRows.length>0, seen={};
      workers.forEach(function(w){
        seen[w.employee]=1;
        var stTxt, stCls;
        if(w.start_date && iso<w.start_date){ stTxt="not started"; stCls="mut"; }
        else if((w.status||"")==="Left" && w.left_date && iso>w.left_date){ stTxt="left"; stCls="bad"; }
        else if(leaveDay(w,iso)){ stTxt="approved leave"; stCls="warn"; }
        else if(offDay(w,iso)){ stTxt="rest day"; stCls="mut"; }
        else if(leavePendingDay(w,iso)){ stTxt="pending leave"; stCls="warn"; }
        else { stTxt="available"; stCls="ok"; }
        var q=ST.cells[ck(w.employee,iso)];
        if(q>0) anyDraft=true;
        var cf=confMap[w.employee];
        var cq=cf?cf.qty:0;
        var isTW=isTaskWorker(w.employment_type);
        rows+='<tr><td>'+esc(w.employee_name||w.employee)+(isTW?'':' <span class="mini">salaried</span>')+'</td>'+
          '<td><span class="dv-st '+stCls+'">'+stTxt+'</span></td>'+
          '<td class="n">'+(cq>0?fmt(cq):"—")+'</td>'+
          '<td class="n">'+(cq>0&&isTW?fmt(cq*(a.rate||0)):"—")+'</td>'+
          '<td class="n">'+(q>0?fmt(q):"—")+'</td></tr>';
      });
      confRows.forEach(function(c){
        if(seen[c.employee]) return;
        var isTW=isTaskWorker(c.et);
        rows+='<tr><td>'+esc(c.name||c.employee)+(isTW?'':' <span class="mini">salaried</span>')+' <span class="mini">off roster</span></td>'+
          '<td><span class="dv-st mut">worked, since replaced</span></td>'+
          '<td class="n">'+fmt(c.qty)+'</td>'+
          '<td class="n">'+(isTW?fmt(c.qty*(a.rate||0)):"—")+'</td>'+
          '<td class="n">—</td></tr>';
      });
      h+='<div class="dv-sec">Crew on this day'+(anyConf?' — confirmed output per worker':'')+(anyDraft?' · includes unsaved draft entries':'')+'</div>'+
        '<div class="dv-tscroll"><table class="dv-t"><thead><tr><th>Worker</th><th>Status</th><th class="n">Confirmed ('+esc(uom)+')</th><th class="n">Confirmed pay KES</th><th class="n">This draft ('+esc(uom)+')</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
    }
    if(!rec){ h+='<div class="dv-note">No confirmed actuals on this day yet — highlighted (green) days carry confirmed output.</div>'; }
    h+='</div>';
    p.innerHTML=h;
    if(p.scrollIntoView) p.scrollIntoView({behavior:"smooth",block:"nearest"});
  }
  function cstrip(d){ return new Date(d.getFullYear(),d.getMonth(),d.getDate()); }
  function cnum(n){ n=parseFloat(n); return isNaN(n)?0:n; }
  function ckk(n){ n=cnum(n); if(n>=1000) return (n/1000).toLocaleString("en-KE",{maximumFractionDigits:1})+"k"; return fmt(n); }

  // ---- My Actuals + approvals ----
  function stateTag(s){
    if(s==="Confirmed") return '<span class="tag confirmed">Confirmed</span>';
    if(s==="Pending HR Head") return '<span class="tag hr">HR</span>';
    if(s==="Pending GM") return '<span class="tag gm">GM</span>';
    if(s==="Rejected") return '<span class="tag rej">Rejected</span>';
    return '<span class="tag">'+esc(s||"Draft")+'</span>';
  }
  function loadMine(){
    var b=el("acmine-body"); b.className="loading"; b.innerHTML="Loading…";
    call({action:"act_my"}).then(function(d){
      var rows=d.actuals||[];
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">No actuals yet.</div>'; return; }
      var sts={}; rows.forEach(function(r){ if(r.workflow_state) sts[r.workflow_state]=1; });
      b.className="";
      b.innerHTML='<div class="note" style="margin-bottom:8px">Draft or rejected records are editable — click a row to resume entering day by day.</div>'
        + fbar(rows,{dates:true,statuses:Object.keys(sts).sort(),ph:"Search ref, farm, task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:r.workflow_state||"", date:isodate(r.entry_date),
                hay:((r.name||"")+" "+(r.farm||"")+" "+(r.task||"")).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Date</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">Paid</th><th class="n">Payment KES</th><th>Status</th><th></th></tr></thead><tbody>';
        list.forEach(function(r, i){
          var editable = (r.workflow_state==="Draft" || r.workflow_state==="Rejected");
          var editcell = editable ? '<span class="editlink" data-asg="'+esc(r.assignment)+'">Edit →</span>' : '';
          h+='<tr data-x="'+i+'"><td>'+esc(r.name)+'</td><td>'+esc(isodate(r.entry_date)||"—")+'</td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td class="n m">'+fmt(r.total_actual_qty)+'</td><td class="n m">'+fmt(r.payroll_people)+'</td><td class="n m">'+fmt(r.total_payment)+'</td><td>'+stateTag(r.workflow_state)+'</td><td>'+editcell+'</td></tr>';
        });
        body.innerHTML=h+'</tbody></table>';
        body.querySelectorAll(".editlink").forEach(function(elk){
          elk.style.cursor="pointer";
          elk.onclick=function(ev){ ev.stopPropagation(); var asg=elk.getAttribute("data-asg"); if(asg) resumeActual(asg); };
        });
        wireExpand(body, 9, function(i){
          var r=list[i];
          return '<div class="dv-h"><b>'+esc(r.name)+'</b><span>'+esc(r.farm||"")+' · '+esc(r.task||"")+'</span></div>'+
            rowFigs([["Entry date",esc(isodate(r.entry_date))],["Quantity",fmt(r.total_actual_qty)],["People (all)",fmt(r.actual_people)],["Paid workers",fmt(r.payroll_people)],["Payment KES",fmt(r.total_payment)],["Cost variance",r.cost_variance!=null?fmt(r.cost_variance):""],["Status",esc(r.workflow_state)]])+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">'+deskA("Open actuals doc","work-management-actuals",r.name)+deskA("Open assignment","work-management-assigner",r.assignment)+'</div>';
        });
      });
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load.</div>'; });
  }
  function loadRejected(){
    var b=el("acrej-body"); if(!b) return; b.className="loading"; b.innerHTML="Loading…";
    call({action:"act_my"}).then(function(d){
      var rows=(d.actuals||[]).filter(function(r){ return r.workflow_state==="Rejected"; });
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">Nothing rejected — you’re all clear.</div>'; return; }
      b.className="";
      b.innerHTML='<div class="note" style="margin-bottom:8px">These actuals were rejected. Click <b>Edit</b> to adjust the daily quantities and resubmit for approval.</div>'
        + fbar(rows,{dates:true,ph:"Search ref, farm, task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:"", date:isodate(r.entry_date),
                hay:((r.name||"")+" "+(r.farm||"")+" "+(r.task||"")).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Date</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">Paid</th><th class="n">Payment KES</th><th>Status</th><th></th></tr></thead><tbody>';
        list.forEach(function(r, i){
          h+='<tr data-x="'+i+'"><td>'+esc(r.name)+'</td><td>'+esc(isodate(r.entry_date)||"—")+'</td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td class="n m">'+fmt(r.total_actual_qty)+'</td><td class="n m">'+fmt(r.payroll_people)+'</td><td class="n m">'+fmt(r.total_payment)+'</td><td>'+stateTag(r.workflow_state)+'</td><td><span class="editlink" data-asg="'+esc(r.assignment)+'">Edit &amp; resubmit →</span></td></tr>';
        });
        body.innerHTML=h+'</tbody></table>';
        body.querySelectorAll(".editlink").forEach(function(elk){
          elk.style.cursor="pointer";
          elk.onclick=function(ev){ ev.stopPropagation(); resumeActual(elk.getAttribute("data-asg")); };
        });
        wireExpand(body, 9, function(i){
          var r=list[i];
          return '<div class="dv-h"><b>'+esc(r.name)+'</b><span>'+esc(r.farm||"")+' · '+esc(r.task||"")+'</span></div>'+
            rowFigs([["Entry date",esc(isodate(r.entry_date))],["Quantity",fmt(r.total_actual_qty)],["People (all)",fmt(r.actual_people)],["Paid workers",fmt(r.payroll_people)],["Payment KES",fmt(r.total_payment)],["Status",esc(r.workflow_state)]])+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">'+deskA("Open actuals doc","work-management-actuals",r.name)+deskA("Open assignment","work-management-assigner",r.assignment)+'</div>';
        });
      });
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load.</div>'; });
  }
  function loadCloseRequests(){
    var b=el("acappr-body"); if(!b) return; b.className="loading"; b.innerHTML="Loading…";
    call({action:"act_close_pending"}).then(function(d){
      if(d.not_gm){ b.className=""; b.innerHTML='<div class="empty">Only the General Manager sees close requests.</div>'; return; }
      var rows=d.pending||[];
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">No close requests awaiting you.</div>'; return; }
      b.className="";
      b.innerHTML='<div class="note" style="margin-bottom:8px">A section head / farm manager has asked to close these plans early. Approving confirms open actuals, caps the plan (target kept), and frees the workers.</div>'
        + fbar(rows,{dates:true,ph:"Search plan, farm, block, task…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:"", date:isodate(r.custom_close_request_date),
                hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.custom_close_requested_by||"")).toLowerCase()};
      }, function(body, list){
      if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
      var h='<table><thead><tr><th>Plan</th><th>Farm</th><th>Block</th><th>Task</th><th class="n">Target</th><th class="n">Done</th><th class="n">Remaining</th><th>Requested by</th><th>Reason</th><th>Action</th></tr></thead><tbody>';
      list.forEach(function(r, i){
        h+='<tr data-x="'+i+'"><td>'+esc(r.name)+'</td><td>'+esc(r.farm)+'</td><td>'+esc(lbl(r.block_section))+'</td><td>'+esc(r.task)+'</td>'+
           '<td class="n m">'+fmt(r.quantity)+' '+esc(r.uom||"")+'</td>'+
           '<td class="n m">'+fmt(r.fulfilled_qty)+'</td>'+
           '<td class="n m">'+fmt(r.remaining_qty)+'</td>'+
           '<td>'+esc(r.custom_close_requested_by||"—")+'<div style="font-size:9px;color:#94a3b8">'+esc(r.custom_close_request_date||"")+'</div></td>'+
           '<td style="max-width:220px;white-space:normal">'+esc(r.custom_close_reason||"—")+'</td>'+
           '<td><div class="ib"><button class="btn solid" data-cl="'+esc(r.name)+'">Approve &amp; close</button></div></td></tr>';
      });
      body.innerHTML=h+'</tbody></table>';
      wireExpand(body, 10, function(i){
        var r=list[i];
        return '<div class="dv-h"><b>'+esc(r.name)+'</b><span>'+esc(r.farm||"")+' · '+esc(r.task||"")+' · '+esc(lbl(r.block_section))+'</span></div>'+
          rowFigs([["Target",fmt(r.quantity)+' '+esc(r.uom||"")],["Done",fmt(r.fulfilled_qty)],["Remaining",fmt(r.remaining_qty)],["Requested by",esc(r.custom_close_requested_by||"—")],["Requested on",esc(r.custom_close_request_date||"—")]])+
          (r.custom_close_reason?('<div class="dv-note">Reason: '+esc(r.custom_close_reason)+'</div>'):'')+
          '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px">'+deskA("Open plan","work-management-planner",r.name)+'</div>';
      });
      body.querySelectorAll("[data-cl]").forEach(function(btn){
        btn.onclick=function(){
          var plan=btn.getAttribute("data-cl");
          btn.disabled=true; btn.textContent="Closing…";
          call({action:"act_close_confirm", plan:plan}).then(function(d){
            if(d.error){ toast("Error: "+d.error); btn.disabled=false; btn.textContent="Approve & close"; return; }
            toast("Closed "+plan+" · "+fmt(d.workers_released)+" workers freed");
            loadCloseRequests();
          }).catch(function(e){ toast("Close failed"); btn.disabled=false; btn.textContent="Approve & close"; });
        };
      });
      });
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load close requests.</div>'; });
  }
  function loadStage(bodyId, stage, approveAction){
    var b=el(bodyId); b.className="loading"; b.innerHTML="Loading…";
    call({action:"act_pending",stage:stage}).then(function(d){
      var rows=d.pending||[];
      if(!rows.length){ b.className=""; b.innerHTML='<div class="empty">Nothing at this stage.</div>'; return; }
      b.className="";
      b.innerHTML=fbar(rows,{dates:true,ph:"Search ref, farm, task, entered by…"});
      fwire(b, rows, function(r){
        return {farm:r.farm||"", status:"", date:isodate(r.entry_date),
                hay:((r.name||"")+" "+(r.farm||"")+" "+(r.block_section||"")+" "+(r.task||"")+" "+(r.entered_by||"")).toLowerCase()};
      }, function(body, list){
        if(!list.length){ body.innerHTML='<div class="empty">Nothing matches these filters.</div>'; return; }
        var h='<table><thead><tr><th>Ref</th><th>Date</th><th>Farm</th><th>Task</th><th class="n">Qty</th><th class="n">Paid</th><th class="n">Payment KES</th><th>By</th><th>Action</th></tr></thead><tbody>';
        list.forEach(function(r, i){
          h+='<tr data-x="'+i+'"><td>'+esc(r.name)+'</td><td>'+esc(isodate(r.entry_date)||"—")+'</td><td>'+esc(r.farm)+'</td><td>'+esc(r.task)+'</td><td class="n m">'+fmt(r.total_actual_qty!=null?r.total_actual_qty:r.actual_people)+'</td><td class="n m">'+fmt(r.payroll_people)+'</td><td class="n m">'+fmt(r.total_payment)+'</td><td>'+esc((r.entered_by||"").split("@")[0])+'</td><td><div class="ib"><button class="btn" data-edit="'+esc(r.assignment||"")+'" data-doc="'+esc(r.name)+'">Edit</button><button class="btn solid" data-app="'+esc(r.name)+'">Approve</button><button class="btn" data-rej="'+esc(r.name)+'">Reject</button></div></td></tr>';
        });
        body.innerHTML=h+'</tbody></table>';
        wireExpand(body, 9, function(i){
          var r=list[i];
          return '<div class="dv-h"><b>'+esc(r.name)+'</b><span>'+esc(r.farm||"")+' · '+esc(r.task||"")+(r.block_section?(' · '+esc(lbl(r.block_section))):'')+'</span></div>'+
            rowFigs([["Entry date",esc(isodate(r.entry_date))],["Quantity",fmt(r.total_actual_qty)],["People (all)",fmt(r.actual_people)],["Planned people",fmt(r.planned_people)],["Paid workers",fmt(r.payroll_people)],["Payment KES",fmt(r.total_payment)],["Planned cost",fmt(r.planned_cost)],["Cost variance",r.cost_variance!=null?fmt(r.cost_variance):""],["Entered by",esc((r.entered_by||"").split("@")[0])]])+
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">'+deskA("Open actuals doc","work-management-actuals",r.name)+deskA("Open assignment","work-management-assigner",r.assignment)+'</div>';
        });
        body.querySelectorAll("[data-app]").forEach(function(btn){ btn.onclick=function(){ act(approveAction, btn.getAttribute("data-app"), bodyId, stage, approveAction); }; });
        body.querySelectorAll("[data-rej]").forEach(function(btn){ btn.onclick=function(){ act("act_reject", btn.getAttribute("data-rej"), bodyId, stage, approveAction); }; });
        body.querySelectorAll("[data-edit]").forEach(function(btn){ btn.onclick=function(){ var asg=btn.getAttribute("data-edit"); if(!asg){ toast("No assignment link on this record"); return; } openActualForEdit(asg, btn.getAttribute("data-doc"), stage); }; });
      });
    }).catch(function(e){ b.className=""; b.innerHTML='<div class="empty">Could not load.</div>'; });
  }
  function act(which,name,bodyId,stage,approveAction){
    call({action:which,name:name}).then(function(d){
      if(d.error){ toast("Error: "+d.error); return; }
      toast(name+" → "+d.workflow_state);
      loadStage(bodyId, stage, approveAction);
    }).catch(function(e){ toast("Action failed"); });
  }

  function boot(){
    call({action:"a_roles"}).then(function(roles){
      ST.roles=roles;
      el("ac-who").textContent=(roles.user||"")+(roles.is_hr_head?" · HR Head":"");
      initEnter(); buildTabs();
    }).catch(function(e){ el("ac-who").textContent="Could not load."; });
  }
  if(typeof frappe==="undefined"){ var w=el("ac-who"); if(w) w.textContent="Open inside Frappe."; }
  else { if(el("ac-asg")) boot(); else document.addEventListener("DOMContentLoaded", boot); }
})();
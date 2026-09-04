(function () {
  // Poppins, matching the other Upande navigation blocks. Document-level so it
  // reaches this block's shadow root.
  try {
    if (!document.querySelector('link[data-upande-poppins]')) {
      var pf = document.createElement('link');
      pf.rel = 'stylesheet';
      pf.setAttribute('data-upande-poppins', '1');
      pf.href = 'https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap';
      document.head.appendChild(pf);
    }
  } catch (e) {}

  // The desk moved from /app to /desk in v16 and this app supports both, so the
  // record tiles ship the v15 route and are rewritten here when the desk we are
  // running inside says otherwise. Nothing is hardcoded to one version.
  try {
    var prefix = (window.location.pathname || '').indexOf('/desk') === 0 ? '/desk' : '/app';
    root_element.querySelectorAll('.uwmn-tile[data-desk]').forEach(function (tile) {
      tile.setAttribute('href', prefix + '/' + tile.getAttribute('data-desk'));
    });
  } catch (e) {}

  // Role-gate the tiles: data-roles="" shows for everyone; otherwise the tile
  // shows only if the user holds one of the listed roles. System Manager and
  // Administrator always see everything.
  var roles = (window.frappe && frappe.user_roles) || [];
  var isAdmin = roles.indexOf('System Manager') >= 0
    || roles.indexOf('Administrator') >= 0
    || (window.frappe && frappe.user && frappe.user.name === 'Administrator');
  root_element.querySelectorAll('.uwmn-tile').forEach(function (tile) {
    var req = (tile.getAttribute('data-roles') || '')
      .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (req.length === 0) return;
    var ok = isAdmin || req.some(function (r) { return roles.indexOf(r) >= 0; });
    if (!ok) tile.classList.add('uwmn-hide');
  });

  // AND LOCK A DESK TILE THIS USER CANNOT OPEN.
  // The /app tiles all shipped as data-roles="", so every reader was offered ten
  // links into the desk whether or not they could read the doctype behind them.
  // A farm manager clicking "Plan requests" got Frappe's bare "Not permitted",
  // which reads as the whole module being shut to them rather than as one dead
  // link -- and that is how it was reported.
  //
  // Locked, not hidden. A tile that simply is not there teaches nobody that a
  // permission is missing, which is the same reason the actuals crew bar shows
  // its button disabled rather than removing it. Hiding it would also bury the
  // next lost permission: today the desk at least says "Not permitted".
  //
  // The permission that decides this is not the one this app ships. A site that
  // has ever opened the Role Permissions Manager for a doctype gets a
  // `Custom DocPerm` set, and that REPLACES the doctype's own permissions --
  // the shipped JSON is then read by nobody. So the tile asks what the reader
  // may actually read, which Frappe puts in the boot payload.
  //
  // Fails OPEN: no payload means lock nothing. A tile that refuses on click is a
  // smaller failure than a navigation page that locks itself.
  var canRead = (window.frappe && frappe.boot && frappe.boot.user
    && frappe.boot.user.can_read) || null;
  if (canRead && canRead.length) {
    root_element.querySelectorAll('.uwmn-tile[data-doctype]').forEach(function (tile) {
      var dt = tile.getAttribute('data-doctype');
      if (!dt || canRead.indexOf(dt) >= 0) return;
      tile.classList.add('uwmn-locked');
      tile.removeAttribute('href');          // not a link any more
      tile.setAttribute('aria-disabled', 'true');
      tile.setAttribute('title', 'You do not have permission to open ' + dt);
      tile.addEventListener('click', function (ev) { ev.preventDefault(); });
      var tx = tile.querySelector('.uwmn-tx');
      if (tx && !tx.querySelector('.uwmn-lock')) {
        var note = document.createElement('span');
        note.className = 'uwmn-lock';
        note.textContent = 'No permission \u2014 ask an administrator';
        tx.appendChild(note);
      }
    });
  }

  // Live counts on the record tiles, so the page reports workload rather than
  // just offering links. Deliberately additive: a count that cannot be read —
  // no permission, missing doctype, offline — simply never appears, and the
  // tile is exactly as useful as it was without it.
  try {
    if (!(window.frappe && frappe.db && frappe.db.count)) return;
    root_element.querySelectorAll('.uwmn-tile[data-count]').forEach(function (tile) {
      var doctype = tile.getAttribute('data-count');
      if (!doctype) return;
      frappe.db.count(doctype).then(function (n) {
        if (!(n > 0)) return;
        var badge = document.createElement('span');
        badge.className = 'uwmn-n';
        badge.textContent = n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(n);
        tile.appendChild(badge);
      }).catch(function () {});
    });
  } catch (e) {}
})();

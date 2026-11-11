# System Console script (Desk > System Console, type: Python). RestrictedPython-safe:
# no imports, no tuple unpacking, no set(), no .format() -- and no `def`, because
# the sandbox runs top-level code with separate globals and locals, so a function
# cannot see the names defined beside it.
#
# Points the Work Management workflow Notifications at the command-centre screens
# instead of the desk form. The URL inside each link's href -- /app/work-management-
# planner/..., /desk/..., or a get_url_to_form(...) call -- becomes
# {{ wm_screen_url(doc) }}, which opens the right screen, tab and document
# (work_management/links.py). Nothing else in the template is touched: live's
# hand-fixed wording (get_fullname and the rest) stays exactly as it is.
#
# RUN ORDER
#   1. Deploy work_management with links.py and the `jinja` hook first. Before
#      that, `wm_screen_url` is undefined and every one of these emails fails.
#   2. Run as is (DRY_RUN = True). Read the before/after for every record.
#   3. Set DRY_RUN = False, tick "Commit", run again.
#   Running it again later is harmless: a fixed URL no longer matches.

DRY_RUN = True

DOCTYPES = [
	"Work Management Planner",
	"Work Management Assigner",
	"Work Management Master Plan",
	"Work Management Actuals",
]
EXPECTED = 13
NEW_URL = "{{ wm_screen_url(doc) }}"
# what a desk-form link looks like inside a URL
MARKERS = ["/app/work-management-", "/desk/work-management-", "get_url_to_form("]

rows = frappe.get_all(
	"Notification",
	filters={"document_type": ["in", DOCTYPES]},
	fields=["name", "document_type", "enabled"],
	order_by="document_type asc, name asc",
)
targets = []
for r in rows:
	msg = frappe.db.get_value("Notification", r.name, "message") or ""
	keep = NEW_URL in msg
	for m in MARKERS:
		if m in msg:
			keep = True
	if keep:
		targets.append(r)

print("Work Management Notifications with a desk or screen link: " + str(len(targets))
	+ " (expected " + str(EXPECTED) + ")")
if len(targets) != EXPECTED:
	print("  !! not " + str(EXPECTED) + " -- read the list below before switching DRY_RUN off")
print("")

changed = 0
manual = []
for r in targets:
	doc = frappe.get_doc("Notification", r.name)
	before = doc.message or ""

	# Walk every href="..." / href='...'. The URL runs to the closing quote,
	# skipping {{ ... }} -- whose own quotes, as in
	# get_url_to_form("Work Management Planner", doc.name), are not the attribute's.
	after = ""
	replaced = 0
	i = 0
	while True:
		hit = -1
		quote = ""
		for q in ['"', "'"]:
			j = before.find("href=" + q, i)
			if j >= 0 and (hit < 0 or j < hit):
				hit = j
				quote = q
		if hit < 0:
			after = after + before[i:]
			break
		start = hit + 6
		end = -1
		k = start
		while k < len(before):
			if before[k:k + 2] == "{{":
				close = before.find("}}", k + 2)
				if close < 0:
					break
				k = close + 2
				continue
			if before[k] == quote:
				end = k
				break
			k = k + 1
		if end < 0:
			after = after + before[i:]
			break
		url = before[start:end]
		after = after + before[i:start]
		desk = False
		for m in MARKERS:
			if m in url:
				desk = True
		if desk:
			after = after + NEW_URL
			replaced = replaced + 1
		else:
			after = after + url
		i = end

	left = False
	for m in MARKERS:
		if m in after:
			left = True

	print("=" * 78)
	print(r.name + "  [" + r.document_type + "]" + ("" if r.enabled else "  (disabled)"))
	if replaced == 0:
		if left:
			print("  !! desk link found but not inside an href -- fix by hand")
			manual.append(r.name)
		else:
			print("  already points at the screens; nothing to do")
		continue
	if left:
		print("  !! a desk link is still left after the fix -- check by hand")
		manual.append(r.name)
	print("  URLs replaced: " + str(replaced))
	print("  --- before")
	print(before)
	print("  --- after")
	print(after)
	if not DRY_RUN:
		doc.message = after
		doc.save()
	changed = changed + 1

print("=" * 78)
print(("WOULD CHANGE " if DRY_RUN else "CHANGED ") + str(changed) + " Notification(s).")
if manual:
	print("Check by hand: " + ", ".join(manual))
if DRY_RUN:
	print("Dry run: nothing saved. Set DRY_RUN = False and tick Commit to apply.")

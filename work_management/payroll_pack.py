"""Send the payroll approval pack when HR sends Kaitet task pay to Accounts.

When a Kaitet Ltd. Payroll Entry that pays Work Management task pay moves to
"Pending Accounts", the approvers get the whole pack (a short summary and the
workbook) and each farm manager gets a pack cut down to their own farm. The
rules for what goes in a pack live in payroll_pack_book; this module loads the
rows, decides who gets mail, and sends it.

It is pay data, so the recipients are deliberately narrow:

  - the full pack goes only to the Settings list `payroll_pack_to` (Bcc
    `payroll_pack_bcc`). If that list is empty nothing is sent and an Error
    Log says so -- it never falls back to a role or anyone else.
  - a farm pack goes only to that farm's enabled "Actuals: Farm Manager"
    approvers. A farm with none gets no mail, and the full pack names it.
  - a test send goes only to the addresses given, never Bcc, never a farm
    manager, and is not recorded, so it does not make the next real one
    "Revised".

frappe.sendmail does not create a Communication, so each real send records one
itself: one per audience (the full pack, and each farm), found again by its exact
subject so the next send to that audience is marked "Revised". The record is
medium "Other", not "Email" -- an Email Communication links every address to its
Contact (and on to Leads and the like), and its content would then show on those
timelines to anyone who can read them. It carries no figures for the same
reason, and it is not linked to the mail (`communication=`), which would only add
a read-tracking pixel and delivery-status writes back onto it.
"""

import frappe
from frappe.utils import cint, getdate

from work_management.payroll_pack_book import (
	attachment_name, build_pack, email_html, farm_recipients, farms_in, filter_farm,
	split_addresses, subject, workbook_bytes,
)

TASK_PAY_COMPANY = "Kaitet Ltd."
TRIGGER_STATE = "Pending Accounts"
PACK_SUBJECT_PREFIX = "Task pay for approval"

SETTINGS = "Work Management Settings"
FM_STAGE = "Actuals: Farm Manager"
WM_PAYMENT = "Work Management Payment"

# The range download: at most this many days, counted inclusively.
MAX_RANGE_DAYS = 92
DEAD_STATES = ("Cancelled", "Rejected")


def should_send(company, state_changed, new_state, has_wm, enabled):
	return bool(company == TASK_PAY_COMPANY and state_changed and new_state == TRIGGER_STATE
		and has_wm and enabled)


def _enabled():
	return cint(frappe.db.get_single_value(SETTINGS, "payroll_pack_enabled"))


# --- loading -----------------------------------------------------------------

def _has_workflow_state():
	"""Sites without the payroll workflow have no workflow_state column."""
	return frappe.db.has_column("Payroll Entry", "workflow_state")


def load_rows(entry_names):
	"""(entries, lines, slips, days_by_employee, days_by_employee_farm) for build_pack."""
	names = tuple(entry_names)
	if not names:
		return [], [], [], {}, {}
	state = "workflow_state" if _has_workflow_state() else "NULL"
	entries = frappe.db.sql(f"""
		select name, start_date, end_date, {state} as workflow_state
		from `tabPayroll Entry` where name in %(names)s order by start_date, name
	""", {"names": names}, as_dict=True)

	# One row per (slip, WM Additional Salary); a slip with none still appears,
	# with wmpay NULL, so a person paid with no work behind it is seen.
	slips = frappe.db.sql("""
		select ss.payroll_entry as entry, ss.name as slip, ss.employee, ss.employee_name,
			ads.ref_docname as wmpay, sd.amount as wm_amount
		from `tabSalary Slip` ss
		left join (`tabSalary Detail` sd
			join `tabAdditional Salary` ads
				on ads.name = sd.additional_salary
				and ads.ref_doctype = %(wm)s
				and ads.docstatus != 2)
			on sd.parent = ss.name and sd.parenttype = 'Salary Slip' and sd.parentfield = 'earnings'
		where ss.payroll_entry in %(names)s and ss.docstatus != 2
		order by ss.name
	""", {"names": names, "wm": WM_PAYMENT}, as_dict=True)
	for row in slips:
		row["wm_amount"] = float(row.get("wm_amount") or 0)

	wmpays = tuple(sorted({r["wmpay"] for r in slips if r.get("wmpay")}))
	if not wmpays:
		return entries, [], slips, {}, {}

	lines = frappe.db.sql("""
		select wpl.parent as wmpay, wpl.employee, wpl.employee_name, wpl.farm,
			coalesce(nullif(t.subject, ''), wpl.task) as task, wpl.task as task_id,
			wpl.block, wpl.work_from, wpl.work_to, wpl.days, wpl.qty, wpl.rate, wpl.amount,
			wpl.entered_by, wpl.fm_approved_by, wpl.hr_approved_by, wpl.gm_approved_by
		from `tabWork Payment Line` wpl
		left join `tabTask` t on t.name = wpl.task
		where wpl.parent in %(wmpays)s
		order by wpl.parent, wpl.idx
	""", {"wmpays": wmpays}, as_dict=True)

	days = frappe.db.sql("""
		select wae.employee, count(distinct wae.work_date) as days
		from `tabWork Actuals Employee` wae
		where wae.payment_ref in %(wmpays)s and wae.count_in_payroll = 1
		group by wae.employee
	""", {"wmpays": wmpays}, as_dict=True)

	days_farm = frappe.db.sql("""
		select wae.employee, wma.farm, count(distinct wae.work_date) as days
		from `tabWork Actuals Employee` wae
		join `tabWork Management Actuals` wma on wma.name = wae.parent
		where wae.payment_ref in %(wmpays)s and wae.count_in_payroll = 1
		group by wae.employee, wma.farm
	""", {"wmpays": wmpays}, as_dict=True)

	return (entries, lines, slips,
		{r["employee"]: cint(r["days"]) for r in days},
		{(r["employee"], r["farm"]): cint(r["days"]) for r in days_farm})


def has_task_pay(entry_name):
	"""Does any live slip on this entry carry a Work Management Additional Salary?"""
	return bool(frappe.db.sql("""
		select 1
		from `tabSalary Slip` ss
		join `tabSalary Detail` sd on sd.parent = ss.name and sd.parenttype = 'Salary Slip'
		join `tabAdditional Salary` ads on ads.name = sd.additional_salary
		where ss.payroll_entry = %(entry)s and ss.docstatus != 2
			and ads.ref_doctype = %(wm)s and ads.docstatus != 2
		limit 1
	""", {"entry": entry_name, "wm": WM_PAYMENT}))


def entries_in_range(from_date, to_date):
	"""Submitted, live Kaitet task-pay Payroll Entries overlapping [from_date, to_date]."""
	state = "and workflow_state not in %(dead)s" if _has_workflow_state() else ""
	names = frappe.db.sql(f"""
		select name from `tabPayroll Entry`
		where company = %(company)s and docstatus = 1 {state}
			and start_date <= %(to_date)s and end_date >= %(from_date)s
		order by start_date, name
	""", {"company": TASK_PAY_COMPANY, "dead": DEAD_STATES,
		"from_date": from_date, "to_date": to_date})
	return [r[0] for r in names if has_task_pay(r[0])]


@frappe.whitelist(methods=["GET"])
def download_breakdown(from_date, to_date):
	"""The task pay breakdown workbook for every task-pay payroll in a date range.

	All or nothing: every entry must be readable by the user before anything is
	built. GET because the button opens it as a URL.
	"""
	# getdate("") is today, so a missing date is caught before it is parsed.
	start = getdate(from_date) if from_date else None
	end = getdate(to_date) if to_date else None
	if not start or not end:
		frappe.throw("Give both a From and a To date.")
	if start > end:
		frappe.throw("From must be on or before To.")
	if (end - start).days + 1 > MAX_RANGE_DAYS:
		frappe.throw(f"Pick at most {MAX_RANGE_DAYS} days.")
	names = entries_in_range(start, end)
	if not names:
		frappe.throw("No task-pay payrolls in that range.")
	for name in names:
		frappe.has_permission("Payroll Entry", "read", doc=name, throw=True)
	pack = build_pack(*load_rows(names))
	frappe.response.filename = attachment_name(start, end)
	frappe.response.filecontent = workbook_bytes(pack)
	frappe.response.type = "binary"


# --- the hook ----------------------------------------------------------------

def on_payroll_entry_update(doc, method=None):
	"""Payroll Entry on_update_after_submit: queue the pack on the move to Pending Accounts.

	The cheap checks run first so an ordinary save never touches the slips.
	"""
	changed = doc.has_value_changed("workflow_state")
	enabled = _enabled()
	worth_a_look = (doc.company == TASK_PAY_COMPANY and doc.workflow_state == TRIGGER_STATE
		and changed and enabled)
	if not should_send(doc.company, changed, doc.workflow_state,
			worth_a_look and has_task_pay(doc.name), enabled):
		return
	frappe.enqueue("work_management.payroll_pack.send_pack", queue="long",
		enqueue_after_commit=True, entry_name=doc.name)


# --- sending -----------------------------------------------------------------

def _stage_rows():
	settings = frappe.get_cached_doc(SETTINGS)
	return [{"stage_label": r.stage_label, "scope": r.scope, "user": r.user}
		for r in (settings.get("stage_approvers") or [])]


def _enabled_users(users):
	if not users:
		return []
	return frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 1}, pluck="name")


def _record_subject(entry_name, farm=None):
	"""What a send to one audience is recorded as: no figures, no TEST."""
	return " \u2014 ".join([PACK_SUBJECT_PREFIX, entry_name] + ([farm] if farm else []))


def _already_sent(entry_name, farm=None):
	"""Has this audience (the full pack, or one farm's) had this entry's pack?

	An exact match on the recorded subject, not LIKE: entry and farm names come
	from the database and may hold % or _."""
	return bool(frappe.db.exists("Communication", {
		"reference_doctype": "Payroll Entry",
		"reference_name": entry_name,
		"communication_type": "Communication",
		"communication_medium": "Other",
		"subject": _record_subject(entry_name, farm),
	}))


def _record(entry_name, farm, recipients):
	"""A Communication for one real send: who got which pack, and nothing else.

	Medium "Other" so Communication.validate adds no timeline links; no bcc, no
	figures, no email body -- see the module docstring."""
	comm = frappe.get_doc({
		"doctype": "Communication",
		"communication_type": "Communication",
		"communication_medium": "Other",
		"sent_or_received": "Sent",
		"subject": _record_subject(entry_name, farm),
		"content": ("Farm pack for " + farm if farm else "Payroll approval pack")
			+ " emailed to " + ", ".join(recipients) + ".",
		"recipients": ", ".join(recipients),
		"reference_doctype": "Payroll Entry",
		"reference_name": entry_name,
	})
	comm.insert(ignore_permissions=True)
	return comm.name


def _mail(result, entry_name, farm, sender, recipients, bcc, subj, html, fname, content, test):
	frappe.sendmail(recipients=list(recipients), bcc=list(bcc) if bcc else None, sender=sender,
		subject=subj, message=html, attachments=[{"fname": fname, "fcontent": content}],
		reference_doctype="Payroll Entry", reference_name=entry_name, add_unsubscribe_link=0)
	if not test:
		_record(entry_name, farm, recipients)
	result["sent"].append({"to": list(recipients), "subject": subj})


def send_pack(entry_name, test_recipients=None):
	"""Send the full pack and the farm packs for one Payroll Entry.

	With `test_recipients` (even an empty list) everything goes only to those
	addresses, marked TEST, and errors are raised as well as logged.
	"""
	result = {"sent": [], "skipped": []}
	try:
		_send(entry_name, test_recipients, result)
	except Exception:
		frappe.log_error(title="Payroll approval pack failed", message=frappe.get_traceback())
		if test_recipients is not None:
			raise
	return result


def _send(entry_name, test_recipients, result):
	test = test_recipients is not None
	entries, lines, slips, days, days_farm = load_rows([entry_name])
	if not entries:
		result["skipped"].append(f"{entry_name}: no such Payroll Entry")
		return
	pack = build_pack(entries, lines, slips, days, days_farm)
	start, end = entries[0]["start_date"], entries[0]["end_date"]
	url = frappe.utils.get_url_to_form("Payroll Entry", entry_name)
	sender = (frappe.db.get_single_value(SETTINGS, "payroll_pack_sender") or "").strip()
	if not sender:
		# Never fall back to the default outgoing account for pay data.
		if test:
			frappe.throw("Set the payroll pack sender in Work Management Settings first.")
		result["skipped"].append(f"{entry_name}: no sender set")
		frappe.log_error(title="Payroll approval pack has no sender",
			message=f"Work Management Settings has no 'payroll_pack_sender'; "
				f"the approval pack for {entry_name} was not sent to anyone.")
		return

	rows = _stage_rows()
	fms = farm_recipients(rows, set(_enabled_users({r["user"] for r in rows if r.get("user")})))
	farms = farms_in(pack)
	without = [f for f in farms if f not in fms]

	if test:
		to, bcc = list(test_recipients), []
	else:
		to = split_addresses(frappe.db.get_single_value(SETTINGS, "payroll_pack_to"))
		bcc = split_addresses(frappe.db.get_single_value(SETTINGS, "payroll_pack_bcc"))
	if not to:
		result["skipped"].append(f"{entry_name}: no recipients for the full pack")
		if not test:
			frappe.log_error(title="Payroll approval pack has no recipients",
				message=f"Work Management Settings has no 'payroll_pack_to' address; "
					f"the approval pack for {entry_name} was not sent to approvers.")
		else:
			return
	else:
		_mail(result, entry_name, None, sender, to, bcc,
			subject(entry_name, pack["totals"]["slip_total"], revised=_already_sent(entry_name), test=test),
			email_html(pack, entry_name, url, farms_without_fm=without),
			attachment_name(start, end), workbook_bytes(pack), test)

	for farm in farms:
		if farm not in fms:
			result["skipped"].append(f"{farm}: no farm manager")
			continue
		farm_pack = filter_farm(pack, farm)
		_mail(result, entry_name, farm, sender, list(test_recipients) if test else fms[farm], [],
			subject(entry_name, farm_pack["totals"]["slip_total"], revised=_already_sent(entry_name, farm),
				farm=farm, test=test),
			email_html(farm_pack, entry_name, url, farm=farm),
			attachment_name(start, end, farm), workbook_bytes(farm_pack), test)


@frappe.whitelist()
def send_test_pack(entry_name, recipients):
	"""Send the whole pack, farm packs included, only to `recipients` (comma separated)."""
	frappe.only_for("System Manager")
	addresses = split_addresses(recipients)
	if not addresses:
		frappe.throw("Give at least one address to send the test pack to.")
	return send_pack(entry_name, addresses)

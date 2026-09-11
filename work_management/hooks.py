app_name = "work_management"
app_title = "Work Management"
app_publisher = "Upande Ltd"
app_description = (
	"Work management command centre: plan task work against a budget, assign "
	"crews, capture actuals and run worker payments."
)
app_email = "dev@upande.com"
app_license = "mit"

# Two hard dependencies.
#
# upande_core owns "Farm". A doctype name is global, and Upande Kaitet ships a
# `Farm` of its own -- so on a site carrying that one, an unguarded read would
# quietly find the wrong records rather than none. Requiring the app that owns
# the name is what makes reading it safe; there is no exists() check anywhere
# that could tell the two apart.
#
# hrms owns the work model: Employee, Employee Checkin, and the employment_type
# an assignment is filtered by. This was not declared, so the app installed
# happily on a site without HRMS and the dashboard then died with
# `Unknown column 'employment_type'`, which tells nobody anything. An undeclared
# dependency works where it was built and fails obscurely everywhere else.
required_apps = ["upande_core", "hrms"]

# The apps screen entry. Routed at the dashboard rather than the desk
# workspace, because the dashboard is the front door people are sent to.
# Which workspace the app opens on. Without this, boot.load_desktop_data falls
# back to the first row of an unordered query over the app's workspaces, which
# came back alphabetically and opened "Work Delivery" instead of the parent.
# /app redirects to /desk on v16, so one route serves both versions.
app_home = "/app/work-management"

# The apps screen reads its route from HERE, not from the Desktop Icon -- which
# is why fixing the icon did not change where clicking the app went. It used to
# be hardcoded to /work-management, the web dashboard, so the app jumped past
# the desk into a single screen. It reuses app_home now: land in the desk on
# this app's workspace, sidebar and all, and let the reader choose.
add_to_apps_screen = [
	{
		"name": "work_management",
		# the Upande mark, as every sibling app uses -- see desk.LOGO_URL
		"logo": "/assets/work_management/images/upande-logo.png",
		"title": "Work Management",
		"route": app_home,
		"has_permission": "work_management.api.permission.has_app_permission",
	}
]

# The five pages call these bare endpoints (/api/method/wm_planner etc.).
# Mapping them here keeps the frontend identical to the original Web Pages
# and lets the app transparently replace the old Server Scripts.
doc_events = {
	"Employee": {
		"on_update": "work_management.api.hr.release_inactive",
	},
	# Editing a rate in the Task list records a rate period effective today, so
	# history writes itself rather than depending on anyone maintaining it.
	"Task": {
		"on_update": "work_management.rates.task_on_update",
	},
	# Payroll linkage: the Additional Salary a payment run raises only actually
	# pays once its Salary Slip is submitted, and cancelling the run must take
	# the Additional Salary with it. See work_management/api/payment.py.
	"Salary Slip": {
		"on_submit": "work_management.api.payment.on_salary_slip_submit",
		"on_cancel": "work_management.api.payment.on_salary_slip_cancel",
	},
	"Work Management Payment": {
		# Not on_cancel: this doctype's docstatus never leaves 0 by design, so
		# its workflow's Cancel action is a plain save, not a real
		# doc.cancel() -- see on_payment_update()'s docstring.
		"on_update": "work_management.api.payment.on_payment_update",
	},
	"Additional Salary": {
		"on_cancel": "work_management.api.payment.on_additional_salary_cancel",
	},
}

override_whitelisted_methods = {
	"wm_dashboard": "work_management.api.dashboard.wm_dashboard",
	"wm_planner": "work_management.api.planner.wm_planner",
	"wm_assigner": "work_management.api.assigner.wm_assigner",
	"wm_actuals": "work_management.api.actuals.wm_actuals",
	"wm_payment": "work_management.api.payment.wm_payment",
	"wm_rates": "work_management.api.rates.wm_rates",
	"wm_masterplan": "work_management.api.masterplan.wm_masterplan",
}

scheduler_events = {
	# Activates any rate period that starts today. Without this a rate card
	# loaded in advance would never take effect — nothing else fires on its
	# start date.
	"daily": [
		"work_management.rates.sync_active_periods",
	],
}

after_install = "work_management.install.after_install"
before_install = "work_management.install.before_install"

# Takes back any doctype the site owns as a custom one (it deploys nowhere, and
# migrate says nothing about it), reseeds the approval stage catalogue and
# regenerates the five workflows from it, relabels the desk from the taxonomy
# template, and repairs the desk workspace when a same-named one built in the
# desk has shadowed the one this app ships.
after_migrate = [
	"work_management.install.adopt_existing_custom_doctypes",
	# before the taxonomy writes its Property Setters: deleting a Custom Field
	# takes that field's Property Setters with it
	"work_management.install.drop_shadowing_custom_fields",
	# before approvals.after_migrate, which saves Settings: a farms row naming no
	# farm fails that save and takes the whole migrate with it
	"work_management.install.drop_farmless_settings_rows",
	"work_management.approvals.after_migrate",
	"work_management.install.drop_stale_link_options",
	"work_management.taxonomy.apply_labels",
	"work_management.desk.sync",
]

# The parent workspace's body is a Custom HTML Block, which is not an importable
# doctype and so has to be upserted in code. before_migrate, because sync_all()
# then imports the workspace that references it.
before_migrate = "work_management.desk.ensure_nav_block"

# No Role fixture. This app used to ship five -- Farm Manager, General Manager,
# HOD HR, HR Clerk, Production Section Head -- because the shipped approval steps
# defaulted to them and a Workflow Transition's role must exist. Installing at any
# company therefore created Kaitet's hierarchy on their site. The steps now default
# to System Manager, which Frappe guarantees, so nothing is created and a new
# company maps the steps onto its own roles.
fixtures = [
	{
		"dt": "Workflow State",
		"filters": [
			[
				"name",
				"in",
				[
					"Approved",
					"Assigned",
					"CONFIRMED",
					"Draft",
					"Paid",
					"Pending Accounts",
					"Pending Approval",
					"Pending Consultant",
					"Pending Farm Manager",
					"Pending GM",
					"Pending HR Head",
					"Rejected",
					"Unpaid",
					"Cancelled",
				],
			]
		],
	},
	{
		"dt": "Workflow Action Master",
		"filters": [
			[
				"name",
				"in",
				[
					"Approve",
					"Cancel",
					"FM Approve",
					"GM Approve",
					"HR Approve",
					"Mark Paid",
					"Re-submit",
					"Reject",
					"Send for Consultant Review",
					"Send to Accounts",
					"Send to GM",
					"Submit for Approval",
				],
			]
		],
	}

]

website_route_rules = []

# Tried before the wiki app's own renderers -- this app installs ahead of wiki --
# so a signed-out visitor asking for an internal guide is sent to sign in rather
# than told the page does not exist. See work_management/wiki_guest_redirect.py.
page_renderer = ["work_management.wiki_guest_redirect.WikiGuestLoginRedirect"]

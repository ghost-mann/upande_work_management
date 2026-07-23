app_name = "upande_work_management"
app_title = "Upande Work Management"
app_publisher = "Upande Ltd"
app_description = (
	"Farm work management command centre: plan task work, assign crews, "
	"capture actuals and run worker payments."
)
app_email = "dev@upande.com"
app_license = "mit"

# The five pages call these bare endpoints (/api/method/wm_planner etc.).
# Mapping them here keeps the frontend identical to the original Web Pages
# and lets the app transparently replace the old Server Scripts.
override_whitelisted_methods = {
	"wm_dashboard": "upande_work_management.api.dashboard.wm_dashboard",
	"wm_planner": "upande_work_management.api.planner.wm_planner",
	"wm_assigner": "upande_work_management.api.assigner.wm_assigner",
	"wm_actuals": "upande_work_management.api.actuals.wm_actuals",
	"wm_payment": "upande_work_management.api.payment.wm_payment",
}

after_install = "upande_work_management.install.after_install"
before_install = "upande_work_management.install.before_install"

fixtures = [
	{"dt": "Workflow", "filters": [["name", "like", "Work Management%"]]},
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
					"Pending Farm Manager",
					"Pending GM",
					"Pending HR Head",
					"Rejected",
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
					"FM Approve",
					"GM Approve",
					"HR Approve",
					"Mark Paid",
					"Re-submit",
					"Reject",
					"Send to Accounts",
					"Submit for Approval",
				],
			]
		],
	},
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					"Agriculture Manager",
					"Coffee Clerk",
					"Farm Manager",
					"Farm Manager Endebess",
					"Farm Manager Lokitela",
					"Farm Manager Saboti",
					"Farm Manager Valle",
					"General Manager",
					"HOD HR",
					"HR Clerk",
					"HR Manager Kaitet",
					"Production Section Head",
				],
			]
		],
	},
]

website_route_rules = []

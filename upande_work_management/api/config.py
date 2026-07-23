"""Deployment configuration for Upande Work Management.

Everything site-specific (farm names, their cost project, the approving role,
default company, block exclusion keywords) is read from the single doctype
"Work Management Settings". If that document has no farms configured the
original Kaitet defaults below are used, so an unconfigured install behaves
exactly like the system this app was extracted from.
"""

import frappe

KAITET_DEFAULTS = {
	"farms": ["Saboti", "Lokitela", "Vale", "Endebess"],
	"farm_project": {
		"Saboti": "PROJ-0031",
		"Lokitela": "PROJ-0031",
		"Vale": "PROJ-0031",
		"Endebess": "PROJ-0032",
	},
	"farm_approver_role": {
		"Saboti": "Farm Manager Saboti",
		"Lokitela": "Farm Manager Lokitela",
		"Endebess": "Farm Manager Endebess",
		# Live role name is spelled "Valle" — kept for compatibility.
		"Vale": "Farm Manager Valle",
	},
	"default_company": "Kaitet Ltd.",
	"block_exclude": ["Store", "Mill", "Tank", "BIN", "Warehouse", "Cold Room", "Parchment", "Diesel"],
}


def get_config():
	cfg = {
		"farms": list(KAITET_DEFAULTS["farms"]),
		"farm_project": dict(KAITET_DEFAULTS["farm_project"]),
		"farm_approver_role": dict(KAITET_DEFAULTS["farm_approver_role"]),
		"default_company": KAITET_DEFAULTS["default_company"],
		"block_exclude": list(KAITET_DEFAULTS["block_exclude"]),
	}
	try:
		settings = frappe.get_cached_doc("Work Management Settings")
	except Exception:
		return cfg

	if settings.get("default_company"):
		cfg["default_company"] = settings.default_company
	if settings.get("block_exclude"):
		kws = [k.strip() for k in settings.block_exclude.split(",") if k.strip()]
		if kws:
			cfg["block_exclude"] = kws
	rows = settings.get("farms") or []
	if rows:
		cfg["farms"] = [r.farm for r in rows if r.farm]
		cfg["farm_project"] = {r.farm: r.project for r in rows if r.farm and r.project}
		cfg["farm_approver_role"] = {r.farm: r.approver_role for r in rows if r.farm and r.approver_role}
	return cfg

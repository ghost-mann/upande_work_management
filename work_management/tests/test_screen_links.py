"""Notification links open the command centre, at the document.

The workflow Notifications (live only) sent people to the desk form. People
work in the screens, so `{{ wm_screen_url(doc) }}` now builds

    /work-planner?tab=appr&ref=<name>

-- one convention on every screen: `tab` picks the tab, `ref` opens the
document once its list has loaded, and a ref the reader cannot see gets a
message (links.locate) rather than a blank screen. A Guest is sent to log in and
back to the SAME link: Frappe's own Not Permitted page drops the query string.

    ./env/bin/python -m unittest work_management.tests.test_screen_links -v
"""

import os
import re
import unittest
from urllib.parse import parse_qs, urlsplit

from work_management.links import (
	ACTUALS,
	ASSIGNER,
	MASTER_PLAN,
	PLANNER,
	SCREENS,
	screen_path,
	state_kind,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
	with open(os.path.join(HERE, *parts)) as handle:
		return handle.read()


# kentrout.local's chain, as get_config()["stage_states"] reports it
PLANNER_STATES = {"draft": "Draft", "terminal": "Approved", "reject": "Rejected",
	"waiting": ["Pending Approval", "Pending HR Approval"]}
ASSIGNER_STATES = {"draft": "Draft", "terminal": "Assigned", "reject": "Rejected",
	"waiting": ["Pending Manager", "Pending HR Head", "Pending GM"]}


def link(doctype, name, state, groups):
	u = urlsplit(screen_path(doctype, name, state, groups))
	q = parse_qs(u.query)
	return u.path, q["tab"][0], q["ref"][0]


class TestWhereEachStateGoes(unittest.TestCase):
	def test_pending_goes_to_approvals(self):
		self.assertEqual(link(PLANNER, "WM-F-00001", "Pending HR Approval", PLANNER_STATES),
			("/work-planner", "appr", "WM-F-00001"))
		self.assertEqual(link(ASSIGNER, "WMA-1", "Pending GM", ASSIGNER_STATES)[1], "aappr")
		self.assertEqual(link(ACTUALS, "WMAC-1", "Pending Manager", ASSIGNER_STATES)[1], "acappr")

	def test_rejected_goes_to_the_author_s_rejected_tab(self):
		self.assertEqual(link(PLANNER, "X", "Rejected", PLANNER_STATES)[1], "rej")
		self.assertEqual(link(ASSIGNER, "X", "Rejected", ASSIGNER_STATES)[1], "arej")
		self.assertEqual(link(ACTUALS, "X", "Rejected", ASSIGNER_STATES)[1], "acrej")

	def test_final_states_go_to_my_lists(self):
		self.assertEqual(link(PLANNER, "X", "Approved", PLANNER_STATES)[1], "mine")
		self.assertEqual(link(ASSIGNER, "X", "Assigned", ASSIGNER_STATES)[1], "amine")
		self.assertEqual(link(ACTUALS, "X", "Approved", ASSIGNER_STATES)[1], "acmine")

	def test_a_master_plan_always_opens_in_the_master_plan_tab(self):
		for state in ("Pending Consultant", "Rejected", "Approved"):
			self.assertEqual(link(MASTER_PLAN, "GH-3-MP-26-001", state,
				{"waiting": ["Pending Consultant"], "reject": "Rejected"})[:2],
				("/work-planner", "mp"))

	def test_a_renamed_step_is_still_pending(self):
		"""The chain's own state list decides, not a name written here."""
		self.assertEqual(state_kind("Pending Section Head", {"waiting": ["Pending Section Head"]}), "pending")

	def test_a_name_with_a_space_survives_the_url(self):
		"""Planner names carry the farm: WM-KenTrout Farm-00042."""
		path = screen_path(PLANNER, "WM-KenTrout Farm-00042", "Approved", PLANNER_STATES)
		self.assertNotIn(" ", path)
		self.assertEqual(link(PLANNER, "WM-KenTrout Farm-00042", "Approved", PLANNER_STATES)[2],
			"WM-KenTrout Farm-00042")

	def test_every_screen_tab_named_here_exists_on_its_screen(self):
		files = {"/work-planner": "work-planner.js", "/work-assigner": "work-assigner.js",
			"/work-actuals": "work-actuals.js"}
		for route, tabs in SCREENS.values():
			src = read("public", "js", files[route])
			for tab in tabs.values():
				self.assertIn('["%s",' % tab, src, (route, tab))


class TestTemplatesCanCallIt(unittest.TestCase):
	def test_it_is_a_jinja_global(self):
		"""Frappe registers each listed function under its own name."""
		hooks = read("hooks.py")
		self.assertRegex(hooks, r'jinja = \{\s*"methods": \["work_management\.links\.wm_screen_url"\]')

	def test_the_function_is_called_what_templates_write(self):
		self.assertIn("def wm_screen_url(doc):", read("links.py"))


class TestLocate(unittest.TestCase):
	def setUp(self):
		self.src = read("links.py")

	def test_it_is_a_whitelisted_get(self):
		self.assertIn('@frappe.whitelist(methods=["GET"])\ndef locate(', self.src)

	def test_it_checks_read_permission(self):
		self.assertIn('frappe.has_permission(dt, "read", name)', self.src)

	def test_missing_and_forbidden_read_the_same(self):
		"""A link must not reveal which names exist."""
		self.assertEqual(self.src.count('"message": _(UNAVAILABLE).format(name)'), 2)


class TestLoginKeepsTheLink(unittest.TestCase):
	PAGES = ("work_planner", "work_assigner", "work_actuals", "work_management", "work_payment")

	def test_every_page_sends_a_guest_through_require_login(self):
		for page in self.PAGES:
			src = read("www", page + ".py")
			self.assertIn("require_login()", src, page)
			self.assertNotIn("frappe.PermissionError", src, page)

	def test_the_query_string_is_kept(self):
		src = read("links.py")
		self.assertIn("req.query_string", src)
		self.assertIn('urlencode({"redirect-to": back})', src)
		# temporary: a cached 301 would bounce a reader who has logged in since
		self.assertIn("raise frappe.Redirect(302)", src)


class TestEveryScreenReadsTheLink(unittest.TestCase):
	SCREENS = (("work-planner", "work_planner"), ("work-assigner", "work_assigner"),
		("work-actuals", "work_actuals"), ("work-management", "work_management"))

	def test_the_helper_loads_before_the_screen_script(self):
		for html, py in self.SCREENS:
			page = read("www", html + ".html")
			self.assertLess(page.index('<script src="{{ deeplink_js }}"></script>'),
				page.index('s.src = "{{ screen_js }}"'), html)
			self.assertIn("context.deeplink_js = screen_js('wm-deeplink.js')", read("www", py + ".py"))

	def test_each_tabbed_screen_starts_from_the_link(self):
		for js, default in (("work-planner", "new"), ("work-assigner", "assign"), ("work-actuals", "enter")):
			src = read("public", "js", js + ".js")
			self.assertIn("WMDeepLink.start({", src, js)
			self.assertIn('defaultTab: "%s"' % default, src, js)
			# the old unconditional first tab is gone from buildTabs
			body = src[src.index("function buildTabs(){"):src.index("function showTab(")]
			self.assertNotIn('showTab("%s");\n  }' % default, body, js)

	def test_approvals_open_the_queue_the_document_waits_in(self):
		for js in ("work-assigner", "work-actuals"):
			self.assertIn("if(q.stage && q.stage===info.state) ST._apprKey=q.key;",
				read("public", "js", js + ".js"), js)

	def test_the_old_master_plan_link_still_works(self):
		self.assertIn("alias: {mp: \"mp\"}", read("public", "js", "work-planner.js"))

	def test_the_dashboard_opens_its_modals(self):
		src = read("public", "js", "work-management-dashboard.js")
		self.assertIn(".then(load, load).then(openLinked);", src)
		for call in ("openPlanModal(info.name", "openActualModal(info.name)", "openPaymentModal(info.name)"):
			self.assertIn(call, src)

	def test_the_helper_says_so_rather_than_leaving_a_blank_screen(self):
		src = read("public", "js", "wm-deeplink.js")
		self.assertIn("notice(info.message", src)
		self.assertIn("is not in", src)
		self.assertIn('[data-f="q"]', src)


CONSOLE = os.path.join(os.path.dirname(HERE), "scripts", "console", "notification_links_to_screens.py")


class TestTheConsoleScript(unittest.TestCase):
	"""The System Console script that repoints live's Notifications. It runs in
	Frappe's sandbox: no imports, no tuple unpacking, no set(), no .format(),
	and no `def` -- top-level code there has separate globals and locals."""

	def setUp(self):
		with open(CONSOLE) as handle:
			self.src = handle.read()
		import ast
		self.tree = ast.parse(self.src)

	def test_it_compiles_under_the_sandbox_policy(self):
		from RestrictedPython import compile_restricted
		from work_management.tests.test_mirror_compiles_in_the_sandbox import sandbox_policy
		policy = sandbox_policy()[0]
		compile_restricted(self.src, filename="console.py", policy=policy, mode="exec")

	def test_none_of_what_the_sandbox_refuses(self):
		import ast
		for node in ast.walk(self.tree):
			self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Lambda))
			if isinstance(node, (ast.For, ast.comprehension)):
				self.assertNotIsInstance(node.target, ast.Tuple)
			if isinstance(node, ast.Assign):
				for t in node.targets:
					self.assertNotIsInstance(t, ast.Tuple)
			if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
				self.assertNotEqual(node.func.id, "set")
			if isinstance(node, ast.Attribute):
				self.assertNotEqual(node.attr, "format")

	def test_it_is_a_dry_run_by_default(self):
		self.assertIn("\nDRY_RUN = True\n", self.src)
		self.assertIn("if not DRY_RUN:\n\t\tdoc.message = after\n\t\tdoc.save()", self.src)

	def test_it_writes_the_jinja_global_this_app_registers(self):
		self.assertIn('NEW_URL = "{{ wm_screen_url(doc) }}"', self.src)


if __name__ == "__main__":
	unittest.main()

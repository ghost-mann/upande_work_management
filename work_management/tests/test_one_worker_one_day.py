"""One worker, one day, one task (2026-11-12).

Live held 962 worker-days paid on two actuals. 238 of the rows since 1 Oct
belonged to a worker marked Left on the other assignment: being released took
them out of the busy check, but their days there were still recorded, and the
new assignment over the same dates paid those days again.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_one_worker_one_day -v
"""

import datetime
import os
import re
import textwrap
import types
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source(module):
	with open(os.path.join(HERE, "api", module + ".py")) as handle:
		return handle.read()


def nested(module, name, scope):
	"""A helper defined inside a ported wm_x() body, dedented and exec'd."""
	src = source(module)
	start = src.index("    def " + name + "(")
	end = src.index("\n    def ", start + 1) if "\n    def " in src[start + 1:] else None
	nxt = re.search(r"\n    (?!\s|def )\S", src[start + 1:])
	stop = start + 1 + nxt.start() if nxt else len(src)
	if end is not None and end < stop:
		stop = end
	exec(textwrap.dedent(src[start:stop]), scope)
	return scope[name]


TODAY = "2026-11-12"


def fake_frappe(form=None):
	utils = types.SimpleNamespace(
		today=lambda: TODAY,
		add_days=lambda d, n: str(datetime.date.fromisoformat(str(d)) + datetime.timedelta(days=n)),
	)
	return types.SimpleNamespace(utils=utils, form_dict=dict(form or {}))


def backdate(gm, form=None, days=7):
	scope = {"frappe": fake_frappe(form), "WMG_BACKDATE_DAYS": days, "WMG_GM": gm}
	return nested("assigner", "wmg_backdate_err", scope)


class TestBusyIncludesReleasedWorkers(unittest.TestCase):
	"""Every busy-elsewhere query bounds a worker by their own window on the other
	assignment -- start to left_date -- and never by being Active."""

	def busy_queries(self, module):
		src = source(module)
		return [m.group(0) for m in re.finditer(
			r"FROM `tabWork Assignment Employee` we\s+INNER JOIN `tabWork Management Assigner` a"
			r"[\s\S]{0,700}?a\.name != %s[\s\S]{0,500}?\"\"\"", src)]

	def test_left_worker_still_blocks_their_dates(self):
		for module in ("assigner", "actuals"):
			queries = self.busy_queries(module)
			self.assertTrue(queries, module)
			for q in queries:
				with self.subTest(module=module):
					self.assertNotIn("IFNULL(we.status,'Active') = 'Active'", q)
					self.assertIn("COALESCE(we.start_date, a.from_date) <= %s", q)
					self.assertIn("THEN we.left_date END, a.to_date) >= %s", q)

	def test_a_substitute_is_bounded_by_the_replacements_start(self):
		for module in ("assigner", "actuals"):
			with self.subTest(module=module):
				self.assertIn("str(start_date) if start_date and str(start_date) > str(rdates.from_date)",
					source(module))

	def test_no_refusal_offers_the_split_day_switch(self):
		self.assertNotIn("Allow a worker's day to be split", source("assigner"))


class TestBackdating(unittest.TestCase):
	def test_recent_start_passes(self):
		self.assertEqual(backdate(0)("2026-11-05"), "")

	def test_backdate_refused_for_clerk(self):
		self.assertIn("Ask the GM", backdate(0)("2026-09-28"))

	def test_gm_needs_a_reason(self):
		self.assertIn("Give a reason", backdate(1)("2026-09-28"))

	def test_backdate_allowed_for_gm_with_reason(self):
		self.assertEqual(backdate(1, {"backdate_reason": "late paperwork"})("2026-09-28"), "")

	def test_every_way_onto_work_checks_it(self):
		src = source("assigner")
		for action in ("a_submit", "a_add_crew", "a_substitute"):
			start = src.index('action == "' + action + '"')
			end = src.find("\n    elif action", start + 1)
			end = len(src) if end < 0 else end
			with self.subTest(action=action):
				self.assertIn("wmg_backdate_err(", src[start:end])
				self.assertIn("wmg_log_backdate(", src[start:end])


if __name__ == "__main__":
	unittest.main()

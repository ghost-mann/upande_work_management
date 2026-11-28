"""Team leaders, People tab: Download Excel (2026-11-27).

The list exports every team leader and the people on their crews, and an opened
team leader exports their own. tlPeopleSheets is pure and runs under node here.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_tl_people_excel -v
"""

import json
import os
import re
import shutil
import subprocess
import unittest

from work_management.tests import mirror

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(HERE, "public", "js", "work-management-dashboard.js")


def source():
	with open(JS, encoding="utf-8") as f:
		return f.read()


def function_src(name):
	m = re.search(r"\n  function " + name + r"\(.*?\n  }\n", source(), re.S)
	assert m, name + " not found"
	return m.group(0)


def run_sheets(leaders, people, kpis):
	js = function_src("tlPeopleSheets") + (
		"\nprocess.stdout.write(JSON.stringify(tlPeopleSheets(%s, %s, %s)));"
		% (json.dumps(leaders), json.dumps(people), json.dumps(kpis)))
	out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
	return json.loads(out.stdout)


LEADERS = [{"key": "jane@x", "name": "Jane Leader"}, {"key": "EMP-7", "name": "Otto Seven"}]
KPIS = {"jane@x": {"plans": 3, "completion": 92.345, "efficiency": 104.06, "earned_md": 31.25, "worked_md": 30,
		"scored": 4, "good": 75, "fair": 25, "rework": 0}}
PEOPLE = [
	{"people": [
		{"emp": "100001", "name": "Ann Worker", "farm": "Vale", "days": 5, "on_today": 1, "status": "Present", "scan": "06:58",
		 "acts": [{"task_label": "Weeding", "block": "B1", "since": "2026-11-02", "until": "2026-11-08"},
				  {"task_label": "Pruning", "block": None, "since": "2026-11-09", "until": "2026-11-15"}]},
		{"emp": "100002", "name": "Ben Worker", "farm": "Vale", "days": 0, "on_today": 1, "status": "No scan yet", "scan": None,
		 "acts": [{"task_label": "Weeding", "block": "B2", "since": "2026-11-02", "until": "2026-11-27"}]},
		{"emp": "100003", "name": "Cy Worker", "farm": "Vale", "days": 2, "on_today": 0, "status": "Absent", "scan": None,
		 "acts": []},
	]},
	{"people": []},
]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestSheets(unittest.TestCase):
	def setUp(self):
		self.s = run_sheets(LEADERS, PEOPLE, KPIS)

	def test_leader_rows(self):
		head, jane, otto = self.s["leaders"]
		self.assertEqual(head[0], "Team leader")
		self.assertEqual(jane[:5], ["Jane Leader", 3, 92.3, 104.1, 31.3])
		self.assertEqual(jane[head.index("People on crews")], 3)
		self.assertEqual(jane[head.index("Assigned on the day")], 2)
		self.assertEqual(jane[head.index("Present")], 1)
		self.assertEqual(jane[head.index("No scan yet")], 1)
		# no KPIs: blanks, not zeros
		self.assertEqual(otto[1:4], ["", "", ""])
		self.assertEqual(otto[head.index("People on crews")], 0)

	def test_one_row_per_person(self):
		head = self.s["people"][0]
		rows = self.s["people"][1:]
		self.assertEqual([r[head.index("Worker")] for r in rows], ["Ann Worker", "Ben Worker", "Cy Worker"])
		ann = rows[0]
		self.assertEqual(ann[head.index("Team leader")], "Jane Leader")
		self.assertEqual(ann[head.index("Employee ID")], "100001")
		self.assertEqual(ann[head.index("Days worked")], 5)
		self.assertEqual(ann[head.index("Activities")],
						 "Weeding · B1 (2026-11-02 → 2026-11-08); Pruning (2026-11-09 → 2026-11-15)")
		self.assertEqual(ann[head.index("On the day")], "Present")
		self.assertEqual(ann[head.index("First scan")], "06:58")
		self.assertEqual(rows[2][head.index("On the day")], "Not on a crew that day")
		self.assertEqual(rows[2][head.index("Activities")], "")


class TestWiring(unittest.TestCase):
	def test_button_only_on_people_tab(self):
		ctl = function_src("tlControls")
		self.assertIn('id="tlk-xlsx"', ctl)
		self.assertIn('TLK.tab==="people"', ctl)
		self.assertIn("Download Excel", ctl)

	def test_wired_and_uses_sheetjs(self):
		self.assertIn('el("tlk-xlsx")', function_src("tlWire"))
		ex = function_src("tlPeopleExcel")
		self.assertIn("tlPeopleSheets(", ex)
		self.assertIn('action:"tl_people"', ex)
		self.assertIn("team_leader:", ex)
		self.assertIn("XLSX.writeFile", ex)
		self.assertIn("cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js", source())

	@unittest.skipUnless(mirror.present(mirror.WEB_PAGES), "mirror not checked out")
	def test_same_as_mirror(self):
		with open(os.path.join(mirror.WEB_PAGES, "work-management-dashboard.js"), encoding="utf-8") as h:
			self.assertEqual(h.read(), source())


if __name__ == "__main__":
	unittest.main()

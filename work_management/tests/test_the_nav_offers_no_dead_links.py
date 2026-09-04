"""The navigation must not offer a desk link the reader cannot open.

Every /app tile in the workspace block shipped as data-roles="", so every reader
was offered ten links into the desk regardless of whether they could read the
doctype behind them. Clicking one returns Frappe's bare "Not permitted", which
reads as the whole module being closed rather than as one dead link -- and that
is how it was reported: "cannot access work management section", by a Farm
Manager who could have used every web screen on the same page.

The permission that decides it is not the one this app ships. A site that has
ever opened the Role Permissions Manager for a doctype gets a `Custom DocPerm`
set, which REPLACES the doctype's own permissions entirely; the shipped JSON is
then read by nobody. Two sites had drifted apart exactly there, one of them
having lost Farm Manager on the Planner. So the tile cannot be gated on a role
named here -- only on what the reader may actually read, which Frappe puts in
the boot payload.

Hence: every /app tile names its doctype, the script hides one the reader cannot
read, and it fails OPEN -- no boot payload means hide nothing, because a tile
that refuses on click is a smaller failure than a navigation page that empties
itself.
"""

import os
import re
import unittest

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = os.path.join(APP, "custom_html_block", "work_management_navigation")


def read(ext):
	with open(BLOCK + "." + ext) as handle:
		return handle.read()


def tiles():
	"""(href, data-doctype) for every tile in the block."""
	out = []
	for m in re.finditer(r'<a class="uwmn-tile"[^>]*>', read("html")):
		tag = m.group(0)
		href = re.search(r'href="([^"]*)"', tag)
		dt = re.search(r'data-doctype="([^"]*)"', tag)
		out.append((href.group(1) if href else None, dt.group(1) if dt else None))
	return out


class TestEveryDeskTileNamesItsDoctype(unittest.TestCase):
	def test_there_are_tiles(self):
		self.assertGreaterEqual(len(tiles()), 10)

	def test_every_app_tile_carries_a_doctype(self):
		missing = [h for h, dt in tiles() if h and h.startswith("/app/") and not dt]
		self.assertEqual(missing, [],
			"these desk tiles cannot be permission-checked: " + ", ".join(missing))

	def test_no_web_tile_carries_one(self):
		"""The web screens work without doctype read -- that is the point of
		their raw SQL -- so gating them would hide a working link."""
		wrong = [h for h, dt in tiles() if h and not h.startswith("/app/") and dt]
		self.assertEqual(wrong, [], "web tiles must not be gated: " + ", ".join(wrong))


class TestTheScriptGatesOnWhatCanBeRead(unittest.TestCase):
	def setUp(self):
		self.js = read("js")

	def test_it_reads_the_boot_payload(self):
		self.assertIn("frappe.boot.user", self.js)
		self.assertIn("can_read", self.js)

	def test_it_hides_a_tile_naming_an_unreadable_doctype(self):
		self.assertIn("[data-doctype]", self.js)
		self.assertIn("uwmn-hide", self.js)

	def test_it_fails_open_when_the_payload_is_absent(self):
		"""No list -> hide nothing. A guard that hides everything on a missing
		global is how a navigation page turns into a blank one."""
		gate = self.js[self.js.index("var canRead"):][:500]
		self.assertRegex(gate, r"if\s*\(canRead\s*&&\s*canRead\.length\)",
			"the gate must run only when the payload actually arrived")

	def test_the_role_gate_still_exists_for_settings(self):
		"""Per-tile roles and per-tile read permission are different questions:
		Settings is gated by role, the record lists by what you may read."""
		self.assertIn("data-roles", self.js)
		self.assertIn('data-roles="System Manager,HR Manager"', read("html"))


if __name__ == "__main__":
	unittest.main()

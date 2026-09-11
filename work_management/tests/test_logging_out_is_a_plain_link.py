"""Logging out is a link to /logout, not a GET at a POST-only command.

Every screen's account menu offered `/?cmd=web_logout`. That command is real,
but it is declared

    @frappe.whitelist(allow_guest=True, methods=["POST"])
    def web_logout():

and an anchor is a GET. Frappe's `is_whitelisted` rejects the method mismatch
with a PermissionError titled "Method Not Allowed" -- so users clicking Log out
were told they lacked permission to log out, which is both wrong and alarming.

`/logout` is a page Frappe ships (`frappe/www/logout.html`) whose only job is to
call `frappe.logout()` on load. That does the POST properly and redirects, so a
plain link works and needs no permission at all.

There is no test that the link WORKS -- that needs a browser -- so this asserts
the two things a file can be asked: that the POST-only command is gone from
every screen, and that each screen still offers a way out.

    PYTHONPATH=. ~/frappe-v16-bench/env/bin/python -m unittest \
        work_management.tests.test_logging_out_is_a_plain_link -v
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(HERE, "www")
SCREENS = ("work-management", "work-planner", "work-assigner", "work-actuals", "work-payment")


def page(name):
	with open(os.path.join(WWW, name + ".html")) as handle:
		return handle.read()


def logout_href(html):
	m = re.search(r'<a\s+href="([^"]*)"[^>]*id="wm-account-logout"', html)
	return m.group(1) if m else None


class TestEveryScreenLogsOutWithALink(unittest.TestCase):
	def test_no_screen_uses_the_post_only_command(self):
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertNotIn("cmd=web_logout", page(screen),
					screen + " still logs out with a GET at a POST-only command")

	def test_every_screen_has_a_logout_link(self):
		"""Removing the broken one and leaving no way out would also 'pass'."""
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertIsNotNone(logout_href(page(screen)),
					screen + " has no wm-account-logout anchor")

	def test_it_points_at_the_logout_page(self):
		for screen in SCREENS:
			with self.subTest(screen=screen):
				self.assertEqual(logout_href(page(screen)), "/logout")


if __name__ == "__main__":
	unittest.main()

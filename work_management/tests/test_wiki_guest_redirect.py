"""What a signed-out visitor gets when they open an internal guide.

The decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_wiki_guest_redirect -v
"""

import unittest

from work_management.wiki_guest_redirect import login_url, should_redirect


class TestWhoGetsSentToLogin(unittest.TestCase):
	"""Wiki 3 answers 404 rather than 403 for a space a visitor cannot read, so
	a shared link reads as broken instead of as "sign in". This steps in for
	exactly that case and no other.
	"""

	def test_guest_on_a_private_page_is_redirected(self):
		self.assertTrue(should_redirect("Guest", "some-doc", guest_may_read=False))

	def test_a_signed_in_user_is_never_touched(self):
		# They may legitimately be refused; that is the wiki's call, not ours.
		self.assertFalse(should_redirect("james@upande.com", "some-doc", guest_may_read=False))

	def test_a_route_with_no_page_still_404s(self):
		# Redirecting here would tell a stranger which routes exist.
		self.assertFalse(should_redirect("Guest", None, guest_may_read=False))

	def test_a_public_page_is_left_to_the_wiki(self):
		# Making a space guest-readable must keep working.
		self.assertFalse(should_redirect("Guest", "some-doc", guest_may_read=True))


class TestWhereTheySentBack(unittest.TestCase):
	def test_it_comes_back_to_the_page_they_asked_for(self):
		self.assertEqual(
			login_url("work-management-guide/daily-work/planner"),
			"/login?redirect-to=/work-management-guide/daily-work/planner",
		)

	def test_leading_and_trailing_slashes_do_not_double_up(self):
		self.assertEqual(login_url("/upande-crm-guide/"), "/login?redirect-to=/upande-crm-guide")

	def test_the_path_separators_survive_quoting(self):
		# A percent-encoded path would fail Frappe's sanitize_redirect and drop
		# the visitor on the home page instead of the guide they clicked.
		self.assertIn("/upande-webstore-guide/for-customers", login_url("upande-webstore-guide/for-customers/x"))

	def test_a_query_string_cannot_escape_the_parameter(self):
		# Anything that could end the parameter early has to be encoded.
		self.assertNotIn("&", login_url("a/b?x=1&y=2"))


if __name__ == "__main__":
	unittest.main()

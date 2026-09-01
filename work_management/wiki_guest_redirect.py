"""Send signed-out visitors to the login page instead of a bare 404.

Frappe Wiki 3 answers "Page not found" -- a ``DoesNotExistError``, rendered as a
404 -- when a visitor cannot read a space, so that a private space does not leak
its own existence. That is the right default for a wiki on a public site and the
wrong one for ours: every guide here is internal, the links get shared with
colleagues who do have accounts, and a 404 reads as "this link is broken" rather
than "sign in first". People retry the link, then ask whether the guide was
published at all.

Custom page renderers are tried before the ones the wiki app registers, and this
app installs ahead of wiki, so this gets first refusal on a wiki route. It acts
only for Guest, and only where a published page really does exist at the path --
a genuinely missing route still 404s, for guests and members alike, so nothing
here tells a stranger which routes are real.

The redirect is a **302**. ``frappe.redirect()`` raises a permanent 301, which
browsers cache: the visitor would sign in, come back to the same URL, and be
bounced to the login page again by their own cache.

The decisions are pure and tested without a site::

    ./env/bin/python -m unittest work_management.tests.test_wiki_guest_redirect -v
"""

from urllib.parse import quote

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

GUEST = "Guest"


# ---------------------------------------------------------------- decisions


def login_url(path):
	"""Where to send a signed-out visitor who asked for ``path``.

	``redirect-to`` is the parameter Frappe's own login page reads, and it
	sanitises anything that is not a relative path, so the round trip only ever
	lands back on this site.
	"""
	return "/login?redirect-to=" + quote("/" + (path or "").strip("/ "), safe="/")


def should_redirect(user, page_exists, guest_may_read):
	"""Whether this renderer should step in.

	Only for Guest, only where a published page exists, and only where the wiki
	itself would refuse it. A page the wiki would happily serve to a guest is
	left alone, so making a space public keeps working.
	"""
	return user == GUEST and bool(page_exists) and not guest_may_read


# ------------------------------------------------------------------ renderer


class WikiGuestLoginRedirect(BaseRenderer):
	def can_render(self):
		if frappe.session.user != GUEST:
			return False
		name = self._published_page()
		if not name:
			return False
		return should_redirect(GUEST, name, self._guest_may_read(name))

	def render(self):
		return self.build_response(
			"", http_status_code=302, headers={"Location": login_url(self.path)}
		)

	def _published_page(self):
		"""The published, non-group wiki page at this path, if there is one.

		Guarded because this app must not break the website on a site that has
		no wiki installed, or has a wiki whose schema differs.
		"""
		try:
			return frappe.db.get_value(
				"Wiki Document",
				{
					"route": self.path,
					"is_group": 0,
					"is_published": 1,
					"is_external_link": 0,
				},
				"name",
			)
		except Exception:
			return None

	def _guest_may_read(self, name):
		"""Ask the wiki's own access check, rather than reimplementing it."""
		try:
			doc = frappe.get_cached_doc("Wiki Document", name)
		except Exception:
			return True  # can't tell -- stay out of the way

		check = getattr(doc, "check_space_access", None)
		if check is None:
			return True  # a wiki without space access control; not ours to police

		try:
			check("read")
			return True
		except Exception:
			return False

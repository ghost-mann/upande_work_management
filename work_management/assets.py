"""Cache-busting tokens for the screens' own JavaScript.

Frappe Cloud's nginx serves everything under /assets with

    cache-control: max-age=31536000, immutable

and the five screens injected their script from a URL that never changed:

    s.src = "/assets/work_management/js/work-actuals.js";

`immutable` tells a browser not to revalidate -- not on a refresh, not on a
revisit -- so anyone who had opened a screen before a deploy went on running
the JavaScript from before that deploy, for up to a year. The page itself is
`no-store` and always fresh, which makes it worse rather than better: readers
got the new markup and the old script, and every fix looked like it had not
been deployed. That is how the split-hours box, the crew controls and the
release button all "failed to appear" on a site where the files were correct
and the setting was ticked; only a hard reload showed them.

It never showed on a dev bench, where `frappe serve` sends no such header.

The token is the file's mtime, so it changes exactly when the file does: one
fetch per deploy, and the year-long cache still does its job in between. A file
that cannot be read falls back to a per-request value, because busting the
cache too often costs a download and getting it stuck costs a bug report.
"""

import os

import frappe

APP = "work_management"


def asset_version(relative):
	"""A token for /assets/work_management/<relative>, changing when it does."""
	try:
		path = frappe.get_app_path(APP, "public", *relative.split("/"))
		return str(int(os.path.getmtime(path)))
	except Exception:
		# Unreadable, missing, or a path this app does not own: fall back to a
		# value that is never stale. Wrong in the cheap direction.
		return str(int(frappe.utils.now_datetime().timestamp()))


def screen_js(name):
	"""The full src for one screen's script, cache-busted.

	Templates use it whole -- `<script src="{{ screen_js('work-actuals.js') }}">`
	is one thing to get right instead of a path and a token to keep in step.
	"""
	return "/assets/%s/js/%s?v=%s" % (APP, name, asset_version("js/" + name))

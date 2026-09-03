"""Where the mirror is checked out.

Many tests here read the upstream Server Scripts and web pages to hold the
ported copy against them. Where that checkout sits is a fact about the machine,
not about the app, so it comes from the environment:

    WM_MIRROR=~/src/kaitet-work-management \
        bench --site <site> run-tests --app work_management

Unset, it falls back to the path the mirror sits at on the author's box, so
that machine needs no change. A mirror that is not checked out here is a skip
and never a failure -- every reader guards with present() first, because a
missing checkout says nothing about whether the code is right.
"""

import os

DEFAULT = "/home/austin/vscodeProjects/kaitet-work-management"

ROOT = os.path.expanduser(os.environ.get("WM_MIRROR") or DEFAULT)
SERVER_SCRIPTS = os.path.join(ROOT, "server_scripts")
WEB_PAGES = os.path.join(ROOT, "web_pages")
PORT_APP = os.path.join(ROOT, "port_app.py")


def present(path=None):
	"""True when the mirror is checked out here. Skip on False, do not fail."""
	return os.path.isdir(path or SERVER_SCRIPTS)

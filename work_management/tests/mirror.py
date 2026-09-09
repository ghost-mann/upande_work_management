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

A *forked* branch is the other case, and a different one: see forked() below.
"""

import os

DEFAULT = "/home/austin/vscodeProjects/kaitet-work-management"

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORK_NOTE = os.path.join(APP, "docs", "ALTURA_FORK.md")

FORK_SKIP = "altura fork: api/ and screens are source, see docs/ALTURA_FORK.md"

ROOT = os.path.expanduser(os.environ.get("WM_MIRROR") or DEFAULT)
SERVER_SCRIPTS = os.path.join(ROOT, "server_scripts")
WEB_PAGES = os.path.join(ROOT, "web_pages")
PORT_APP = os.path.join(ROOT, "port_app.py")


def present(path=None):
	"""True when the mirror is checked out here. Skip on False, do not fail."""
	return os.path.isdir(path or SERVER_SCRIPTS)


def forked():
	"""True on a branch that has declared api/ and the screens to be source.

	present() answers "is there a mirror to compare against here", which is a
	fact about the machine. This answers "is there anything to prove", which is
	a fact about the branch -- and the two must not be confused.

	On `altura` the app is what deploys: no porter runs downstream of api/, so
	nothing reverts a hand edit and the drift the mirror contract forbids is the
	intended state. The tests that enforce that contract therefore skip here, and
	they are gated on this rather than on present() so that they skip on a
	machine that *does* have a mirror checked out. A skip that depends on the
	checkout would go green on this box and fail on the author's, which is the
	one place the mirror lives.

	docs/ALTURA_FORK.md is both the declaration and the switch: deleting it
	re-arms every one of those tests, which is what folding this branch back
	into the mirror would want.
	"""
	return os.path.exists(FORK_NOTE)

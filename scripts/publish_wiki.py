#!/usr/bin/env python3
"""Publish a repo's ``docs/wiki`` tree into Frappe Wiki 3.x on a site.

    WIKI_TOKEN='api_key:api_secret' \
      scripts/publish_wiki.py --docs ../upande_crm/docs/wiki \
                              --site https://example.frappe.cloud

Wiki 3 keeps content in a ``Wiki Document`` nested-set tree whose ``content``
field is markdown and renders directly -- no ``Wiki Revision`` needed. Inserting
a ``Wiki Space`` auto-creates its root group, and ``route``/``slug``/``doc_key``
are all derived server-side, so the publisher only ever sends title, parentage,
ordering, flags and body.

Idempotency hangs on ``source_path``: every document carries the manifest path of
the file it came from, so a second run updates in place instead of duplicating
the tree. A run that changes nothing writes nothing.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60


class Api:
	def __init__(self, site, token, dry_run=False):
		self.site = site.rstrip("/")
		self.token = token
		self.dry_run = dry_run
		self.writes = 0

	def _call(self, method, path, payload=None):
		url = f"{self.site}{path}"
		body = json.dumps(payload).encode() if payload is not None else None
		req = urllib.request.Request(url, data=body, method=method)
		req.add_header("Authorization", f"token {self.token}")
		req.add_header("Content-Type", "application/json")
		try:
			with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
				return json.loads(resp.read().decode())
		except urllib.error.HTTPError as exc:
			detail = exc.read().decode(errors="replace")[:800]
			raise SystemExit(f"{method} {path} failed: HTTP {exc.code}\n{detail}") from exc

	def get_list(self, doctype, filters, fields):
		query = urllib.parse.urlencode({
			"filters": json.dumps(filters),
			"fields": json.dumps(fields),
			"limit_page_length": 0,
		})
		dt = urllib.parse.quote(doctype)
		return self._call("GET", f"/api/resource/{dt}?{query}").get("data", [])

	def insert(self, doctype, doc):
		if self.dry_run:
			print(f"    would CREATE {doctype}: {doc.get('title') or doc.get('route')}")
			return {"name": f"<dry-run-{doctype}>"}
		self.writes += 1
		dt = urllib.parse.quote(doctype)
		return self._call("POST", f"/api/resource/{dt}", doc)["data"]

	def update(self, doctype, name, doc):
		if self.dry_run:
			print(f"    would UPDATE {doctype} {name}: {sorted(doc)}")
			return {"name": name}
		self.writes += 1
		dt = urllib.parse.quote(doctype)
		return self._call("PUT", f"/api/resource/{dt}/{urllib.parse.quote(name)}", doc)["data"]


def load_manifest(docs_dir):
	path = os.path.join(docs_dir, "wiki.json")
	if not os.path.exists(path):
		raise SystemExit(f"no wiki.json in {docs_dir}")
	with open(path) as fh:
		manifest = json.load(fh)
	for key in ("space_name", "route", "groups"):
		if key not in manifest:
			raise SystemExit(f"wiki.json missing required key: {key}")
	return manifest


def read_page(docs_dir, rel_path):
	full = os.path.join(docs_dir, rel_path)
	if not os.path.exists(full):
		raise SystemExit(f"page file missing: {full}")
	with open(full) as fh:
		return fh.read()


def ensure_space(api, manifest):
	"""Return (space_name, root_group). Created on first run, matched on route after."""
	route = manifest["route"]
	found = api.get_list("Wiki Space", [["route", "=", route]], ["name", "root_group", "space_name"])
	if found:
		space = found[0]
		if space.get("space_name") != manifest["space_name"]:
			api.update("Wiki Space", space["name"], {"space_name": manifest["space_name"]})
		print(f"  space: {route} (existing)")
		return space["name"], space["root_group"]

	space = api.insert("Wiki Space", {
		"space_name": manifest["space_name"],
		"route": route,
		"is_published": 1,
	})
	print(f"  space: {route} (created)")
	return space["name"], space.get("root_group")


def upsert_document(api, space, parent, source_path, fields):
	"""Create or update one Wiki Document, keyed on source_path."""
	found = api.get_list(
		"Wiki Document",
		[["source_path", "=", source_path], ["wiki_space", "=", space]],
		["name", "title", "content", "sort_order", "is_group", "parent_wiki_document", "is_published"],
	)
	payload = dict(fields, wiki_space=space, parent_wiki_document=parent, source_path=source_path)

	if not found:
		doc = api.insert("Wiki Document", payload)
		print(f"    + {fields['title']}")
		return doc["name"]

	existing = found[0]
	changed = {
		key: value for key, value in payload.items()
		if key in existing and (existing.get(key) or None) != (value or None)
	}
	# parentage and space are set on create; only resend if they really moved
	changed.pop("wiki_space", None)
	if changed:
		api.update("Wiki Document", existing["name"], changed)
		print(f"    ~ {fields['title']} ({', '.join(sorted(changed))})")
	else:
		print(f"    = {fields['title']}")
	return existing["name"]


def publish(api, docs_dir, manifest):
	print(f"publishing {manifest['space_name']} -> {api.site}")
	space, root = ensure_space(api, manifest)

	for group_index, group in enumerate(manifest["groups"], start=1):
		group_path = f"__group__/{group['title']}"
		group_name = upsert_document(api, space, root, group_path, {
			"title": group["title"],
			"is_group": 1,
			"is_published": 1,
			"sort_order": group_index,
		})
		for page_index, page in enumerate(group["pages"], start=1):
			upsert_document(api, space, group_name, page["file"], {
				"title": page["title"],
				"is_group": 0,
				"is_published": 1,
				"sort_order": page_index,
				"content": read_page(docs_dir, page["file"]),
			})

	verb = "would write" if api.dry_run else "wrote"
	print(f"  {verb} {api.writes} document(s)")
	return f"{api.site}/{manifest['route']}"


def main():
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--docs", required=True, help="path to a repo's docs/wiki directory")
	parser.add_argument("--site", required=True, help="site base URL")
	parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
	args = parser.parse_args()

	token = os.environ.get("WIKI_TOKEN")
	if not token:
		raise SystemExit("set WIKI_TOKEN='api_key:api_secret' in the environment")

	docs_dir = os.path.abspath(args.docs)
	manifest = load_manifest(docs_dir)
	api = Api(args.site, token, dry_run=args.dry_run)
	url = publish(api, docs_dir, manifest)
	print(f"  {url}")
	return 0


if __name__ == "__main__":
	sys.exit(main())

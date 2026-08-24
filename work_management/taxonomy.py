"""What each level of the hierarchy is called, on this installation.

The module ships knowing the levels but not their names. A project that runs
estates and plots says so here once, and the desk labels and the five screens
follow. Nothing about a level's meaning is configurable -- only its name.
"""

from collections import namedtuple

Level = namedtuple("Level", "key singular plural optional")

# Ordered outermost first. `key` is the prefix of the Settings fields and of the
# keys resolve() returns.
LEVELS = (
	Level("bu", "Business Unit", "Business Units", True),
	Level("top", "Farm", "Farms", False),
	Level("unit", "Block", "Blocks", False),
	# Not a level in the chain: names the cost-centre grouping and its toggle.
	Level("section", "Section", "Sections", True),
)


def _pick(settings, fieldname, default):
	value = (settings.get(fieldname) or "").strip() if settings else ""
	return value or default


def resolve(settings):
	"""{name key: string} for this installation, falling back to the defaults.

	A blank name falls back rather than rendering an empty label, so clearing a
	field in Settings restores the shipped wording instead of breaking a form.
	"""
	names = {}
	for level in LEVELS:
		names[f"{level.key}_singular"] = _pick(settings, f"tax_{level.key}_singular", level.singular)
		names[f"{level.key}_plural"] = _pick(settings, f"tax_{level.key}_plural", level.plural)
	names["bu_enabled"] = bool(settings.get("tax_bu_enabled")) if settings else False
	return names


def label_for(template, names):
	"""Fill a label template. An unknown placeholder is left visible, not raised.

	Labels are cosmetic; a typo in one should look wrong, not stop a migrate.
	"""
	try:
		return template.format(**names)
	except (KeyError, IndexError):
		return template

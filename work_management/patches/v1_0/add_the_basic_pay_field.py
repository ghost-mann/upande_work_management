"""Create Employee.custom_basic_pay on a site that is already installed.

`create_core_custom_fields()` runs in after_install and nowhere else, so a field
added to CORE_CUSTOM_FIELDS after a site was built never arrives there. The
weekly payroll feed writes this field by name and refuses to run without it, so
"the button does nothing on the site that has been live longest" is the failure
this exists to prevent.

Idempotent by way of create_core_custom_fields() itself, which skips every field
that already exists -- so it is safe on a fresh install where after_install has
already made them, and safe to re-run.
"""

from work_management.install import create_core_custom_fields


def execute():
	create_core_custom_fields()

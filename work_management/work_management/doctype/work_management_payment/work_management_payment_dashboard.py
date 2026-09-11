def get_data():
    """The Additional Salary a run raised, shown as a Connection rather than a
    field on the form -- the real link lives on Additional Salary itself
    (ref_doctype/ref_docname), which is also what on_payment_cancel() and
    on_additional_salary_cancel() in api/payment.py both query."""
    return {
        "fieldname": "ref_docname",
        "non_standard_fieldnames": {"Additional Salary": "ref_docname"},
        "dynamic_links": {"ref_docname": ["Work Management Payment", "ref_doctype"]},
        "transactions": [
            {"label": "Payroll", "items": ["Additional Salary"]},
        ],
    }

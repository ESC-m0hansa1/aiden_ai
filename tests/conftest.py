

from datetime import date

import pytest

from docugen import templates


@pytest.fixture(autouse=True)
def clear_template_cache():
    """Templates are cached in a module-level dict, so reset it between tests."""
    templates.clear_cache()
    yield
    templates.clear_cache()


@pytest.fixture
def nda():
    return templates.load_template("nda")


@pytest.fixture
def nda_input():
    """A complete, valid set of answers for the NDA template."""
    return {
        "disclosing_party": "Northwind Logistics Pvt Ltd",
        "receiving_party": "Bluefin Analytics LLP",
        "effective_date": date(2026, 10, 15),
        "purpose": "evaluating a supply-chain forecasting pilot",
        "term_months": 24,
        "jurisdiction": "Karnataka, India",
        "confidential_scope": "pricing models and customer lists",
    }

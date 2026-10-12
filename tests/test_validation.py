"""Tests for input validation.

validate() returns a dict of problems rather than raising, so these tests check
both that good input is accepted and that each kind of bad input produces a
message aimed at the person filling in the form.
"""

from datetime import date

from docugen import validation


def test_complete_input_has_no_errors(nda, nda_input):
    assert validation.validate(nda, nda_input) == {}


def test_optional_field_may_be_left_blank(nda, nda_input):
    nda_input["confidential_scope"] = ""
    assert validation.validate(nda, nda_input) == {}


def test_missing_required_field_is_reported(nda, nda_input):
    nda_input["receiving_party"] = "   "
    errors = validation.validate(nda, nda_input)
    assert errors == {"receiving_party": "Receiving party is required."}


def test_a_missing_key_counts_as_missing(nda, nda_input):
    del nda_input["jurisdiction"]
    assert "jurisdiction" in validation.validate(nda, nda_input)


def test_every_problem_is_reported_at_once(nda, nda_input):
    """The UI shows all errors together, so validate must not stop at the first."""
    nda_input["receiving_party"] = ""
    nda_input["jurisdiction"] = ""
    errors = validation.validate(nda, nda_input)
    assert set(errors) == {"receiving_party", "jurisdiction"}


def test_non_numeric_term_is_rejected(nda, nda_input):
    nda_input["term_months"] = "twelve and a half"
    assert validation.validate(nda, nda_input)["term_months"] == "Term (months) must be a whole number."


def test_decimal_term_is_rejected_rather_than_rounded(nda, nda_input):
    nda_input["term_months"] = "12.5"
    assert "term_months" in validation.validate(nda, nda_input)


def test_term_below_minimum_is_rejected(nda, nda_input):
    nda_input["term_months"] = 0
    assert validation.validate(nda, nda_input)["term_months"] == "Term (months) must be at least 1."


def test_term_above_maximum_is_rejected(nda, nda_input):
    nda_input["term_months"] = 999
    assert validation.validate(nda, nda_input)["term_months"] == "Term (months) must be 120 or less."


def test_date_object_is_accepted(nda, nda_input):
    nda_input["effective_date"] = date(2026, 10, 15)
    assert validation.validate(nda, nda_input) == {}


def test_iso_date_string_is_accepted(nda, nda_input):
    nda_input["effective_date"] = "2026-10-15"
    assert validation.validate(nda, nda_input) == {}


def test_badly_formatted_date_is_rejected(nda, nda_input):
    nda_input["effective_date"] = "15/10/2026"
    assert "YYYY-MM-DD" in validation.validate(nda, nda_input)["effective_date"]


def test_overlong_text_is_rejected(nda, nda_input):
    nda_input["disclosing_party"] = "A" * 200
    message = validation.validate(nda, nda_input)["disclosing_party"]
    assert "too long" in message
    assert "maximum 120" in message

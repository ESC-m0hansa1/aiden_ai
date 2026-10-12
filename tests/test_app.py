"""Smoke tests for the Streamlit interface.

Streamlit's own AppTest harness runs app.py without a browser, so these catch
the kind of thing unit tests cannot: the app failing on load, a widget not
appearing, or the download button showing up while the form is still invalid.

These exist because a real bug got through: Template objects were being passed
as selectbox options, and Streamlit deep-copies widget options into session
state. A compiled Jinja template cannot be deep-copied, so the app crashed the
moment it loaded - while every unit test still passed.
"""

import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from docugen import llm
from docugen.llm import Clause

# AppTest resolves a relative path against the file that calls it, which would
# be tests/, so point at the app explicitly.
APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

REQUIRED_TEXT = {
    "nda.disclosing_party": "Northwind Logistics Pvt Ltd",
    "nda.receiving_party": "Bluefin Analytics LLP",
    "nda.jurisdiction": "Karnataka, India",
}
REQUIRED_TEXTAREA = {"nda.purpose": "evaluating a supply-chain forecasting pilot"}


@pytest.fixture
def app():
    return AppTest.from_file(APP_PATH, default_timeout=30).run()


def fill_required(at: AppTest) -> AppTest:
    """Fill every required field. Date and term already have usable defaults."""
    for key, value in REQUIRED_TEXT.items():
        at.text_input(key=key).set_value(value)
    for key, value in REQUIRED_TEXTAREA.items():
        at.text_area(key=key).set_value(value)
    return at.run()


def test_the_app_loads_without_crashing(app):
    assert not app.exception


def test_both_templates_are_offered(app):
    # .options exposes the formatted labels, which is what the user actually sees.
    assert app.sidebar.selectbox[0].options == ["Non-Disclosure Agreement", "Service Agreement"]


def test_the_form_is_built_from_the_field_spec(app):
    """Widgets come from the template JSON, so their keys mirror the field ids."""
    keys = {w.key for w in app.text_input} | {w.key for w in app.text_area}
    assert "nda.disclosing_party" in keys
    assert "nda.purpose" in keys
    assert any(w.key == "nda.term_months" for w in app.number_input)
    assert any(w.key == "nda.effective_date" for w in app.date_input)


def test_an_empty_form_shows_errors_and_offers_no_download(app):
    assert app.error, "expected validation errors on an empty form"
    assert len(app.get("download_button")) == 0


def test_a_complete_form_clears_errors_and_offers_the_download(app):
    at = fill_required(app)
    assert not at.exception
    assert not at.error
    assert len(at.get("download_button")) == 1


def test_the_preview_shows_what_was_typed(app):
    at = fill_required(app)
    # The preview is the last text area on the page, after the form fields.
    preview = at.text_area[-1].value
    assert "Northwind Logistics Pvt Ltd" in preview
    assert "Karnataka, India" in preview


def test_switching_template_rebuilds_the_form(app):
    at = app
    at.sidebar.selectbox[0].set_value("service_agreement")
    at = at.run()
    assert not at.exception
    keys = {w.key for w in at.text_input}
    assert "service_agreement.fee_amount" in keys
    assert "nda.disclosing_party" not in keys


# --- the accept / reject flow, driven through the UI ----------------------

FAKE_CLAUSES = [
    Clause(title="Data Security Controls", body="The Receiving Party shall encrypt all data.", rationale="Pilot handles data."),
    Clause(title="Non-Solicitation", body="Neither Party shall solicit the other's staff.", rationale="Staff overlap."),
]


@contextmanager
def model_returning(clauses):
    """Pretend a model is configured and that it returns these clauses."""
    with patch("docugen.llm.is_configured", return_value=True), patch(
        "docugen.llm.suggest_clauses", return_value=clauses
    ):
        yield


def test_suggestions_appear_after_pressing_the_button():
    with model_returning(FAKE_CLAUSES):
        at = fill_required(AppTest.from_file(APP_PATH, default_timeout=30).run())
        at.button[0].click()
        at = at.run()

        assert not at.exception
        labels = [c.label for c in at.checkbox]
        assert any("Data Security Controls" in label for label in labels)
        assert any("Non-Solicitation" in label for label in labels)


def test_only_the_ticked_clause_reaches_the_document():
    """The safety promise, checked through the UI rather than in isolation.

    Accept the first suggestion, leave the second alone, and confirm the
    preview contains one and not the other.
    """
    with model_returning(FAKE_CLAUSES):
        at = fill_required(AppTest.from_file(APP_PATH, default_timeout=30).run())
        at.button[0].click()
        at = at.run()

        at.checkbox[0].set_value(True)
        at = at.run()

        preview = at.text_area[-1].value
        assert "Data Security Controls" in preview
        assert "The Receiving Party shall encrypt all data." in preview
        assert "Non-Solicitation" not in preview
        assert "solicit the other's staff" not in preview


def test_a_model_failure_warns_but_leaves_the_app_usable():
    """Suggestions are an enhancement, so losing them must not block the download."""
    with patch("docugen.llm.is_configured", return_value=True), patch(
        "docugen.llm.suggest_clauses",
        side_effect=llm.LLMRateLimitError("The model provider is rate limiting us (free tier)."),
    ):
        at = fill_required(AppTest.from_file(APP_PATH, default_timeout=30).run())
        at.button[0].click()
        at = at.run()

        assert not at.exception
        assert any("rate limiting" in w.value for w in at.warning)
        assert len(at.get("download_button")) == 1


def test_the_suggest_button_is_disabled_until_the_form_is_valid():
    with model_returning(FAKE_CLAUSES):
        at = AppTest.from_file(APP_PATH, default_timeout=30).run()
        assert at.button[0].disabled is True

"""Tests for loading templates from disk."""

import json

import pytest

from docugen import templates


def test_both_templates_are_found():
    ids = templates.available_template_ids()
    assert "nda" in ids
    assert "service_agreement" in ids


def test_template_has_fields_and_a_body(nda):
    assert nda.name == "Non-Disclosure Agreement"
    assert len(nda.fields) > 0
    assert "{{ disclosing_party }}" in nda.body_source


def test_required_and_optional_fields_are_read_correctly(nda):
    assert nda.field("disclosing_party").required is True
    assert nda.field("confidential_scope").required is False
    assert nda.field("term_months").max == 120


def test_unknown_template_id_raises():
    with pytest.raises(templates.UnknownTemplateError):
        templates.load_template("power_of_attorney")


def test_templates_are_cached():
    """The second load must return the same object, not re-read the files.

    This is the caching requirement: Streamlit re-runs the script on every
    interaction, so without this we would re-parse JSON and recompile the
    Jinja template on every keystroke.
    """
    first = templates.load_template("nda")
    second = templates.load_template("nda")
    assert first is second


def test_clear_cache_forces_a_reload():
    first = templates.load_template("nda")
    templates.clear_cache()
    assert templates.load_template("nda") is not first


def test_malformed_json_gives_a_clear_error(tmp_path, monkeypatch):
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / "broken.j2").write_text("## Parties\nhello", encoding="utf-8")
    monkeypatch.setattr(templates, "TEMPLATE_DIR", tmp_path)

    with pytest.raises(templates.TemplateFormatError, match="not valid JSON"):
        templates.load_template("broken")


def test_unsupported_field_type_is_rejected(tmp_path, monkeypatch):
    spec = {
        "name": "Bad",
        "title": "BAD",
        "fields": [{"id": "x", "label": "X", "type": "colour_picker"}],
    }
    (tmp_path / "bad.json").write_text(json.dumps(spec), encoding="utf-8")
    (tmp_path / "bad.j2").write_text("## Parties\nhello", encoding="utf-8")
    monkeypatch.setattr(templates, "TEMPLATE_DIR", tmp_path)

    with pytest.raises(templates.TemplateFormatError, match="unsupported type"):
        templates.load_template("bad")

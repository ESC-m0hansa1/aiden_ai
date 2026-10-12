"""Tests for assembling the final document.

The most important test in this file is the one asserting that a rejected
clause does not appear. That is the central safety promise of the app: model
output only reaches the document if the user ticked it.
"""

from datetime import date

import pytest

from docugen import assembly, templates
from docugen.llm import Clause

ACCEPTED = Clause(title="Data Security", body="The Receiving Party shall encrypt all data.", rationale="r")
REJECTED = Clause(title="Non-Compete", body="The Receiving Party shall not compete.", rationale="r")


def headings(document):
    return [b.text for b in document.blocks if b.kind == "heading"]


def test_user_values_appear_in_the_document(nda, nda_input):
    text = assembly.assemble(nda, nda_input).to_text()
    assert "Northwind Logistics Pvt Ltd" in text
    assert "Bluefin Analytics LLP" in text
    assert "Karnataka, India" in text
    assert "24 months" in text


def test_dates_are_written_the_way_a_contract_reads(nda, nda_input):
    text = assembly.assemble(nda, nda_input).to_text()
    assert "15 October 2026" in text
    assert "2026-10-15" not in text


def test_iso_date_string_is_formatted_too(nda, nda_input):
    nda_input["effective_date"] = "2026-01-05"
    assert "5 January 2026" in assembly.assemble(nda, nda_input).to_text()


def test_accepted_clause_is_included(nda, nda_input):
    text = assembly.assemble(nda, nda_input, [ACCEPTED]).to_text()
    assert "Data Security" in text
    assert "The Receiving Party shall encrypt all data." in text


def test_rejected_clause_is_not_included(nda, nda_input):
    """Only clauses passed in as accepted may appear. Nothing else."""
    text = assembly.assemble(nda, nda_input, [ACCEPTED]).to_text()
    assert "Non-Compete" not in text
    assert "shall not compete" not in text


def test_no_clauses_still_produces_a_document(nda, nda_input):
    assert len(headings(assembly.assemble(nda, nda_input))) > 0


def test_clauses_are_inserted_before_the_signature_block(nda, nda_input):
    """A clause after the signatures would be outside the agreed text."""
    names = headings(assembly.assemble(nda, nda_input, [ACCEPTED]))
    assert [n for n in names if "Data Security" in n]
    clause_at = next(i for i, n in enumerate(names) if "Data Security" in n)
    signature_at = next(i for i, n in enumerate(names) if "Signatures" in n)
    assert clause_at < signature_at


def test_sections_are_numbered_in_order_including_new_clauses(nda, nda_input):
    names = headings(assembly.assemble(nda, nda_input, [ACCEPTED]))
    numbers = [int(n.split(".")[0]) for n in names]
    assert numbers == list(range(1, len(names) + 1))


def test_the_optional_field_changes_the_wording(nda, nda_input):
    with_scope = assembly.assemble(nda, nda_input).to_text()
    assert "pricing models and customer lists" in with_scope

    nda_input["confidential_scope"] = ""
    without_scope = assembly.assemble(nda, nda_input).to_text()
    assert "pricing models and customer lists" not in without_scope
    assert "Confidential Information means any information" in without_scope


def test_a_missing_optional_key_does_not_crash(nda, nda_input):
    """The Jinja environment is strict, so assembly must fill in blanks itself."""
    del nda_input["confidential_scope"]
    assert assembly.assemble(nda, nda_input).to_text()


def test_the_other_template_also_assembles():
    template = templates.load_template("service_agreement")
    document = assembly.assemble(
        template,
        {
            "client_name": "Northwind Logistics Pvt Ltd",
            "provider_name": "Bluefin Analytics LLP",
            "effective_date": date(2026, 10, 15),
            "services": "build a demand forecasting dashboard",
            "fee_amount": "INR 2,50,000 per month",
            "payment_terms": "within 30 days of invoice",
            "term_months": 12,
            "termination_notice_days": 30,
            "jurisdiction": "Karnataka, India",
        },
    )
    text = document.to_text()
    assert "INR 2,50,000 per month" in text
    assert "30 days' written notice" in text


def test_a_template_referring_to_an_unknown_field_fails_clearly(tmp_path, monkeypatch):
    (tmp_path / "x.json").write_text(
        '{"name":"X","title":"X","fields":[{"id":"a","label":"A","type":"text"}]}', encoding="utf-8"
    )
    (tmp_path / "x.j2").write_text("## Parties\n{{ a }} and {{ unknown_field }}", encoding="utf-8")
    monkeypatch.setattr(templates, "TEMPLATE_DIR", tmp_path)

    template = templates.load_template("x")
    with pytest.raises(assembly.AssemblyError, match="not in its field list"):
        assembly.assemble(template, {"a": "hello"})

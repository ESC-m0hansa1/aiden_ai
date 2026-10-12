
"""Tests for assembling the final document.

Only accepted clauses should be included. Suggested clauses must appear
before the signatures, and all section headings must be numbered in order.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from docugen import assembly, templates
from docugen.llm import Clause


ACCEPTED = Clause(
    title="Data Security",
    body="The Receiving Party shall encrypt all data.",
    rationale="r",
)

REJECTED = Clause(
    title="Non-Compete",
    body="The Receiving Party shall not compete.",
    rationale="r",
)


def headings(document):
    return [block.text for block in document.blocks if block.kind == "heading"]


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

    text = assembly.assemble(nda, nda_input).to_text()

    assert "5 January 2026" in text


def test_accepted_clause_is_included(nda, nda_input):
    text = assembly.assemble(nda, nda_input, [ACCEPTED]).to_text()

    assert "Data Security" in text
    assert "The Receiving Party shall encrypt all data." in text


def test_rejected_clause_is_not_included(nda, nda_input):
    """Only clauses explicitly passed as accepted may appear."""
    text = assembly.assemble(nda, nda_input, [ACCEPTED]).to_text()

    assert "Non-Compete" not in text
    assert "shall not compete" not in text


def test_no_clauses_still_produces_a_document(nda, nda_input):
    document = assembly.assemble(nda, nda_input)

    assert len(headings(document)) > 0


def test_clauses_are_inserted_before_the_signature_block(nda, nda_input):
    names = headings(assembly.assemble(nda, nda_input, [ACCEPTED]))

    clause_at = next(
        i for i, name in enumerate(names) if "Data Security" in name
    )
    signature_at = next(
        i for i, name in enumerate(names) if "Signatures" in name
    )

    assert clause_at < signature_at


def test_sections_are_numbered_in_order_including_new_clauses(
    nda, nda_input
):
    names = headings(assembly.assemble(nda, nda_input, [ACCEPTED]))
    numbers = [int(name.split(".")[0]) for name in names]

    assert numbers == list(range(1, len(names) + 1))


def test_the_optional_field_changes_the_wording(nda, nda_input):
    with_scope = assembly.assemble(nda, nda_input).to_text()

    assert "pricing models and customer lists" in with_scope

    nda_input["confidential_scope"] = ""
    without_scope = assembly.assemble(nda, nda_input).to_text()

    assert "pricing models and customer lists" not in without_scope
    assert "Confidential Information means any information" in without_scope


def test_a_missing_optional_key_does_not_crash(nda, nda_input):
    """Missing optional values should be supplied as empty strings."""
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


def test_a_template_referring_to_an_unknown_field_fails_clearly(
    tmp_path, monkeypatch
):
    (tmp_path / "x.json").write_text(
        '{"name":"X","title":"X",'
        '"fields":[{"id":"a","label":"A","type":"text"}]}',
        encoding="utf-8",
    )

    (tmp_path / "x.j2").write_text(
        "## Parties\n{{ a }} and {{ unknown_field }}",
        encoding="utf-8",
    )

    monkeypatch.setattr(templates, "TEMPLATE_DIR", tmp_path)
    template = templates.load_template("x")

    with pytest.raises(
        assembly.AssemblyError,
        match="not in its field list",
    ):
        assembly.assemble(template, {"a": "hello"})


def test_signature_heading_is_detected_without_blank_line():
    """Headings should be recognized even without surrounding blank lines."""
    blocks = assembly._parse_blocks(
        "## Governing Law\n"
        "This is the governing law.\n"
        "## Signatures\n"
        "Signed by both parties."
    )

    signature = next(
        i for i, block in enumerate(blocks)
        if block.kind == "heading" and block.text == "Signatures"
    )

    assert blocks[signature + 1].text == "Signed by both parties."


def test_clause_body_does_not_repeat_numbered_bold_title(nda, nda_input):
    clause = Clause(
        title="Job-Related Confidentiality Scope",
        body=(
            "1. **Scope of Confidentiality for Job-Related Information**: "
            "The Receiving Party shall protect the information."
        ),
        rationale="Relevant",
    )

    document = assembly.assemble(nda, nda_input, [clause])
    names = headings(document)

    clause_heading = next(
        name for name in names if "Job-Related" in name
    )

    assert clause_heading.startswith("8. ")

    clause_paragraph = next(
        block.text for block in document.blocks
        if (
            block.kind == "paragraph"
            and "shall protect the information" in block.text
        )
    )

    assert not clause_paragraph.startswith("1. **")
    assert "**Scope of Confidentiality" not in clause_paragraph


def test_accepted_clause_precedes_signatures_with_single_newlines(
    nda,
):
    """Insertion still works when rendered headings have single newlines."""

    class BodyTemplate:
        def render(self, **values):
            return (
                "## Parties\n"
                "Parties text.\n"
                "## Governing Law\n"
                "Law text.\n"
                "## Signatures\n"
                "Signed by both parties."
            )

    simple_template = SimpleNamespace(
        id=nda.id,
        title=nda.title,
        fields=nda.fields,
        subtitle_template=nda.subtitle_template,
        body_template=BodyTemplate(),
    )

    user_input = {field.id: "value" for field in nda.fields}

    document = assembly.assemble(
        simple_template,
        user_input,
        [ACCEPTED],
    )

    names = headings(document)

    clause_at = next(
        i for i, name in enumerate(names) if "Data Security" in name
    )
    signature_at = next(
        i for i, name in enumerate(names) if "Signatures" in name
    )

    assert clause_at < signature_at

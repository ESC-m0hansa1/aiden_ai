"""Tests for DOCX export.

These open the generated file again with python-docx and read the text back,
rather than only checking that some bytes were produced.
"""

import io

from docx import Document as DocxDocument

from docugen import assembly, export


def docx_text(data: bytes) -> str:
    return "\n".join(p.text for p in DocxDocument(io.BytesIO(data)).paragraphs)


def test_output_is_a_real_docx_file(nda, nda_input):
    data = export.to_docx_bytes(assembly.assemble(nda, nda_input))
    # .docx is a zip archive, so it starts with the zip magic number.
    assert data[:2] == b"PK"
    assert len(data) > 1000


def test_the_document_can_be_reopened_and_read(nda, nda_input):
    data = export.to_docx_bytes(assembly.assemble(nda, nda_input))
    text = docx_text(data)
    assert "Northwind Logistics Pvt Ltd" in text
    assert "Bluefin Analytics LLP" in text
    assert "15 October 2026" in text


def test_the_title_is_in_the_document(nda, nda_input):
    text = docx_text(export.to_docx_bytes(assembly.assemble(nda, nda_input)))
    assert "NON-DISCLOSURE AGREEMENT" in text


def test_an_accepted_clause_survives_the_export(nda, nda_input):
    from docugen.llm import Clause

    clause = Clause(title="Data Security", body="The Receiving Party shall encrypt all data.", rationale="r")
    text = docx_text(export.to_docx_bytes(assembly.assemble(nda, nda_input, [clause])))
    assert "Data Security" in text
    assert "The Receiving Party shall encrypt all data." in text


def test_the_disclaimer_is_in_the_exported_file(nda, nda_input):
    """The warning has to travel with the document, not just sit in the UI."""
    text = docx_text(export.to_docx_bytes(assembly.assemble(nda, nda_input)))
    assert "not legal advice" in text


def test_filename_is_safe_and_readable(nda, nda_input):
    name = export.suggested_filename(assembly.assemble(nda, nda_input))
    assert name == "non-disclosure_agreement.docx"
    assert "/" not in name and "\\" not in name

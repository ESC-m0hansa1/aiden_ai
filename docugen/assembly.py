
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re

import jinja2

from docugen.llm import Clause
from docugen.templates import Template


# Suggested clauses must be inserted before the signature section.
SIGNATURE_HEADING = "Signatures"


class AssemblyError(Exception):
    """Raised when a document template cannot be assembled."""


@dataclass(frozen=True)
class Block:
    kind: str  # "heading" or "paragraph"
    text: str


@dataclass(frozen=True)
class Document:
    title: str
    subtitle: str
    blocks: tuple[Block, ...]

    def to_text(self) -> str:
        lines = [self.title]

        if self.subtitle:
            lines.append(self.subtitle)

        lines.append("")

        for block in self.blocks:
            lines.append(block.text)
            lines.append("")

        return "\n".join(lines).strip() + "\n"


def assemble(
    template: Template,
    user_input: dict,
    accepted_clauses: list[Clause] | None = None,
) -> Document:
    """Render a template, insert accepted clauses, and number its sections."""
    values = _render_values(template, user_input)

    try:
        body_text = template.body_template.render(**values)
        subtitle = template.subtitle_template.render(**values)
    except jinja2.UndefinedError as exc:
        raise AssemblyError(
            f"Template '{template.id}' refers to a field that is not "
            f"in its field list: {exc}"
        ) from exc

    blocks = _parse_blocks(body_text)
    blocks = _insert_clauses(blocks, accepted_clauses or [])
    blocks = _number_headings(blocks)

    return Document(
        title=template.title,
        subtitle=subtitle.strip(),
        blocks=tuple(blocks),
    )


def _render_values(template: Template, user_input: dict) -> dict:
    """Prepare and format the user-provided template values."""
    values = {}

    for field in template.fields:
        raw = user_input.get(field.id)

        if raw is None:
            values[field.id] = ""
        elif field.type == "date":
            values[field.id] = _format_date(raw)
        else:
            values[field.id] = str(raw).strip()

    return values


def _format_date(raw) -> str:
    """Format dates as, for example, '15 October 2026'."""
    if isinstance(raw, datetime):
        raw = raw.date()

    if isinstance(raw, date):
        return f"{raw.day} {raw.strftime('%B %Y')}"

    try:
        parsed = datetime.strptime(
            str(raw).strip(), "%Y-%m-%d"
        ).date()
    except ValueError:
        # Preserve the input if validation has not already rejected it.
        return str(raw).strip()

    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _parse_blocks(body_text: str) -> list[Block]:
    """Parse headings and paragraphs without requiring blank lines.

    A heading beginning with '## ' is recognized even when Jinja whitespace
    control removes the blank line before or after it.
    """
    blocks: list[Block] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            paragraph = "\n".join(
                line.strip() for line in paragraph_lines
            ).strip()

            if paragraph:
                blocks.append(Block("paragraph", paragraph))

            paragraph_lines.clear()

    for raw_line in body_text.splitlines():
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            continue

        if line.startswith("## "):
            flush_paragraph()
            heading = line[3:].strip()

            if heading:
                blocks.append(Block("heading", heading))

            continue

        paragraph_lines.append(line)

    flush_paragraph()
    return blocks


def _insert_clauses(
    blocks: list[Block],
    clauses: list[Clause],
) -> list[Block]:
    """Insert only supplied, accepted clauses before the signatures."""
    if not clauses:
        return blocks

    new_sections: list[Block] = []

    for clause in clauses:
        title = clause.title.strip()

        if title:
            new_sections.append(Block("heading", title))

        for paragraph in clause.body.splitlines():
            paragraph = paragraph.strip()
            paragraph = _clean_clause_body_lead(paragraph)

            if paragraph:
                new_sections.append(Block("paragraph", paragraph))

    if not new_sections:
        return blocks

    for index, block in enumerate(blocks):
        if (
            block.kind == "heading"
            and block.text.strip().lower() == SIGNATURE_HEADING.lower()
        ):
            return blocks[:index] + new_sections + blocks[index:]

    # Templates without a signature heading receive clauses at the end.
    return blocks + new_sections


def _clean_clause_body_lead(text: str) -> str:
    """Remove a duplicated numbered and bold title at the start of a body.

    Example:
    '1. **Confidentiality Scope**: The Receiving Party shall...'

    becomes:
    'The Receiving Party shall...'

    The clause's actual heading and section number are generated separately.
    """
    return re.sub(
        r"^\s*\d+\.\s+\*\*[^*]+\*\*\s*:\s*",
        "",
        text,
        count=1,
    ).strip()


def _number_headings(blocks: list[Block]) -> list[Block]:
    """Number all headings sequentially, including inserted clauses."""
    numbered: list[Block] = []
    counter = 0

    for block in blocks:
        if block.kind == "heading":
            counter += 1
            heading = _remove_existing_number(block.text.strip())

            numbered.append(
                Block("heading", f"{counter}. {heading}")
            )
        else:
            numbered.append(block)

    return numbered


def _remove_existing_number(heading: str) -> str:
    """Remove an existing leading integer section number."""
    prefix, separator, remainder = heading.partition(". ")

    if separator and prefix.isdigit():
        return remainder.strip()

    return heading


from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import jinja2

from docugen.llm import Clause
from docugen.templates import Template


# Where suggested clauses are inserted. They belong in the body of the
# agreement, not after the signature block.
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
    values = _render_values(template, user_input)

    try:
        body_text = template.body_template.render(**values)
        subtitle = template.subtitle_template.render(**values)
    except jinja2.UndefinedError as exc:
        # A template references a field that was not declared.
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
    blocks: list[Block] = []

    # Split on blank lines while preserving multiline paragraphs.
    for chunk in body_text.split("\n\n"):
        chunk = chunk.strip()

        if not chunk:
            continue

        lines = chunk.splitlines()

        # A heading must occupy its own line.
        if len(lines) == 1 and lines[0].strip().startswith("## "):
            heading = lines[0].strip()[3:].strip()

            if heading:
                blocks.append(Block("heading", heading))

            continue

        paragraph = "\n".join(line.strip() for line in lines).strip()

        if paragraph:
            blocks.append(Block("paragraph", paragraph))

    return blocks


def _insert_clauses(
    blocks: list[Block],
    clauses: list[Clause],
) -> list[Block]:
    if not clauses:
        return blocks

    new_sections: list[Block] = []

    for clause in clauses:
        title = clause.title.strip()

        if title:
            new_sections.append(Block("heading", title))

        for paragraph in clause.body.splitlines():
            paragraph = paragraph.strip()

            if paragraph:
                new_sections.append(Block("paragraph", paragraph))

    if not new_sections:
        return blocks

    # Insert before the signature section, if it exists.
    for index, block in enumerate(blocks):
        if (
            block.kind == "heading"
            and block.text.strip().lower() == SIGNATURE_HEADING.lower()
        ):
            return blocks[:index] + new_sections + blocks[index:]

    # If no signature heading exists, append the clauses.
    return blocks + new_sections


def _number_headings(blocks: list[Block]) -> list[Block]:
    numbered: list[Block] = []
    counter = 0

    for block in blocks:
        if block.kind == "heading":
            counter += 1

            # Avoid numbering a heading twice if this function is reapplied.
            heading = block.text.strip()
            heading = _remove_existing_number(heading)

            numbered.append(
                Block("heading", f"{counter}. {heading}")
            )
        else:
            numbered.append(block)

    return numbered


def _remove_existing_number(heading: str) -> str:
    """Remove a leading integer section number, if present."""
    prefix, separator, remainder = heading.partition(". ")

    if separator and prefix.isdigit():
        return remainder.strip()

    return heading

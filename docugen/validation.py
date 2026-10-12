"""Validation of what the legal assistant typed, before we build anything.

The rule set is deliberately small. This is a drafting aid, not a legal
compliance engine, so we check that the inputs are present and shaped
sensibly and leave the legal judgement to the person signing the document.

validate() returns a dict of {field_id: message}. An empty dict means valid.
Returning messages rather than raising lets the UI show every problem at once
instead of making the user fix them one at a time.
"""

from __future__ import annotations

from datetime import date, datetime

from docugen.templates import Field, Template

# Accepted when a date arrives as text (the Streamlit date picker gives us a
# real date object, but the CLI-style tests and any future API would send text).
DATE_FORMAT = "%Y-%m-%d"


def validate(template: Template, user_input: dict) -> dict[str, str]:
    """Check user_input against the template's field spec.

    Returns {field_id: friendly message} for every problem found.
    """
    errors: dict[str, str] = {}

    for field in template.fields:
        raw = user_input.get(field.id)
        message = _check_field(field, raw)
        if message:
            errors[field.id] = message

    return errors


def _check_field(field: Field, raw) -> str | None:
    """Return a problem message for one field, or None if it is fine."""
    if _is_blank(raw):
        if field.required:
            return f"{field.label} is required."
        return None

    if field.type in ("text", "textarea"):
        return _check_text(field, str(raw).strip())
    if field.type == "integer":
        return _check_integer(field, raw)
    if field.type == "date":
        return _check_date(field, raw)

    # A template declared a type templates.py accepted but we forgot to handle.
    # Better to say so than to silently let it through unchecked.
    return f"{field.label} has an unsupported field type '{field.type}'."


def _is_blank(raw) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _check_text(field: Field, value: str) -> str | None:
    if field.max_length is not None and len(value) > field.max_length:
        return f"{field.label} is too long ({len(value)} characters, maximum {field.max_length})."
    return None


def _check_integer(field: Field, raw) -> str | None:
    try:
        # int(str) rather than int(float) on purpose: "12.5 months" should be
        # rejected rather than silently rounded to 12.
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return f"{field.label} must be a whole number."

    if field.min is not None and value < field.min:
        return f"{field.label} must be at least {field.min}."
    if field.max is not None and value > field.max:
        return f"{field.label} must be {field.max} or less."
    return None


def _check_date(field: Field, raw) -> str | None:
    if isinstance(raw, (date, datetime)):
        return None
    try:
        datetime.strptime(str(raw).strip(), DATE_FORMAT)
    except ValueError:
        return f"{field.label} must be a date in YYYY-MM-DD format."
    return None

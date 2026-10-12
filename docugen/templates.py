"""Loading of document templates.

A template is two files in the templates/ folder:

    <id>.json   metadata plus the list of input fields the UI should ask for
    <id>.j2     the document body, written as a Jinja2 template

Keeping templates as data rather than as Python means adding a new document
type is two text files and no code change at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import jinja2

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

# The field types a template is allowed to declare. The UI switches on these
# to pick a widget, and the validator switches on them to pick a check.
FIELD_TYPES = {"text", "textarea", "date", "integer"}


class UnknownTemplateError(Exception):
    """Raised when a template id does not exist on disk."""


class TemplateFormatError(Exception):
    """Raised when a template file exists but is not usable."""


@dataclass(frozen=True)
class Field:
    """One input the legal assistant has to fill in."""

    id: str
    label: str
    type: str
    required: bool = False
    help: str = ""
    placeholder: str = ""
    max_length: int | None = None
    min: int | None = None
    max: int | None = None
    default: int | None = None


@dataclass(frozen=True)
class Template:
    """A document type: what to ask for, and how to lay the answers out."""

    id: str
    name: str
    description: str
    title: str
    fields: tuple[Field, ...]
    # Kept as text for tests and debugging ...
    subtitle_source: str
    body_source: str
    # ... and pre-compiled, because compiling is the slow part and the whole
    # Template object is cached.
    subtitle_template: jinja2.Template
    body_template: jinja2.Template

    def field(self, field_id: str) -> Field:
        for f in self.fields:
            if f.id == field_id:
                return f
        raise KeyError(field_id)


# Streamlit re-runs the entire script on every widget interaction, so without a
# cache we would re-read and re-parse both template files on every keystroke.
# Templates are read-only and there are only a handful of them, so a plain dict
# is the right size of solution - no TTL, no eviction, no external cache.
_cache: dict[str, Template] = {}

# autoescape stays off: we are producing plain text for a Word document, not
# HTML, so escaping would corrupt characters like & in company names. The
# preview in the UI is rendered as text, never as HTML, for the same reason.
_env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)


def clear_cache() -> None:
    """Drop cached templates. Used by tests, and handy if a template is edited."""
    _cache.clear()


def available_template_ids() -> list[str]:
    """Ids of every template on disk, sorted for a stable UI order."""
    return sorted(path.stem for path in TEMPLATE_DIR.glob("*.json"))


def load_template(template_id: str) -> Template:
    """Load one template by id, using the cache when we have already read it."""
    if template_id in _cache:
        return _cache[template_id]

    spec_path = TEMPLATE_DIR / f"{template_id}.json"
    body_path = TEMPLATE_DIR / f"{template_id}.j2"
    if not spec_path.exists() or not body_path.exists():
        raise UnknownTemplateError(
            f"No template called '{template_id}'. Available: {', '.join(available_template_ids())}"
        )

    template = _build_template(template_id, spec_path, body_path)
    _cache[template_id] = template
    return template


def _build_template(template_id: str, spec_path: Path, body_path: Path) -> Template:
    """Parse the two files into a Template, failing loudly if they are malformed."""
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateFormatError(f"{spec_path.name} is not valid JSON: {exc}") from exc

    for key in ("name", "title", "fields"):
        if key not in spec:
            raise TemplateFormatError(f"{spec_path.name} is missing the '{key}' key")

    fields = tuple(_build_field(raw, spec_path.name) for raw in spec["fields"])
    subtitle_source = spec.get("subtitle", "")
    body_source = body_path.read_text(encoding="utf-8")

    try:
        subtitle_template = _env.from_string(subtitle_source)
        body_template = _env.from_string(body_source)
    except jinja2.TemplateSyntaxError as exc:
        raise TemplateFormatError(f"{body_path.name} has a template error on line {exc.lineno}: {exc.message}") from exc

    return Template(
        id=template_id,
        name=spec["name"],
        description=spec.get("description", ""),
        title=spec["title"],
        fields=fields,
        subtitle_source=subtitle_source,
        body_source=body_source,
        subtitle_template=subtitle_template,
        body_template=body_template,
    )


def _build_field(raw: dict, source_name: str) -> Field:
    """Turn one entry of the JSON 'fields' list into a Field."""
    for key in ("id", "label", "type"):
        if key not in raw:
            raise TemplateFormatError(f"{source_name} has a field missing its '{key}'")
    if raw["type"] not in FIELD_TYPES:
        raise TemplateFormatError(
            f"{source_name} field '{raw['id']}' has unsupported type '{raw['type']}'. "
            f"Supported: {', '.join(sorted(FIELD_TYPES))}"
        )

    return Field(
        id=raw["id"],
        label=raw["label"],
        type=raw["type"],
        required=raw.get("required", False),
        help=raw.get("help", ""),
        placeholder=raw.get("placeholder", ""),
        max_length=raw.get("max_length"),
        min=raw.get("min"),
        max=raw.get("max"),
        default=raw.get("default"),
    )

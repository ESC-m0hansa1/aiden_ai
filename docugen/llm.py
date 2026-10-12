

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from docugen.templates import Template

load_dotenv()

DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_MODEL = "ministral-8b-latest"
DEFAULT_TIMEOUT_S = 45
DEFAULT_MAX_TOKENS = 900

# Low but not zero. We want repeatable, conservative drafting rather than
# creative variety, but identical output on every run would make the feature
# look fake during a demo.
TEMPERATURE = 0.2


@dataclass(frozen=True)
class Clause:
    """One suggested clause, before the user has decided on it."""

    title: str
    body: str
    rationale: str


class LLMError(Exception):
    """Base class for anything that can go wrong talking to the model.

    The message on these exceptions is written for the end user, so the UI can
    show str(exc) directly instead of inventing its own wording.
    """


class MissingAPIKeyError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMServiceError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout_s: int
    max_tokens: int


def load_config() -> LLMConfig:
    """Read provider settings from the environment.

    Raises MissingAPIKeyError rather than returning a half-built config, so the
    failure happens at the point of use with a message that says how to fix it.
    """
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKeyError(
            "No LLM_API_KEY is configured, so clause suggestions are turned off. "
            "Copy .env.example to .env and add your key. You can still fill in the "
            "form and download the document without suggestions."
        )

    return LLMConfig(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        timeout_s=_int_from_env("LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S),
        max_tokens=_int_from_env("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
    )


def _int_from_env(name: str, fallback: int) -> int:
    """Read an int setting, falling back if it is missing or not a number."""
    try:
        return int(os.getenv(name, "").strip())
    except ValueError:
        return fallback


def is_configured() -> bool:
    """True when a key is present. Lets the UI hide the button instead of
    showing one that is guaranteed to fail."""
    return bool(os.getenv("LLM_API_KEY", "").strip())


def existing_clause_headings(template: Template) -> list[str]:
    """Headings already in the template body.

    Passed to the model so it proposes genuinely additional clauses rather than
    restating the boilerplate that is already there.
    """
    headings = re.findall(r"^##\s*\d*\.?\s*(.+)$", template.body_source, flags=re.MULTILINE)
    return [h.strip() for h in headings if h.strip().lower() != "signatures"]


def build_prompt(template: Template, user_input: dict, count: int = 3) -> str:
    """Build the user message.

    The real field values go in, which is what makes the suggestions specific
    to this agreement rather than generic filler.
    """
    detail_lines = []
    for field in template.fields:
        value = user_input.get(field.id)
        if value is None or str(value).strip() == "":
            continue
        detail_lines.append(f"- {field.label}: {value}")

    already_covered = existing_clause_headings(template)

    return (
        f"You are helping a legal assistant prepare a {template.name}.\n\n"
        f"Details of this specific agreement:\n"
        + "\n".join(detail_lines)
        + "\n\n"
        f"The standard template already contains these clauses, so do not repeat them:\n"
        + "\n".join(f"- {h}" for h in already_covered)
        + "\n\n"
        f"Suggest {count} additional clauses that are genuinely relevant to THIS agreement, "
        f"based on the details above. For each clause give a short title, the clause text "
        f"written in the same formal register as a contract, and one sentence explaining why "
        f"it is relevant here.\n"
        f"Do not put clause numbers in the title or the body - the application numbers "
        f"sections itself once the user has chosen which clauses to keep.\n\n"
        'Return only JSON in exactly this shape:\n'
        '{"suggestions": [{"title": "...", "body": "...", "rationale": "..."}]}'
    )


SYSTEM_PROMPT = (
    "You are a careful legal drafting assistant. You propose optional contract clauses "
    "for a qualified human to review. You never claim legal advice, and you always "
    "respond with valid JSON only."
)


def suggest_clauses(
    template: Template,
    user_input: dict,
    count: int = 3,
    config: LLMConfig | None = None,
) -> list[Clause]:
    """Ask the model for clauses relevant to this agreement.

    Raises a subclass of LLMError on any failure. The caller is expected to
    catch LLMError and carry on without suggestions - they are an enhancement,
    not a precondition for producing the document.
    """
    config = config or load_config()
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(template, user_input, count)},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": config.max_tokens,
        # Supported by Mistral, Groq and OpenAI. It does not remove the need to
        # handle bad JSON below - it just makes it much rarer.
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            f"{config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
            timeout=config.timeout_s,
        )
    except requests.Timeout as exc:
        raise LLMTimeoutError(
            f"The model took longer than {config.timeout_s} seconds to answer. "
            "Try again, or carry on without suggestions."
        ) from exc
    except requests.RequestException as exc:
        raise LLMServiceError(
            "Could not reach the language model. Check your internet connection "
            "and the LLM_BASE_URL setting."
        ) from exc

    _raise_for_status(response, config)
    return _parse_suggestions(response)


def _raise_for_status(response: requests.Response, config: LLMConfig) -> None:
    """Turn an HTTP error into an LLMError carrying a message a user can act on."""
    if response.ok:
        return

    if response.status_code == 429:
        # Deliberately not auto-retried. The free-tier limit is per minute, so a
        # silent retry would spend another request and leave the UI looking hung.
        raise LLMRateLimitError(
            "The model provider is rate limiting us (free tier). Wait a few seconds "
            "and press the button again."
        )
    if response.status_code in (401, 403):
        raise MissingAPIKeyError(
            "The language model rejected our API key. Check LLM_API_KEY in your .env file."
        )
    if response.status_code == 404:
        raise LLMServiceError(
            f"The provider does not recognise the model '{config.model}'. "
            "Check LLM_MODEL in your .env file."
        )
    raise LLMServiceError(
        f"The language model returned an error (HTTP {response.status_code}). Please try again."
    )


def _parse_suggestions(response: requests.Response) -> list[Clause]:
    """Pull the clause list out of the response, rejecting anything malformed."""
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise LLMResponseError(
            "The language model sent back a response we could not read. Please try again."
        ) from exc

    try:
        data = json.loads(_strip_code_fence(content))
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            "The language model did not return valid JSON. Please try again."
        ) from exc

    if not isinstance(data, dict) or not isinstance(data.get("suggestions"), list):
        raise LLMResponseError(
            "The language model returned an unexpected format. Please try again."
        )

    clauses = [c for c in (_build_clause(item) for item in data["suggestions"]) if c]
    if not clauses:
        raise LLMResponseError(
            "The language model did not return any usable clauses. Please try again."
        )
    return clauses


def _build_clause(item) -> Clause | None:
    """One suggestion, or None if it is not shaped like a clause.

    Skipping a bad entry is better than failing the whole batch: two good
    clauses out of three is still useful to the person drafting.
    """
    if not isinstance(item, dict):
        return None
    title = str(item.get("title", "")).strip()
    body = str(item.get("body", "")).strip()
    if not title or not body:
        return None
    return Clause(title=title, body=body, rationale=str(item.get("rationale", "")).strip())


def _strip_code_fence(text: str) -> str:
    """Remove a ```json ... ``` wrapper if the model added one anyway."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()

"""Tests for the language model integration.

Every test here mocks requests.post. The suite never makes a network call, so
it runs identically on a machine with no API key and in CI. What is being
tested is our handling of the provider's answer - the good case and, mostly,
the bad ones.
"""

import json
from unittest.mock import patch

import pytest
import requests

from docugen import llm


class FakeResponse:
    """Just enough of requests.Response for the code under test."""

    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


def chat_response(content: str) -> FakeResponse:
    """Wrap model output in the envelope an OpenAI-compatible API returns."""
    return FakeResponse(payload={"choices": [{"message": {"content": content}}]})


GOOD_JSON = json.dumps(
    {
        "suggestions": [
            {"title": "Data Security", "body": "The Receiving Party shall...", "rationale": "Pilot handles data."},
            {"title": "Non-Solicitation", "body": "Neither Party shall...", "rationale": "Staff overlap."},
        ]
    }
)

CONFIG = llm.LLMConfig(
    api_key="test-key",
    base_url="https://example.test/v1",
    model="test-model",
    timeout_s=10,
    max_tokens=500,
)


# --- the prompt -----------------------------------------------------------


def test_prompt_contains_the_users_actual_values(nda, nda_input):
    """This is what makes suggestions specific rather than generic boilerplate."""
    prompt = llm.build_prompt(nda, nda_input)
    assert "Northwind Logistics Pvt Ltd" in prompt
    assert "evaluating a supply-chain forecasting pilot" in prompt
    assert "Karnataka, India" in prompt


def test_prompt_lists_clauses_already_in_the_template(nda, nda_input):
    """So the model proposes additions instead of repeating the boilerplate."""
    prompt = llm.build_prompt(nda, nda_input)
    assert "Governing Law" in prompt
    assert "Confidential Information" in prompt


def test_prompt_skips_blank_optional_fields(nda, nda_input):
    nda_input["confidential_scope"] = ""
    prompt = llm.build_prompt(nda, nda_input)
    assert "Specific confidential information" not in prompt


def test_existing_headings_exclude_signatures(nda):
    assert "Signatures" not in llm.existing_clause_headings(nda)


# --- the happy path -------------------------------------------------------


def test_valid_response_becomes_clauses(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=chat_response(GOOD_JSON)):
        clauses = llm.suggest_clauses(nda, nda_input, config=CONFIG)

    assert [c.title for c in clauses] == ["Data Security", "Non-Solicitation"]
    assert clauses[0].rationale == "Pilot handles data."


def test_json_wrapped_in_a_code_fence_is_still_read(nda, nda_input):
    """Some providers wrap JSON in ```json even when asked not to."""
    fenced = f"```json\n{GOOD_JSON}\n```"
    with patch("docugen.llm.requests.post", return_value=chat_response(fenced)):
        clauses = llm.suggest_clauses(nda, nda_input, config=CONFIG)
    assert len(clauses) == 2


def test_one_malformed_suggestion_does_not_lose_the_good_ones(nda, nda_input):
    """Two usable clauses out of three is still useful to the drafter."""
    mixed = json.dumps(
        {
            "suggestions": [
                {"title": "Good One", "body": "Text here.", "rationale": "r"},
                {"title": "Missing body"},
                "not even an object",
            ]
        }
    )
    with patch("docugen.llm.requests.post", return_value=chat_response(mixed)):
        clauses = llm.suggest_clauses(nda, nda_input, config=CONFIG)
    assert [c.title for c in clauses] == ["Good One"]


# --- the failure paths ----------------------------------------------------


def test_invalid_json_raises_response_error(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=chat_response("I'm sorry, I can't.")):
        with pytest.raises(llm.LLMResponseError):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_json_of_the_wrong_shape_raises_response_error(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=chat_response('{"clauses": []}')):
        with pytest.raises(llm.LLMResponseError):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_all_suggestions_unusable_raises_response_error(nda, nda_input):
    empty = json.dumps({"suggestions": [{"title": "", "body": ""}]})
    with patch("docugen.llm.requests.post", return_value=chat_response(empty)):
        with pytest.raises(llm.LLMResponseError):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_rate_limit_is_reported_as_such(nda, nda_input):
    """429 is a real condition on the free tier, not a hypothetical."""
    with patch("docugen.llm.requests.post", return_value=FakeResponse(status_code=429)):
        with pytest.raises(llm.LLMRateLimitError, match="rate limiting"):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_rejected_key_is_reported_as_a_key_problem(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=FakeResponse(status_code=401)):
        with pytest.raises(llm.MissingAPIKeyError, match="LLM_API_KEY"):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_unknown_model_mentions_the_setting(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=FakeResponse(status_code=404)):
        with pytest.raises(llm.LLMServiceError, match="LLM_MODEL"):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_server_error_is_reported_as_a_service_error(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=FakeResponse(status_code=500)):
        with pytest.raises(llm.LLMServiceError):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_timeout_is_reported_as_a_timeout(nda, nda_input):
    with patch("docugen.llm.requests.post", side_effect=requests.Timeout()):
        with pytest.raises(llm.LLMTimeoutError, match="10 seconds"):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_connection_failure_is_reported(nda, nda_input):
    with patch("docugen.llm.requests.post", side_effect=requests.ConnectionError()):
        with pytest.raises(llm.LLMServiceError, match="Could not reach"):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_unreadable_envelope_raises_response_error(nda, nda_input):
    with patch("docugen.llm.requests.post", return_value=FakeResponse(raise_on_json=True)):
        with pytest.raises(llm.LLMResponseError):
            llm.suggest_clauses(nda, nda_input, config=CONFIG)


def test_every_failure_is_an_llm_error(nda, nda_input):
    """The UI catches LLMError once, so every failure must inherit from it."""
    for error in (
        llm.MissingAPIKeyError,
        llm.LLMTimeoutError,
        llm.LLMRateLimitError,
        llm.LLMServiceError,
        llm.LLMResponseError,
    ):
        assert issubclass(error, llm.LLMError)


# --- configuration --------------------------------------------------------


def test_missing_api_key_raises_with_instructions(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(llm.MissingAPIKeyError, match=".env"):
        llm.load_config()


def test_is_configured_reflects_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    assert llm.is_configured() is False
    monkeypatch.setenv("LLM_API_KEY", "a-key")
    assert llm.is_configured() is True


def test_config_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "a-key")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    config = llm.load_config()
    assert config.base_url == llm.DEFAULT_BASE_URL
    assert config.model == llm.DEFAULT_MODEL


def test_a_non_numeric_timeout_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "a-key")
    monkeypatch.setenv("LLM_TIMEOUT_S", "soon")
    assert llm.load_config().timeout_s == llm.DEFAULT_TIMEOUT_S

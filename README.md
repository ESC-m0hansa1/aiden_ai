# DocuGenAI

Generate standard legal documents from templates, with optional AI-suggested clauses
that a human has to approve before they go in.

Built for the AidenAI AI Engineer build round.

The user I had in mind is a legal assistant who produces the same handful of agreements
over and over, and wants the boilerplate filled in correctly and quickly — not a tool
that invents contracts.

---

## What it does

1. Pick a document type (NDA or Service Agreement).
2. Fill in the details — parties, dates, term, jurisdiction, and so on.
3. Optionally press **Suggest clauses**. A language model reads the details you entered
   and proposes extra clauses relevant to *this* agreement.
4. Tick the ones you want. Anything you don't tick never reaches the document.
5. Watch the preview update, then download a `.docx`.

---

## The one design decision that drove everything else

**The model does not write the contract. It suggests additions to a template a human wrote.**

The finished document is always assembled from a reviewed template plus validated input.
Model output can only enter it through a checkbox the user ticked. There is no code path
where unreviewed generated text ends up in a downloaded document — `test_rejected_clause_is_not_included`
in `tests/test_assembly.py` exists specifically to keep it that way.

For legal documents that matters more than flexibility. A free-form generated contract is
impressive in a demo and indefensible in practice: you cannot tell a legal assistant that
clause 7 is correct because the model usually gets it right.

---

## Tech stack

| Choice | Why |
|---|---|
| **Streamlit** | Single-user internal tool. Gives a working UI with no frontend build, no bundler, no separate API. FastAPI + React would have been two services and most of the six hours. |
| **Jinja2** | Templates need placeholders and a couple of conditionals. Jinja does that; a hand-rolled `str.replace` loop would have grown into a worse version of Jinja. |
| **python-docx** | Writes real `.docx` files, pure Python, no Word or LibreOffice needed on the machine. |
| **requests** | The provider is OpenAI-compatible, so one `POST` is the whole integration. A vendor SDK would have locked the app to one provider for no benefit. |
| **pytest** | Standard. 72 tests, all offline. |

Deliberately **not** used: no database (nothing needs persisting), no authentication (explicitly
out of scope in the brief), no LangChain or agent framework (one prompt and one HTTP call do not
need an orchestration layer), no vector store (there is nothing to retrieve).

I also skipped Pydantic, which I'd normally reach for. Fields are declared dynamically by each
template's JSON, so I'd have been building Pydantic models at runtime from a spec — more moving
parts than the ~70-line validator in `docugen/validation.py` that reads the same spec directly.

---

## Architecture

```
user input → validation → template render → LLM suggestions → user accepts/rejects → assembly → DOCX
```

```
app.py                  Streamlit UI. Thin: collects input, shows results, handles buttons.
docugen/
  templates.py          Loads <id>.json + <id>.j2 from templates/. Caches parsed templates.
  validation.py         Checks input against the template's field spec. Returns messages.
  llm.py                OpenAI-compatible client, prompt building, JSON parsing, typed errors.
  assembly.py           Renders the template, inserts accepted clauses, numbers sections.
  export.py             Document → .docx bytes.
templates/
  nda.json / nda.j2
  service_agreement.json / service_agreement.j2
tests/                  72 tests. The model is mocked; nothing here touches the network.
  test_app.py           Drives the Streamlit app headlessly via AppTest.
```

**Nothing in `docugen/` imports Streamlit.** That's the rule that makes the logic testable
without starting a web server, and it's why the test suite runs in under a second.

### Templates are data, not code

A document type is two text files: a `.json` listing the fields to ask for, and a `.j2` holding
the body text. The UI builds its form by looping over that field list, so **adding a third
document type requires no Python changes at all** — drop two files in `templates/` and it appears
in the dropdown with the right inputs and validation.

### Section numbering happens after assembly

The templates have unnumbered headings (`## Termination`). `assembly.py` numbers them once the
accepted clauses have been inserted. I did it this way after realising that numbering inside the
templates breaks the moment a user accepts a clause — every later section would be misnumbered.
Accepted clauses are inserted *before* the signature block, not appended, because text after the
signatures isn't part of what was agreed.

---

## Setup

Requires Python 3.11+. Developed and tested on Python 3.14.0, Windows.

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Then set up configuration:

```bash
cp .env.example .env
```

Open `.env` and paste your API key into `LLM_API_KEY`. A free key from
[console.mistral.ai](https://console.mistral.ai) works. `.env` is gitignored and no key is
committed anywhere in this repository.

Any OpenAI-compatible provider works — the base URL and model are both settings:

```bash
LLM_BASE_URL=https://api.groq.com/openai/v1    # Groq
LLM_BASE_URL=http://localhost:11434/v1         # local Ollama
```

**The app runs without a key.** Suggestions are disabled and the sidebar says so, but you can
still fill in the form, preview and download. Clause suggestions are an enhancement, not a
prerequisite for producing a document.

## Run

```bash
streamlit run app.py
```

Then open http://localhost:8501.

## Test

```bash
pytest
```

72 tests, a few seconds, no network access required.

The suite is in two halves. Most of it tests the `docugen` package directly, with
`requests.post` mocked — the failure paths get more attention than the happy path, because
that's where the bugs live. The rest (`tests/test_app.py`) runs `app.py` headlessly through
Streamlit's `AppTest` harness and checks the things unit tests structurally cannot: that the app
loads at all, that the form is built from the field spec, that an invalid form offers no
download, and that a suggested clause reaches the document only when its checkbox is ticked.

---

## Example

Template: **Non-Disclosure Agreement**

| Field | Value |
|---|---|
| Disclosing party | Northwind Logistics Pvt Ltd |
| Receiving party | Bluefin Analytics LLP |
| Effective date | 2026-10-15 |
| Purpose | evaluating a supply-chain forecasting pilot |
| Term | 24 months |
| Jurisdiction | Karnataka, India |

Clauses the model suggested for that input:

- *Data Security and Access Controls*
- *Third-Party Restrictions and Subcontracting*
- *Pilot-Specific Limitations and Non-Competition*

Those are specific to a data-handling pilot — they are not what you'd get for a generic NDA,
which is the point of feeding the real field values into the prompt. Accepting the first two
produced an 8-section agreement with the new clauses at 8 and 9, ahead of the signature block,
and the third suggestion absent from the file.

---

## Error handling

| What goes wrong | What the user sees |
|---|---|
| Required field blank | A list of every problem at once, and the preview is held back until they're fixed |
| Term isn't a whole number | "Term (months) must be a whole number." |
| Date in the wrong format | "Effective date must be a date in YYYY-MM-DD format." |
| No API key configured | Sidebar warning; the suggest button is hidden; everything else still works |
| Provider rate-limits us (HTTP 429) | "The model provider is rate limiting us (free tier). Wait a few seconds and press the button again." |
| Key rejected (401/403) | "The language model rejected our API key. Check LLM_API_KEY in your .env file." |
| Request times out | A warning naming the timeout; the form stays usable |
| Model returns something that isn't valid JSON | "The language model did not return valid JSON. Please try again." |
| One suggestion out of three is malformed | The other two are shown. A bad entry is skipped, not fatal. |

Two things I was deliberate about:

**Validation returns a dict of problems rather than raising.** The UI shows every error at once
instead of making someone fix them one at a time.

**Every LLM failure is a subclass of `LLMError`, and the exception message is already written
for the end user.** The UI catches one exception type and displays `str(exc)` — no stack traces
reach the screen, and there's no second copy of the wording in the UI to drift out of sync.

I chose **not** to auto-retry on 429. The free-tier limit is per-minute, so a silent retry would
spend another request and leave the UI looking hung. Telling the user to wait a few seconds is
more honest and, in practice, faster.

---

## Trade-offs I made

**Small model over a large one.** `ministral-8b-latest` answers in about 6 seconds. I started on
`mistral-small-latest` and found it returns HTTP 429 on the free tier, so it isn't the default.
For "suggest three clauses in JSON" the smaller model is accurate enough and the latency is the
difference between a usable form and one that feels broken. The model is a setting, so anyone
with a paid tier can point it at something larger without touching code.

**JSON mode, plus parsing that assumes it will fail anyway.** The request asks for
`response_format: json_object`, which makes malformed output rare. The parser still strips stray
```` ```json ```` fences, checks the shape, and skips individual entries that aren't clause-shaped.
Rare isn't never, and the cost of being wrong is a crash in front of a user.

**Templates as data rather than as code.** Costs a small loader and a field-spec format. Buys a
new document type for zero code change, which is the thing a firm would actually ask for next.

**Caching is a plain dict.** Streamlit re-runs the whole script on every interaction, so without
a cache the app re-reads and re-parses both template files and recompiles the Jinja template on
every keystroke. A module-level dict fixes that completely. Templates are read-only and there are
two of them — a TTL, an eviction policy, or an external cache would be machinery with nothing to
do. I deliberately cache *templates* and never *suggestions*, because suggestions are built from
one client's contract details and caching them across sessions is how you leak one firm's terms
into another's draft.

**Latency vs. perceived quality.** Three suggestions is the default. More would be slower and
give the reviewer more to read; fewer looks thin. Three fits on screen without scrolling.

---

## Known limitations

- Clause suggestions depend on a third-party API. No key, no suggestions — the rest still works.
- Generated clauses are **not** checked for legal correctness, enforceability, or jurisdiction
  fit. A human has to read them. The app is built around that assumption rather than apologising
  for it.
- Field values are sent to the model provider. For real use in a firm, that needs either a
  self-hosted model or a provider agreement — see below.
- DOCX only. PDF export would be the next format; I'd rather ship one export path that works
  than two that half-work.
- Two templates. The point is that adding more is a content task, not an engineering one.
- No persistence. Close the tab and the draft is gone. Nothing in the brief asked for storage,
  and storing clients' draft contracts is a decision that needs more thought than a six-hour build.

### What would have to change before a real firm used this

Document storage with access control and an audit trail of who generated what; a provider
agreement or a self-hosted model so client details never leave the firm's control; a template
approval workflow so a partner signs off template changes; and e-signature integration. None of
those are hard — they're just a different, larger project than the one in the brief.

---

## Requirement coverage

| Requirement | Where it lives |
|---|---|
| MUST — UI to input details and generate from a template | `app.py`, `templates/` |
| MUST — LLM suggests clauses based on user input | `docugen/llm.py` |
| MUST — Save as structured format + download | `docugen/export.py`, download button in `app.py` |
| SHOULD — Error handling, friendly messages, no crashes | `docugen/validation.py`, `docugen/llm.py`, `app.py` |
| SHOULD — Architecture documented with trade-offs | This file |
| COULD — Caching for frequently used templates | `docugen/templates.py`, tested in `tests/test_templates.py` |

---

## ⚖️ Legal disclaimer

DocuGenAI produces **draft** documents from standard templates. It is a drafting aid and **not
legal advice**. Nothing it generates is guaranteed to be legally valid, enforceable, or
appropriate for any jurisdiction or situation. Every document must be reviewed by a qualified
legal professional before it is signed or relied upon. The disclaimer is written into every
exported `.docx` as well as shown in the app, so it travels with the file.

---

## AI usage

**Tool used:** Claude (Anthropic), via Claude Code, through the whole build.

I want to be straightforward about this rather than undersell it: AI assistance was substantial
and spread across the project, not confined to one corner of it.

**Where it helped most:**

- **UI and UX.** The Streamlit layout, the sidebar, the accept/reject interaction and the wording
  of the on-screen messages were largely AI-drafted. This is the part I leaned on most — it's the
  area where I had the least prior experience, and it's the part I'd most want a second look at.
- **Template prose.** The NDA and Service Agreement body text was AI-drafted from standard clause
  structures, then read through and edited. It is illustrative boilerplate, not vetted legal text —
  which is exactly why the app insists a professional reviews the output.
- **First drafts of the modules.** `validation.py`, `llm.py`, `assembly.py` and `export.py` were
  drafted with AI and then reworked.
- **Test cases.** AI proposed a broad set, particularly the LLM failure modes.

**What I decided, checked, or changed afterwards:**

- **Provider and model.** I tested the API directly before writing the integration and found
  `mistral-small-latest` returns HTTP 429 on the free tier while `ministral-8b-latest` answers in
  ~6s. That measurement is why the default model is what it is, and it's why 429 is a first-class
  error case rather than something I imagined might happen.
- **Dropped Pydantic from the plan.** It was in my initial stack. Once fields became
  template-driven it would have meant constructing models at runtime, so I replaced it with a
  plain validator over the same spec.
- **Caught a preview/export mismatch.** `Document.to_text()` was upper-casing headings, so the
  on-screen preview didn't match the downloaded `.docx`. The test suite surfaced it and I fixed
  the preview rather than the test — the preview should show what you're actually going to get.
- **Found and fixed a crash that every unit test missed.** The app failed on load: I was passing
  `Template` objects as the dropdown's options, and Streamlit deep-copies widget options into
  session state — a compiled Jinja template can't be deep-copied. Sixty-one logic tests passed
  while the application was completely broken. I fixed the picker to use template ids, and then
  added `tests/test_app.py`, which drives the real app headlessly, so that whole class of bug
  can't pass silently again. This is the single most useful thing I did on this build, and it's
  a good argument against trusting a green test suite as evidence that software works.
- **Fixed a broken cross-reference in a template.** `service_agreement.j2` said "in accordance with
  clause 5". Once I moved numbering into `assembly.py`, accepting a clause could shift Termination
  away from 5. Replaced with a reference by name.
- **Moved section numbering out of the templates** once I worked through what happens when a user
  accepts a clause mid-document, and made clauses insert before the signature block.
- **Verified the whole pipeline end to end** against the live API: validation errors, a real model
  call, accepting two of three suggestions, and reopening the generated `.docx` with python-docx to
  confirm the accepted clause is in it and the rejected one isn't.
- **Ran the tests.** 72 passing. The two failures during development were both real bugs — the
  heading case mismatch and the load crash above — not flaky tests.


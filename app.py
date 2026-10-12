"""DocuGenAI - Streamlit interface.

This file is deliberately thin. It collects input, shows results and handles
button presses; every decision about what is valid, what the model is asked,
and what the finished document contains lives in the docugen package. That
split is what lets the logic be tested without starting a web server.
"""

from __future__ import annotations

import streamlit as st

from docugen import assembly, export, llm, templates, validation

st.set_page_config(page_title="DocuGenAI", page_icon="📄", layout="wide")

PREVIEW_HEIGHT = 560


def main() -> None:
    st.title("DocuGenAI")
    st.caption("Draft a standard legal document from a template, with optional AI-suggested clauses.")

    template = choose_template()
    if template is None:
        return

    reset_suggestions_if_template_changed(template.id)

    left, right = st.columns([1, 1], gap="large")

    with left:
        user_input = render_form(template)
        errors = validation.validate(template, user_input)
        show_errors(errors)
        render_suggestion_section(template, user_input, errors)

    with right:
        render_preview_and_download(template, user_input, errors)

    render_disclaimer()


def choose_template():
    """Template picker in the sidebar. Returns None if templates cannot be read."""
    st.sidebar.header("Template")
    try:
        # Loaded once up front so a malformed template file is reported here,
        # with a clear message, rather than from inside a widget callback.
        names = {
            template_id: templates.load_template(template_id).name
            for template_id in templates.available_template_ids()
        }
    except (templates.TemplateFormatError, OSError) as exc:
        st.error(f"Could not load the document templates: {exc}")
        return None

    if not names:
        st.error("No templates found in the templates/ folder.")
        return None

    # The options are ids rather than Template objects on purpose: Streamlit
    # deep-copies widget options into session state, and a Template holds a
    # compiled Jinja template, which cannot be deep-copied.
    choice_id = st.sidebar.selectbox(
        "Document type",
        options=list(names),
        format_func=lambda template_id: names[template_id],
        key="template_choice",
    )
    choice = templates.load_template(choice_id)  # free: already cached
    st.sidebar.caption(choice.description)

    st.sidebar.divider()
    st.sidebar.header("Clause suggestions")
    if llm.is_configured():
        st.sidebar.success("Language model configured")
    else:
        st.sidebar.warning(
            "No API key set. Suggestions are off, but you can still fill in the form "
            "and download the document. Copy .env.example to .env to enable them."
        )

    return choice


def reset_suggestions_if_template_changed(template_id: str) -> None:
    """Suggestions belong to one document type, so drop them on a switch."""
    if st.session_state.get("suggestions_for") != template_id:
        st.session_state["suggestions_for"] = template_id
        st.session_state["suggestions"] = []
        st.session_state["accepted"] = set()


def render_form(template) -> dict:
    """Build the input form from the template's field spec.

    Nothing here is hard-coded per document type - the widgets come from the
    JSON, which is what makes adding a template a no-code change.
    """
    st.subheader("1. Agreement details")
    user_input: dict = {}

    for field in template.fields:
        key = f"{template.id}.{field.id}"
        label = field.label + (" *" if field.required else "")

        if field.type == "text":
            user_input[field.id] = st.text_input(
                label, key=key, help=field.help, placeholder=field.placeholder
            )
        elif field.type == "textarea":
            user_input[field.id] = st.text_area(
                label, key=key, help=field.help, placeholder=field.placeholder, height=90
            )
        elif field.type == "date":
            user_input[field.id] = st.date_input(label, key=key, help=field.help, format="YYYY-MM-DD")
        elif field.type == "integer":
            user_input[field.id] = int(
                st.number_input(
                    label,
                    key=key,
                    help=field.help,
                    min_value=field.min if field.min is not None else 0,
                    max_value=field.max if field.max is not None else 10_000,
                    value=field.default if field.default is not None else (field.min or 1),
                    step=1,
                )
            )

    st.caption("\\* required")
    return user_input


def show_errors(errors: dict) -> None:
    if errors:
        st.error("Please fix the following before downloading:\n\n"
                 + "\n".join(f"- {message}" for message in errors.values()))


def render_suggestion_section(template, user_input: dict, errors: dict) -> None:
    """The AI step: request clauses, then accept or reject each one."""
    st.subheader("2. Suggested clauses")
    st.caption(
        "Optional. The model reads the details above and proposes extra clauses. "
        "Nothing reaches the document unless you tick it."
    )

    if not llm.is_configured():
        st.info("Clause suggestions are disabled because no API key is configured.")
        return

    disabled = bool(errors)
    if disabled:
        st.caption("Fill in the required details above to get suggestions relevant to this agreement.")

    if st.button("Suggest clauses", disabled=disabled, type="primary"):
        request_suggestions(template, user_input)

    render_suggestions()


def request_suggestions(template, user_input: dict) -> None:
    """Call the model, turning any failure into a message the user can act on."""
    try:
        with st.spinner("Asking the model for relevant clauses..."):
            clauses = llm.suggest_clauses(template, user_input)
    except llm.LLMError as exc:
        # Every llm failure carries a user-facing message, so the app degrades
        # to "no suggestions" instead of breaking the drafting flow.
        st.warning(str(exc))
        return

    st.session_state["suggestions"] = clauses
    st.session_state["accepted"] = set()


def render_suggestions() -> None:
    suggestions = st.session_state.get("suggestions", [])
    if not suggestions:
        return

    accepted = set()
    for index, clause in enumerate(suggestions):
        with st.container(border=True):
            keep = st.checkbox(
                f"**{clause.title}**",
                key=f"accept_{st.session_state['suggestions_for']}_{index}",
            )
            if clause.rationale:
                st.caption(f"Why: {clause.rationale}")
            with st.expander("Clause text", expanded=not keep):
                st.write(clause.body)
            if keep:
                accepted.add(index)

    st.session_state["accepted"] = accepted
    st.caption(f"{len(accepted)} of {len(suggestions)} suggestions accepted.")


def accepted_clauses() -> list:
    suggestions = st.session_state.get("suggestions", [])
    accepted = st.session_state.get("accepted", set())
    return [clause for index, clause in enumerate(suggestions) if index in accepted]


def render_preview_and_download(template, user_input: dict, errors: dict) -> None:
    """Live preview plus the download button."""
    st.subheader("3. Preview and download")

    if errors:
        st.info("The preview appears once the required details are filled in.")
        return

    try:
        document = assembly.assemble(template, user_input, accepted_clauses())
    except assembly.AssemblyError as exc:
        st.error(f"Could not build the document: {exc}")
        return

    # Rendered as plain text, never as markdown or HTML, so that whatever the
    # user typed is shown literally instead of being interpreted.
    st.text_area(
        "Document preview",
        value=document.to_text(),
        height=PREVIEW_HEIGHT,
        disabled=True,
        label_visibility="collapsed",
    )

    try:
        docx_bytes = export.to_docx_bytes(document)
    except Exception as exc:  # noqa: BLE001 - last line of defence before the UI
        st.error(f"Could not produce the Word file: {exc}")
        return

    st.download_button(
        "Download .docx",
        data=docx_bytes,
        file_name=export.suggested_filename(document),
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary",
    )


def render_disclaimer() -> None:
    st.divider()
    st.caption(
        "DocuGenAI produces draft documents from standard templates. It is a drafting "
        "aid, not legal advice. Every document must be reviewed by a qualified "
        "professional before it is signed or relied upon."
    )


if __name__ == "__main__":
    main()

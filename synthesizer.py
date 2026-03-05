"""
Writers Room — Synthesizer

Turns a user query + search results into a streamed natural-language answer
using GPT-4o-mini.  All callbacks are dispatched to the main thread.
"""

import threading
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from utils import call_on_main

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# System prompt — establishes the second-brain companion persona
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a thoughtful second-brain companion for a writer. \
You have access to excerpts from their personal notes.

When they ask a question:
- Synthesise a warm, insightful, specific answer based on the notes
- Speak directly to the writer: "You've been…" not "The notes show…"
- Reference specific note titles in [[double brackets]] when you cite them
- Be specific — name actual themes, phrases, ideas found in the notes
- Keep it to 2–4 sentences unless the question clearly warrants more
- If the notes don't clearly answer the question, say so honestly
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_stream(
    query: str,
    results: list[dict],
    on_chunk,
    on_done,
    on_error,
) -> None:
    """
    Start a background thread that streams a synthesis answer.

    All three callbacks are called on the main thread:
        on_chunk(text_so_far: str)  — called with accumulated text each token
        on_done(full_text: str)     — called once when streaming is complete
        on_error(err_msg: str)      — called on any exception
    """
    threading.Thread(
        target=_run,
        args=(query, results, on_chunk, on_done, on_error),
        daemon=True,
    ).start()


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _run(query, results, on_chunk, on_done, on_error) -> None:
    try:
        client = OpenAI()

        # Build context from top 8 results (600 chars each keeps tokens low)
        notes_text = "\n\n---\n\n".join(
            f"Title: {r['title']}\nFolder: {r['folder']}\n\n"
            f"{r.get('content', r.get('snippet', ''))[:600]}"
            for r in results[:8]
        )

        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {query}\n\nRelevant notes:\n\n{notes_text}",
                },
            ],
            max_tokens=250,
            temperature=0.7,
            stream=True,
        )

        full_text = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            full_text += delta
            if delta:
                _text = full_text  # capture for closure
                call_on_main(lambda t=_text: on_chunk(t))

        _final = full_text
        call_on_main(lambda: on_done(_final))

    except Exception as exc:
        _msg = str(exc)
        call_on_main(lambda: on_error(_msg))

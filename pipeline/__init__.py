"""SENTINEL pipeline. See CLAUDE.md for the stage layout; pipeline/schemas.py is the output contract.

Interface for the API:
    process_call(audio_path: str, call_id: str, *, on_event=None, transcripts="asr", no_llm=False) -> dict
returns a CallResult as dict and never raises for stage failures (they land in `stage_errors`, decision `review`).
Imported lazily so that `import pipeline.evaluate` does not pull in numpy / soundfile.
"""


def process_call(audio_path: str, call_id: str, **kw) -> dict:
    from pipeline.runner import process_call as _process_call
    return _process_call(audio_path, call_id, **kw)

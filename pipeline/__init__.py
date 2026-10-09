"""SENTINEL pipeline. See CLAUDE.md for the stage layout; pipeline/schemas.py is the output contract.

Interface for the API (to be implemented in a later milestone):
    process_call(audio_path: str, call_id: str) -> dict   # a CallResult as dict
"""

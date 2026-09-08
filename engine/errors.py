"""Typed failures the API layer maps to HTTP status codes."""
from __future__ import annotations


class SearchUnavailable(Exception):
    """Every configured provider failed, or none are configured."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RequiredSearchFailed(Exception):
    """policy=required and the model never performed a successful search."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StreamToolsRejected(Exception):
    """stream:true cannot be combined with the tool loop."""


FAIL_CLOSED_SUFFIX = "Do not present unverified facts as sourced."


def fail_closed_search(reason: str) -> str:
    """Tool-result string the model must not treat as facts.

    The ai-router string "answer from your own knowledge" is never emitted.
    """
    return f"ERROR: web_search unavailable ({reason}). {FAIL_CLOSED_SUFFIX}"


def fail_closed_fetch(reason: str) -> str:
    return f"ERROR: fetch_url unavailable ({reason}). {FAIL_CLOSED_SUFFIX}"


def fail_closed_budget(kind: str, limit: int) -> str:
    return (
        f"ERROR: {kind} budget exhausted (limit={limit}). {FAIL_CLOSED_SUFFIX}"
    )

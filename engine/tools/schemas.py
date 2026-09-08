"""OpenAI function-calling schemas the model sees."""
from __future__ import annotations

WEB_SEARCH_NAME = "web_search"
FETCH_URL_NAME = "fetch_url"
SEARCH_AND_READ_NAME = "search_and_read"

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": WEB_SEARCH_NAME,
        "description": (
            "Search the web across multiple providers and return the raw results "
            "(title, snippet, link, source). Results are not pre-filtered — "
            "weigh and cross-check them yourself. Use this when facts may have "
            "changed, need sources, or you do not already have a URL to read."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "num_results": {
                    "type": "integer",
                    "description": "Maximum organic hits to return (default 8).",
                },
                "recency_days": {
                    "type": "integer",
                    "description": "Prefer results from the last N days when the provider supports it.",
                },
            },
            "required": ["query"],
        },
    },
}

FETCH_URL_SCHEMA = {
    "type": "function",
    "function": {
        "name": FETCH_URL_NAME,
        "description": (
            "Fetch a URL and extract readable text (HTML or PDF). "
            "Use this after web_search when you need the page itself, not just the snippet. "
            "Only pass a URL that was actually returned by search or given by the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL to fetch."},
                "max_chars": {
                    "type": "integer",
                    "description": "Cap extracted text (default 8000 HTML / 25000 PDF).",
                },
            },
            "required": ["url"],
        },
    },
}

SEARCH_AND_READ_SCHEMA = {
    "type": "function",
    "function": {
        "name": SEARCH_AND_READ_NAME,
        "description": (
            "Search the web and fetch the top results in one step. "
            "Prefer this when you need sourced excerpts quickly (saves a tool round)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "top_n": {
                    "type": "integer",
                    "description": "How many top hits to fetch and extract (default 3).",
                },
            },
            "required": ["query"],
        },
    },
}

TOOL_SCHEMAS = {
    WEB_SEARCH_NAME: WEB_SEARCH_SCHEMA,
    FETCH_URL_NAME: FETCH_URL_SCHEMA,
    SEARCH_AND_READ_NAME: SEARCH_AND_READ_SCHEMA,
}

KNOWN_TOOLS = tuple(TOOL_SCHEMAS.keys())
DEFAULT_TOOLS = list(KNOWN_TOOLS)

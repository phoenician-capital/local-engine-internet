"""Prometheus metrics for the engine."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUESTS_TOTAL = Counter(
    "engine_requests_total",
    "HTTP requests",
    ["endpoint", "status"],
)
ACTIVE_REQUESTS = Gauge("engine_active_requests", "In-flight HTTP requests")
REQUEST_LATENCY_SECONDS = Histogram(
    "engine_request_latency_seconds",
    "Request latency",
    ["endpoint"],
)
SEARCH_TOTAL = Counter(
    "engine_search_total",
    "Search provider calls",
    ["provider", "status"],
)
FETCH_TOTAL = Counter(
    "engine_fetch_total",
    "Fetch ladder completions",
    ["tier", "status"],
)
TOOL_ROUNDS = Counter("engine_tool_rounds_total", "Agentic tool rounds completed")

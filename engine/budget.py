"""Per-request search / fetch / character budgets."""
from __future__ import annotations

from dataclasses import dataclass

from .config import settings

COMPACT_STUB = "[compacted: {dropped} chars dropped; URLs retained: {urls}]"


def _int_opt(web: dict, key: str, default: int) -> int:
    """Honor explicit 0. ``web.get(key) or default`` would swallow it."""
    if key not in web or web[key] is None or web[key] == "":
        return default
    try:
        return int(web[key])
    except (TypeError, ValueError):
        return default


@dataclass
class ToolBudget:
    max_search_uses: int = 0
    max_fetches: int = 0
    max_rounds: int = 0
    web_context_chars: int = 0
    searches_used: int = 0
    fetches_used: int = 0

    @classmethod
    def from_web_options(cls, web: dict | None) -> "ToolBudget":
        web = web or {}
        return cls(
            max_search_uses=max(0, _int_opt(web, "max_search_uses", settings.max_search_uses)),
            max_fetches=max(0, _int_opt(web, "max_fetches", settings.max_fetches)),
            max_rounds=max(1, _int_opt(web, "max_rounds", settings.max_tool_rounds)),
            web_context_chars=max(
                0, _int_opt(web, "web_context_budget_chars", settings.web_context_budget_chars)
            ),
        )

    def allow_search(self) -> bool:
        return self.searches_used < self.max_search_uses

    def allow_fetch(self) -> bool:
        return self.fetches_used < self.max_fetches

    def note_search(self) -> None:
        self.searches_used += 1

    def note_fetch(self) -> None:
        self.fetches_used += 1

    def trim_tool_messages(self, messages: list[dict]) -> list[dict]:
        """Compact oldest ``role=tool`` contents first when over the char budget."""
        if self.web_context_chars <= 0:
            return messages

        def _total() -> int:
            return sum(len(str(m.get("content") or "")) for m in messages if m.get("role") == "tool")

        compacted = True
        while _total() > self.web_context_chars and compacted:
            compacted = False
            for idx, message in enumerate(messages):
                if message.get("role") != "tool":
                    continue
                content = str(message.get("content") or "")
                if content.startswith("[compacted:") or len(content) < 80:
                    continue
                urls = _urls_in(content)
                messages[idx] = {
                    **message,
                    "content": COMPACT_STUB.format(
                        dropped=len(content),
                        urls=", ".join(urls) if urls else "(none)",
                    ),
                }
                compacted = True
                break
        return messages


def _urls_in(text: str) -> list[str]:
    urls: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[PUBLIC_URL:") and "]" in line:
            inner = line.split("]", 1)[0][len("[PUBLIC_URL:") :].strip()
            if inner:
                urls.append(inner)
    for token in text.split():
        if token.startswith("http://") or token.startswith("https://"):
            urls.append(token.strip("<>).,;[]"))
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

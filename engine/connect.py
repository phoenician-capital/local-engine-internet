"""How other apps plug this engine into an existing LLM client.

OpenAI Python, DeepSeek, Cursor, Continue, and Open WebUI all speak
chat-completions. They differ only in whether ``base_url`` includes ``/v1``.
We serve both ``/chat/completions`` and ``/v1/chat/completions``.
"""
from __future__ import annotations

from . import runtime
from .config import settings
from .plugin import plugin_status
from .search.merge import configured_providers


def public_base() -> str:
    return f"http://127.0.0.1:{settings.port}"


def connection_info() -> dict:
    base = public_base()
    providers = configured_providers()
    plugin = plugin_status()
    return {
        "search_ready": bool(providers) and bool(runtime.plugin_enabled),
        "plugin": plugin,
        "providers": providers,
        "openai_base_url": f"{base}/v1",
        "openai_base_url_no_v1": base,
        "model": settings.upstream_model,
        "api_key": settings.engine_api_key or "local",
        "snippets": {
            "openai_python": (
                "from openai import OpenAI\n"
                f'client = OpenAI(base_url="{base}/v1", api_key="{settings.engine_api_key or "local"}")\n'
                "r = client.chat.completions.create(\n"
                f'    model="{settings.upstream_model}",\n'
                '    messages=[{"role": "user", "content": "What is Phoenician Capital?"}],\n'
                ")\n"
                "print(r.choices[0].message.content)"
            ),
            "env": (
                f"export OPENAI_BASE_URL={base}/v1\n"
                f"export OPENAI_API_KEY={settings.engine_api_key or 'local'}\n"
                f"export DEEPSEEK_BASE_URL={base}"
            ),
            "cursor": (
                f"Settings → Models → OpenAI-compatible:\n"
                f"  Base URL  {base}/v1\n"
                f"  API Key   {settings.engine_api_key or 'local'}\n"
                f"  Model     {settings.upstream_model}"
            ),
            "continue": (
                "models:\n"
                "  - name: phoenician-web\n"
                "    provider: openai\n"
                f"    model: {settings.upstream_model}\n"
                f"    apiBase: {base}/v1\n"
                f"    apiKey: {settings.engine_api_key or 'local'}\n"
                "    env:\n"
                "      useLegacyCompletionsEndpoint: false"
            ),
            "litellm": (
                "model_list:\n"
                "  - model_name: phoenician-web\n"
                "    litellm_params:\n"
                f"      model: openai/{settings.upstream_model}\n"
                f"      api_base: {base}/v1\n"
                f"      api_key: {settings.engine_api_key or 'local'}"
            ),
        },
        "notes": [
            "Layer 1: the internet plugin is on or off (GET/POST /v1/plugin, or /ui).",
            "Layer 2: when on, the model decides whether this question needs the live web (policy: auto).",
            "Do not send phoenician_tools unless you want to opt out (empty list) or pin tools.",
            "Mode 2 (chat) needs UPSTREAM_LLM_BASE_URL pointing at ai-router or any OpenAI-compatible LLM.",
            "Mode 1 (POST /v1/search) works with search keys only — no Brain. 503 if the plugin is off.",
        ],
    }


def print_banner() -> None:
    info = connection_info()
    base = public_base()
    providers = ", ".join(info["providers"]) or "none — set SERPAPI_KEY"
    print()
    print(f"  local-engine-internet  {base}")
    print(f"  plugin                 {'on' if info['plugin']['enabled'] else 'off'}  (intelligence: {info['plugin']['intelligence']})")
    print(f"  search_ready           {info['search_ready']}  ({providers})")
    print()
    print("  Plug an LLM client in:")
    print(f'    OpenAI / Cursor / Continue  base_url="{base}/v1"  api_key="{info["api_key"]}"')
    print(f'    DeepSeek SDK                base_url="{base}"')
    print(f"    Toggle                      {base}/ui")
    print(f"    Docs                        {base}/docs")
    print()

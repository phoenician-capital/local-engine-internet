"""Non-interactive setup: ensure .env exists and print how to plug in an LLM."""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def run_setup(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine setup")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report what is configured (never print secret values).",
    )
    args = parser.parse_args(argv)

    example = ROOT / ".env.example"
    env_path = ROOT / ".env"
    if not env_path.exists():
        if example.exists():
            env_path.write_text(example.read_text())
            print(f"Wrote {env_path} from .env.example")
        else:
            print("No .env.example found — create .env yourself.")
            return 1
        print("Open .env and set SERPAPI_KEY (enough alone). Then add TAVILY_API_KEY / BRAVE_API_KEY.")
    else:
        print(f"Using existing {env_path}")

    vals = dotenv_values(env_path)
    checks = {
        "SERPAPI_KEY": bool((vals.get("SERPAPI_KEY") or vals.get("SERPAPI_API_KEY") or "").strip()),
        "TAVILY_API_KEY": bool((vals.get("TAVILY_API_KEY") or "").strip()),
        "BRAVE_API_KEY": bool((vals.get("BRAVE_API_KEY") or "").strip()),
        "UPSTREAM_LLM_BASE_URL": (vals.get("UPSTREAM_LLM_BASE_URL") or "http://127.0.0.1:8080").strip(),
    }
    print()
    print("Configured (values hidden):")
    print(f"  SERPAPI_KEY           {'yes' if checks['SERPAPI_KEY'] else 'NO — search needs this or Tavily/Brave'}")
    print(f"  TAVILY_API_KEY        {'yes' if checks['TAVILY_API_KEY'] else 'no (optional, recommended)'}")
    print(f"  BRAVE_API_KEY         {'yes' if checks['BRAVE_API_KEY'] else 'no (optional, recommended)'}")
    print(f"  UPSTREAM_LLM_BASE_URL {checks['UPSTREAM_LLM_BASE_URL']}")
    print()
    if not (checks["SERPAPI_KEY"] or checks["TAVILY_API_KEY"] or checks["BRAVE_API_KEY"]):
        print("No search key yet. Get SerpAPI at https://serpapi.com and paste SERPAPI_KEY= into .env")
        print()

    from .connect import print_banner

    print_banner()
    print("Start the engine:")
    print("  python -m engine")
    print("Prove search:")
    print("  python scripts/check_search.py")
    if args.check:
        return 0 if (checks["SERPAPI_KEY"] or checks["TAVILY_API_KEY"] or checks["BRAVE_API_KEY"]) else 1
    return 0
